import { describe, it, expect } from "vitest";
import { validateStateMachine } from "../src/engine/validation.js";
import type { StateMachineDef } from "../src/types.js";

// Import the bundled state machine to verify it passes validation
import stateMachine from "../src/schema/state_machine.json";

describe("validateStateMachine", () => {
  it("should validate the bundled state machine", () => {
    const errors = validateStateMachine(stateMachine as StateMachineDef);
    expect(errors).toEqual([]);
  });

  it("should reject missing states", () => {
    const errors = validateStateMachine({ transitions: [] } as unknown as StateMachineDef);
    expect(errors).toContain("Missing required key: 'states'");
  });

  it("should reject missing transitions", () => {
    const errors = validateStateMachine({
      states: { ACTIVE: { terminal: false } },
    } as unknown as StateMachineDef);
    expect(errors).toContain("Missing required key: 'transitions'");
  });

  it("should reject missing terminal state", () => {
    const sm: StateMachineDef = {
      states: {
        ACTIVE: { terminal: false },
        DONE: { terminal: false },
      },
      transitions: [
        {
          id: "T01",
          from_state: "ACTIVE",
          to_state: "DONE",
          allowed_roles: ["EXECUTOR"],
          guards: [],
        },
      ],
    };
    const errors = validateStateMachine(sm);
    expect(errors.some((e) => e.includes("terminal"))).toBe(true);
  });

  it("should reject duplicate transition IDs", () => {
    const sm: StateMachineDef = {
      states: {
        A: { terminal: false },
        B: { terminal: true },
      },
      transitions: [
        { id: "T01", from_state: "A", to_state: "B", allowed_roles: ["EX"], guards: [] },
        { id: "T01", from_state: "A", to_state: "B", allowed_roles: ["EX"], guards: [] },
      ],
    };
    const errors = validateStateMachine(sm);
    expect(errors.some((e) => e.includes("Duplicate"))).toBe(true);
  });

  it("should reject undefined state references", () => {
    const sm: StateMachineDef = {
      states: {
        A: { terminal: false },
        B: { terminal: true },
      },
      transitions: [
        { id: "T01", from_state: "A", to_state: "C", allowed_roles: ["EX"], guards: [] },
      ],
    };
    const errors = validateStateMachine(sm);
    expect(errors.some((e) => e.includes("not in defined states"))).toBe(true);
  });

  it("should reject terminal states with outbound transitions", () => {
    const sm: StateMachineDef = {
      states: {
        A: { terminal: false },
        B: { terminal: true },
      },
      transitions: [
        { id: "T01", from_state: "A", to_state: "B", allowed_roles: ["EX"], guards: [] },
        { id: "T02", from_state: "B", to_state: "A", allowed_roles: ["EX"], guards: [] },
      ],
    };
    const errors = validateStateMachine(sm);
    expect(errors.some((e) => e.includes("Terminal state"))).toBe(true);
  });

  it("should detect orphan states", () => {
    const sm: StateMachineDef = {
      states: {
        A: { terminal: false },
        B: { terminal: true },
        ORPHAN: { terminal: false },
      },
      transitions: [
        { id: "T01", from_state: "A", to_state: "B", allowed_roles: ["EX"], guards: [] },
      ],
    };
    const errors = validateStateMachine(sm);
    expect(errors.some((e) => e.includes("Orphan"))).toBe(true);
  });
});
