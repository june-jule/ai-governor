/**
 * Executor Governor Guards (EG-01 through EG-08).
 *
 * These guards gate the ACTIVE -> READY_FOR_REVIEW transition. They validate
 * that an executor agent has produced sufficient evidence and deliverables
 * before submitting work for review.
 */

import { GuardContext, GuardResult } from "../types.js";
import { registerGuard } from "../engine/guards.js";

function normEnum(value: unknown): string {
  return String(value ?? "").trim().toUpperCase();
}

// ------------------------------------------------------------------
// EG-01: Self-review must exist
// ------------------------------------------------------------------

function guardSelfReviewExists(ctx: GuardContext): GuardResult {
  let count = 0;
  for (const r of ctx.relationships) {
    if (r.type === "HAS_REVIEW") {
      if (normEnum(r.node.review_type) === "SELF_REVIEW") {
        count++;
      }
    }
  }
  if (count < 1) {
    return new GuardResult(
      "EG-01",
      false,
      "No SELF_REVIEW found",
      "Create a self-review before submission",
    );
  }
  return new GuardResult("EG-01", true, "Self-review exists");
}

// ------------------------------------------------------------------
// EG-02: Report must exist (task-type aware severity)
// ------------------------------------------------------------------

function guardReportExists(ctx: GuardContext): GuardResult {
  const taskType = normEnum(ctx.task.task_type);
  const count = ctx.relationships.filter((r) => r.type === "REPORTS_ON").length;

  if (count >= 1) {
    return new GuardResult("EG-02", true, "Report exists");
  }

  const mandatoryTypes = new Set(["INVESTIGATION", "AUDIT"]);
  const warningTypes = new Set(["IMPLEMENTATION", "DEPLOY"]);

  if (mandatoryTypes.has(taskType)) {
    return new GuardResult(
      "EG-02",
      false,
      `No report found (mandatory for ${taskType})`,
      "Create and link a report before submission",
    );
  }
  if (warningTypes.has(taskType)) {
    return new GuardResult(
      "EG-02",
      true,
      `No report found (warning for ${taskType} — non-blocking)`,
      "Create a report for better traceability",
      true,
    );
  }
  return new GuardResult(
    "EG-02",
    true,
    "No report found (warning — non-blocking)",
    "Create a report for better traceability",
    true,
  );
}

// ------------------------------------------------------------------
// EG-03: Deliverables exist (report or filesystem)
// ------------------------------------------------------------------

function guardDeliverablesExist(ctx: GuardContext): GuardResult {
  // In TypeScript SDK, we skip filesystem checks (browser compatibility).
  // Instead, we check for linked reports or declared deliverables.
  const reportCount = ctx.relationships.filter(
    (r) => r.type === "REPORTS_ON",
  ).length;

  const deliverables = ctx.task.deliverables;
  let paths: string[] = [];

  if (deliverables) {
    if (typeof deliverables === "string") {
      try {
        const parsed = JSON.parse(deliverables);
        if (Array.isArray(parsed)) paths = parsed;
        else if (typeof parsed === "string") paths = [parsed];
      } catch {
        paths = deliverables
          .split("\n")
          .map((p) => p.trim())
          .filter(Boolean);
      }
    }
  }

  if (paths.length === 0) {
    if (reportCount >= 1) {
      return new GuardResult(
        "EG-03",
        true,
        `No filesystem deliverables declared; satisfied by ${reportCount} linked report(s)`,
      );
    }
    const taskType = normEnum(ctx.task.task_type);
    if (taskType === "INVESTIGATION" || taskType === "AUDIT") {
      return new GuardResult(
        "EG-03",
        false,
        `No deliverables declared and no report linked (required for ${taskType})`,
        "Link a report or add file paths under a Deliverables section",
      );
    }
    return new GuardResult(
      "EG-03",
      true,
      "No deliverables declared (nothing to verify)",
    );
  }

  // With paths declared, check if report satisfies the requirement
  if (reportCount >= 1) {
    return new GuardResult(
      "EG-03",
      true,
      `Deliverables declared; satisfied by ${reportCount} linked report(s)`,
    );
  }

  // TS SDK: pass with a note that filesystem checks are not available
  return new GuardResult(
    "EG-03",
    true,
    `${paths.length} deliverables declared (filesystem verification not available in TS SDK)`,
  );
}

