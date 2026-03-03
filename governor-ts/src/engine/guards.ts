/**
 * Guard infrastructure — registry, resolution, and inline guard factory.
 *
 * Guards are functions (sync or async) that receive a GuardContext and
 * return a GuardResult. They are registered by ID in a global registry,
 * or defined inline in the state machine JSON.
 */

import { GuardContext, GuardResult } from "../types.js";
import type { GuardCallable, InlineGuardDef } from "../types.js";

// Global guard registry
const _guardRegistry = new Map<string, GuardCallable>();

/**
 * Register a guard function by ID in the global registry.
 */
export function registerGuard(
  guardId: string,
  fn: GuardCallable,
  overwrite = true,
): void {
  if (!overwrite && _guardRegistry.has(guardId)) return;
  _guardRegistry.set(guardId, fn);
}

/**
 * Get a guard from the global registry.
 */
export function getGuard(guardId: string): GuardCallable | undefined {
  return _guardRegistry.get(guardId);
}

/**
 * Clear all guards (useful for tests).
 */
export function clearGuards(): void {
  _guardRegistry.clear();
}

/**
 * Get a read-only snapshot of the global registry (for engine instance copy).
 */
export function getRegistrySnapshot(): Map<string, GuardCallable> {
  return new Map(_guardRegistry);
}

/**
 * Walk a dotted path into a nested object.
 * Returns [found, value].
 */
function getNested(
  obj: Record<string, unknown>,
  dottedPath: string,
): [boolean, unknown] {
  const parts = dottedPath.split(".");
  let current: unknown = obj;
  for (const part of parts) {
    if (current == null || typeof current !== "object") return [false, undefined];
    current = (current as Record<string, unknown>)[part];
  }
  return [current !== undefined, current];
}

/**
 * Create a property_set guard from an inline definition.
 */
function makePropertySetGuard(guardDef: InlineGuardDef): GuardCallable {
  const guardId = guardDef.guard_id;
  const check = guardDef.check ?? "";
  const match = check.match(/^property_set\((.+)\)$/);
  if (!match) {
    return () =>
      new GuardResult(guardId, false, `Invalid check syntax: ${check}`);
  }
  const path = match[1];

  return (ctx: GuardContext) => {
    // Check transition params first, then task
    const [foundP, valP] = getNested(
      ctx.transitionParams as Record<string, unknown>,
      path,
    );
    if (foundP && valP != null && valP !== "" && valP !== false) {
      return new GuardResult(guardId, true, `Property '${path}' is set (via params)`);
    }
    const [foundT, valT] = getNested(
      ctx.task as Record<string, unknown>,
      path,
    );
    if (foundT && valT != null && valT !== "" && valT !== false) {
      return new GuardResult(guardId, true, `Property '${path}' is set (via task)`);
    }
    return new GuardResult(
      guardId,
      false,
      `Property '${path}' is not set`,
      `Set '${path}' in task or transition_params`,
    );
  };
}

/**
 * Resolve a guard reference (string ID, inline dict) to [guardId, callable].
 * Checks instanceRegistry first, then global registry.
 */
export function resolveGuard(
  guardRef: string | InlineGuardDef,
  strict = false,
  instanceRegistry?: Map<string, GuardCallable>,
): [string, GuardCallable] {
  if (typeof guardRef === "string") {
    const guardId = guardRef;
    const fn =
      instanceRegistry?.get(guardId) ?? _guardRegistry.get(guardId);
    if (fn) return [guardId, fn];
    if (strict) {
      throw new Error(`Guard not found in registry: '${guardId}'`);
    }
    return [
      guardId,
      () => new GuardResult(guardId, true, `Guard '${guardId}' not registered — pass-through`),
    ];
  }

  // Inline guard definition (dict with guard_id + check)
  const def = guardRef as InlineGuardDef;
  const guardId = def.guard_id;
  if (!guardId) {
    throw new Error("Inline guard missing 'guard_id'");
  }

  const check = def.check ?? "";
  if (check.startsWith("property_set(")) {
    return [guardId, makePropertySetGuard(def)];
  }

  // Look up by guard_id as fallback
  const fn =
    instanceRegistry?.get(guardId) ?? _guardRegistry.get(guardId);
  if (fn) return [guardId, fn];
  if (strict) {
    throw new Error(`Guard not found: '${guardId}'`);
  }
  return [
    guardId,
    () => new GuardResult(guardId, true, `Guard '${guardId}' not registered — pass-through`),
  ];
}
