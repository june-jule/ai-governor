# Governor TypeScript SDK

State-machine-enforced quality gates for AI agent output. Zero dependencies. Wire-compatible with the Python engine.

## Quickstart

```bash
npm install @governor/core
```

```typescript
import { MemoryBackend, TransitionEngine } from "@governor/core";

// 1. Create backend + engine
const backend = new MemoryBackend();
const engine = new TransitionEngine(backend);

// 2. Create a task
await backend.createTask({
  task_id: "TASK_001",
  task_name: "Ship login feature",
  task_type: "IMPLEMENTATION",
  role: "DEVELOPER",
  status: "ACTIVE",
  priority: "HIGH",
  content: "Implement OAuth login. All tests pass.",
});

// 3. Add required evidence
await backend.addReview("TASK_001", { review_type: "SELF_REVIEW", rating: 8 });
await backend.addReport("TASK_001", { report_type: "IMPLEMENTATION" });

// 4. Transition — guards enforce quality automatically
const result = await engine.transitionTask("TASK_001", "READY_FOR_REVIEW", "EXECUTOR");
console.log(result.result); // "PASS"
```

## What Happens When Guards Block

```typescript
// Try to submit WITHOUT a self-review
const result = await engine.transitionTask("TASK_001", "READY_FOR_REVIEW", "EXECUTOR");

console.log(result.result); // "FAIL"
for (const gr of result.guard_results ?? []) {
  if (!gr.passed) {
    console.log(`  BLOCKED by ${gr.guard_id}: ${gr.reason}`);
    console.log(`  Fix: ${gr.fix_hint}`);
  }
}
// Output:
//   BLOCKED by EG-01: No SELF_REVIEW found
//   Fix: Create a self-review before submission
```

## Built-in Guards (EG-01 through EG-08)

| Guard | What it checks |
|-------|---------------|
| EG-01 | Self-review exists |
| EG-02 | Report linked (severity varies by task type) |
| EG-03 | Deliverables exist (report satisfies) |
| EG-04 | No deploy commands in non-DEPLOY tasks |
| EG-05 | No secrets/credentials in content |
| EG-06 | DEPLOY tasks have rollback plan |
| EG-07 | AUDIT tasks have >= 2 evidence sources |
| EG-08 | IMPLEMENTATION tasks reference tests |

## Custom Guards

```typescript
import { registerGuard, GuardContext, GuardResult } from "@governor/core";

registerGuard("CUSTOM-01", (ctx: GuardContext) => {
  const hasApproval = ctx.task.content?.includes("approved");
  return new GuardResult(
    "CUSTOM-01",
    hasApproval ?? false,
    hasApproval ? "Approval found" : "Missing approval",
    "Add 'approved' to task content",
  );
});
```

## API Compatibility

This SDK is wire-compatible with the Python Governor engine. The same `state_machine.json` powers both. Tasks created in Python can be evaluated in TypeScript and vice versa.

## Feature Parity with Python SDK

The TypeScript SDK (v0.1.0) implements the core engine. Some Python SDK features are not yet available:

| Feature | Python | TypeScript | Status |
|---------|--------|------------|--------|
| State machine enforcement | Yes | Yes | Parity |
| Built-in guards (EG-01–EG-08) | Yes | Yes | Parity |
| MemoryBackend | Yes | Yes | Parity |
| Neo4jBackend | Yes | Yes | Parity |
| Custom guard registration | Yes | Yes | Parity |
| Role aliases | Yes | Yes | Parity |
| State machine validation | Yes | Yes | Parity |
| Graph analytics (GDS) | Yes | No | Planned |
| MCP tool wrappers | Yes | No | Planned |
| Async engine | Yes | N/A | TS is async-native |
| Scoring rubrics | Yes | No | Planned |
| Event callbacks | Yes | Partial | In progress |
| Rate limiting | Yes | No | Planned |
| Telemetry (OpenTelemetry) | Yes | No | Planned |

Contributions for missing features are welcome.

## Development

```bash
npm install
npm test        # Run tests
npm run build   # Build for distribution
```