// ------------------------------------------------------------------
// EG-04: Non-DEPLOY tasks must not contain deploy commands
// ------------------------------------------------------------------

const FORBIDDEN_DEPLOY_PATTERNS = [
  "kubectl apply",
  "kubectl delete",
  "kubectl rollout",
  "terraform apply",
  "terraform destroy",
  "helm install",
  "helm upgrade",
  "docker push",
  "gcloud deploy",
  "gcloud app deploy",
  "gcloud run deploy",
  "aws deploy",
  "aws ecs update-service",
  "aws lambda update-function",
  "pulumi up",
  "ansible-playbook",
  "cdk deploy",
];

function guardNoImpliedDeploys(ctx: GuardContext): GuardResult {
  const taskType = normEnum(ctx.task.task_type);
  if (taskType === "DEPLOY") {
    return new GuardResult("EG-04", true, "Skipped — DEPLOY tasks are exempt");
  }
  const content = String(ctx.task.content ?? "").toLowerCase();
  for (const pat of FORBIDDEN_DEPLOY_PATTERNS) {
    if (content.includes(pat)) {
      return new GuardResult(
        "EG-04",
        false,
        `Forbidden deploy pattern found: ${pat}`,
        "Remove deploy commands from non-DEPLOY task content",
      );
    }
  }
  return new GuardResult("EG-04", true, "No implied deploys");
}

// ------------------------------------------------------------------
// EG-05: No secrets in task content
// ------------------------------------------------------------------

const SECRET_PATTERNS: [RegExp, string][] = [
  [/(?:password|passwd|pwd)\s*[:=]\s*['"]?[^\s'"]{3,}['"]?/i, "password assignment"],
  [/(?:api[_-]?key|apikey)\s*[:=]\s*['"]?[^\s'"]{3,}['"]?/i, "API key assignment"],
  [/(?:secret|token)\s*[:=]\s*['"]?[^\s'"]{20,}['"]?/i, "secret/token assignment"],
  [/-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----/i, "private key block"],
  [/(?:aws_access_key_id|aws_secret_access_key)\s*[:=]\s*['"]?\S+/i, "AWS credential"],
  [/ghp_[A-Za-z0-9_]{36,}/, "GitHub personal access token"],
  [/sk-[A-Za-z0-9]{20,}/, "API secret key pattern"],
  [/(?:bearer|authorization)\s*[:=]\s*['"]?[^\s'"]{20,}/i, "authorization header value"],
];

function guardNoSecretsInContent(ctx: GuardContext): GuardResult {
  const content = String(ctx.task.content ?? "");
  if (!content) {
    return new GuardResult("EG-05", true, "No content to scan");
  }
  for (const [pattern, desc] of SECRET_PATTERNS) {
    if (pattern.test(content)) {
      return new GuardResult(
        "EG-05",
        false,
        `Potential secret detected in task content: ${desc}`,
        "Remove credentials from task content. Use environment variables or a secrets manager instead.",
      );
    }
  }
  return new GuardResult("EG-05", true, "No secrets detected in content");
}

// ------------------------------------------------------------------
// EG-06: DEPLOY tasks must mention rollback plan
// ------------------------------------------------------------------

function guardDeployRollbackPlan(ctx: GuardContext): GuardResult {
  if (normEnum(ctx.task.task_type) !== "DEPLOY") {
    return new GuardResult("EG-06", true, "Skipped — task type is not DEPLOY");
  }
  const content = String(ctx.task.content ?? "");
  if (/rollback|revert|undo|recovery|fallback/i.test(content)) {
    return new GuardResult("EG-06", true, "Rollback/revert strategy found");
  }
  return new GuardResult(
    "EG-06",
    false,
    "DEPLOY task missing rollback/revert strategy",
    "Add rollback strategy to task content",
  );
}

// ------------------------------------------------------------------
// EG-07: AUDIT tasks must reference >= 2 evidence sources
// ------------------------------------------------------------------

function guardAuditMultiSource(ctx: GuardContext): GuardResult {
  if (normEnum(ctx.task.task_type) !== "AUDIT") {
    return new GuardResult("EG-07", true, "Skipped — task type is not AUDIT");
  }

  const taskContent = String(ctx.task.content ?? "");
  const reportChunks: string[] = [];
  const evidenceSources = new Set<string>();

  for (const r of ctx.relationships) {
    if (r.type !== "REPORTS_ON") continue;
    const node = r.node;
    const reportContent = node.content;
    if (reportContent) reportChunks.push(String(reportContent));

    let metadataObj: Record<string, unknown> | null = null;
    const metadataRaw = node.metadata;
    if (typeof metadataRaw === "object" && metadataRaw != null) {
      metadataObj = metadataRaw as Record<string, unknown>;
    } else if (typeof metadataRaw === "string" && metadataRaw.trim()) {
      try {
        const parsed = JSON.parse(metadataRaw);
        if (typeof parsed === "object" && parsed != null) {
          metadataObj = parsed as Record<string, unknown>;
        }
      } catch {
        // ignore parse errors
      }
    }

    if (metadataObj) {
      for (const key of [
        "evidence_sources",
        "sources",
        "references",
        "citations",
        "evidence",
      ]) {
        const val = metadataObj[key];
        if (Array.isArray(val)) {
          for (const item of val) {
            if (item != null) {
              const s = String(item).trim();
              if (s) evidenceSources.add(s);
            }
          }
        } else if (typeof val === "string") {
          const s = val.trim();
          if (s) evidenceSources.add(s);
        }
      }
    }
  }

  const combined = `${taskContent}\n${reportChunks.join("\n")}`;
  const matches = combined.match(
    /(?:source|evidence|verified|confirmed|cross-check|reference)/gi,
  );
  const keywordCount = matches?.length ?? 0;

  if (keywordCount >= 2 || evidenceSources.size >= 2) {
    return new GuardResult(
      "EG-07",
      true,
      `Multi-source evidence found (keyword_refs=${keywordCount}, explicit_sources=${evidenceSources.size})`,
    );
  }

  return new GuardResult(
    "EG-07",
    false,
    `Need >= 2 evidence sources, found keyword_refs=${keywordCount}, explicit_sources=${evidenceSources.size}`,
    "Add >= 2 evidence sources to the audit task content or linked report",
  );
}

// ------------------------------------------------------------------
// EG-08: IMPLEMENTATION tasks must reference tests
// ------------------------------------------------------------------

function guardImplementationTests(ctx: GuardContext): GuardResult {
  if (normEnum(ctx.task.task_type) !== "IMPLEMENTATION") {
    return new GuardResult(
      "EG-08",
      true,
      "Skipped — task type is not IMPLEMENTATION",
    );
  }
  const content = String(ctx.task.content ?? "");
  const notes = String(ctx.task.notes ?? "");
  const combined = `${content}\n${notes}`;
  const matches = combined.match(/(?:test|verify|validation|assert|check)/gi);
  if (matches && matches.length >= 1) {
    return new GuardResult("EG-08", true, "Test/verification references found");
  }
  return new GuardResult(
    "EG-08",
    false,
    "IMPLEMENTATION task missing test/verification references.",
    "Add test or verification references in task content or notes.",
  );
}

// ------------------------------------------------------------------
// Register all guards
// ------------------------------------------------------------------

export function registerBuiltinGuards(): void {
  registerGuard("EG-01", guardSelfReviewExists, false);
  registerGuard("EG-02", guardReportExists, false);
  registerGuard("EG-03", guardDeliverablesExist, false);
  registerGuard("EG-04", guardNoImpliedDeploys, false);
  registerGuard("EG-05", guardNoSecretsInContent, false);
  registerGuard("EG-06", guardDeployRollbackPlan, false);
  registerGuard("EG-07", guardAuditMultiSource, false);
  registerGuard("EG-08", guardImplementationTests, false);
}

// Auto-register on import
registerBuiltinGuards();
