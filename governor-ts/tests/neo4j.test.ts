/**
 * Mock-based tests for the Neo4j backend.
 *
 * These tests verify the Neo4jBackend's query construction and result handling
 * without requiring a running Neo4j instance. We mock the neo4j-driver module
 * and inspect the queries/params sent to it.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// -----------------------------------------------------------------------
// Mock neo4j-driver at module level BEFORE importing Neo4jBackend
// -----------------------------------------------------------------------

interface MockTx {
  run: ReturnType<typeof vi.fn>;
}

interface MockSession {
  executeRead: ReturnType<typeof vi.fn>;
  executeWrite: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
}

// vi.hoisted() runs before vi.mock() hoisting, so these variables are
// available inside the mock factory and survive vi.clearAllMocks().
const { mockDriver, mockSession } = vi.hoisted(() => {
  const mockSession: MockSession = {
    executeRead: vi.fn(),
    executeWrite: vi.fn(),
    close: vi.fn().mockResolvedValue(undefined),
  };
  const mockDriver = {
    session: vi.fn().mockReturnValue(mockSession),
    close: vi.fn().mockResolvedValue(undefined),
    getServerInfo: vi.fn().mockResolvedValue({
      address: "localhost:7687",
      agent: "Neo4j/5.0.0",
      protocolVersion: 5.0,
    }),
  };
  return { mockDriver, mockSession };
});

function makeRecords(rows: Record<string, unknown>[]) {
  return {
    records: rows.map((row) => ({
      toObject: () => row,
    })),
  };
}

vi.mock("neo4j-driver", () => {
  return {
    default: {
      driver: vi.fn().mockReturnValue(mockDriver),
      auth: {
        basic: vi.fn().mockReturnValue({ scheme: "basic" }),
      },
      int: vi.fn((n: number) => ({ low: n, high: 0 })),
    },
  };
});

// Import AFTER mock is set up
import { Neo4jBackend } from "../src/backend/neo4j.js";

describe("Neo4jBackend", () => {
  let backend: Neo4jBackend;

  beforeEach(async () => {
    vi.clearAllMocks();
    mockDriver.session.mockReturnValue(mockSession);
    mockSession.close.mockResolvedValue(undefined);

    backend = await Neo4jBackend.create({
      uri: "neo4j://localhost:7687",
      user: "neo4j",
      password: "test",
    });
  });

  afterEach(async () => {
    await backend.close();
  });

  // ------------------------------------------------------------------
  // getTask
  // ------------------------------------------------------------------

  it("should fetch a task with relationships", async () => {
    mockSession.executeRead.mockImplementation(async (fn: (tx: MockTx) => Promise<unknown>) => {
      const tx: MockTx = {
        run: vi.fn().mockResolvedValue(
          makeRecords([
            {
              task: { task_id: "T1", status: "ACTIVE", task_name: "Test" },
              out_rels: [
                {
                  type: "HAS_REVIEW",
                  node: { review_type: "SELF_REVIEW" },
                  node_labels: ["Review"],
                },
              ],
              in_rels: [],
            },
          ]),
        ),
      };
      return fn(tx);
    });

    const result = await backend.getTask("T1");
    expect(result.task.task_id).toBe("T1");
    expect(result.task.status).toBe("ACTIVE");
    expect(result.relationships).toHaveLength(1);
    expect(result.relationships[0].type).toBe("HAS_REVIEW");
  });

  it("should throw when task not found", async () => {
    mockSession.executeRead.mockImplementation(async (fn: (tx: MockTx) => Promise<unknown>) => {
      const tx: MockTx = { run: vi.fn().mockResolvedValue(makeRecords([])) };
      return fn(tx);
    });

    await expect(backend.getTask("NONEXISTENT")).rejects.toThrow("not found");
  });

  // ------------------------------------------------------------------
  // updateTask
  // ------------------------------------------------------------------

  it("should update a task and return new status", async () => {
    mockSession.executeWrite.mockImplementation(async (fn: (tx: MockTx) => Promise<unknown>) => {
      const tx: MockTx = {
        run: vi.fn().mockResolvedValue(
          makeRecords([{ task_id: "T1", status: "READY_FOR_REVIEW" }]),
        ),
      };
      return fn(tx);
    });

    const result = await backend.updateTask("T1", {
      status: "READY_FOR_REVIEW",
    });
    expect(result.success).toBe(true);
    expect(result.new_status).toBe("READY_FOR_REVIEW");
  });

  it("should detect STATE_CONFLICT on update", async () => {
    // First call (write): no records returned (CAS failed)
    mockSession.executeWrite.mockImplementation(async (fn: (tx: MockTx) => Promise<unknown>) => {
      const tx: MockTx = { run: vi.fn().mockResolvedValue(makeRecords([])) };
      return fn(tx);
    });

    // Second call (read for taskExists) and third call (read for current status)
    let readCallCount = 0;
    mockSession.executeRead.mockImplementation(async (fn: (tx: MockTx) => Promise<unknown>) => {
      readCallCount++;
      if (readCallCount === 1) {
        // taskExists
        const tx: MockTx = {
          run: vi.fn().mockResolvedValue(makeRecords([{ cnt: 1 }])),
        };
        return fn(tx);
      }
      // get current status
      const tx: MockTx = {
        run: vi.fn().mockResolvedValue(makeRecords([{ status: "COMPLETED" }])),
      };
      return fn(tx);
    });

    const result = await backend.updateTask(
      "T1",
      { status: "READY_FOR_REVIEW" },
      "ACTIVE",
    );
    expect(result.success).toBe(false);
    expect(result.error_code).toBe("STATE_CONFLICT");
    expect(result.actual_current_status).toBe("COMPLETED");
  });

  // ------------------------------------------------------------------
  // taskExists
  // ------------------------------------------------------------------

  it("should check task existence", async () => {
    mockSession.executeRead.mockImplementation(async (fn: (tx: MockTx) => Promise<unknown>) => {
      const tx: MockTx = {
        run: vi.fn().mockResolvedValue(makeRecords([{ cnt: 1 }])),
      };
      return fn(tx);
    });

    expect(await backend.taskExists("T1")).toBe(true);
  });

  it("should return false for non-existent task", async () => {
    mockSession.executeRead.mockImplementation(async (fn: (tx: MockTx) => Promise<unknown>) => {
      const tx: MockTx = {
        run: vi.fn().mockResolvedValue(makeRecords([{ cnt: 0 }])),
      };
      return fn(tx);
    });

    expect(await backend.taskExists("NOPE")).toBe(false);
  });

  // ------------------------------------------------------------------
  // applyTransition
  // ------------------------------------------------------------------

  it("should apply transition atomically", async () => {
    mockSession.executeWrite.mockImplementation(async (fn: (tx: MockTx) => Promise<unknown>) => {
      const tx: MockTx = {
        run: vi.fn().mockResolvedValue(
          makeRecords([
            {
              task_id: "T1",
              status: "READY_FOR_REVIEW",
              event_id: "evt-123",
            },
          ]),
        ),
      };
      return fn(tx);
    });

    const result = await backend.applyTransition(
      "T1",
      { status: "READY_FOR_REVIEW" },
      {
        event_id: "EVT_001",
        task_id: "T1",
        transition_id: "T01",
        from_state: "ACTIVE",
        to_state: "READY_FOR_REVIEW",
        result: "PASS",
        guard_results: [
          { guard_id: "EG-01", passed: true, reason: "ok", fix_hint: "" },
        ],
      },
      "ACTIVE",
    );

    expect(result.success).toBe(true);
    expect(result.event_id).toBe("evt-123");
  });

  // ------------------------------------------------------------------
  // recordTransitionEvent
  // ------------------------------------------------------------------

  it("should record a transition event", async () => {
    mockSession.executeWrite.mockImplementation(async (fn: (tx: MockTx) => Promise<unknown>) => {
      const tx: MockTx = {
        run: vi.fn().mockResolvedValue(
          makeRecords([{ event_id: "evt-456" }]),
        ),
      };
      return fn(tx);
    });

    const result = await backend.recordTransitionEvent({
      event_id: "EVT_002",
      task_id: "T1",
      transition_id: "T01",
      from_state: "ACTIVE",
      to_state: "READY_FOR_REVIEW",
      result: "PASS",
    });
    expect(result.success).toBe(true);
    expect(result.event_id).toBe("evt-456");
  });

  // ------------------------------------------------------------------
  // healthCheck
  // ------------------------------------------------------------------

  it("should return healthy status", async () => {
    const result = await backend.healthCheck();
    expect(result.healthy).toBe(true);
    expect(result.server_address).toBe("localhost:7687");
    expect(result.database).toBe("neo4j");
  });

  it("should return unhealthy on error", async () => {
    mockDriver.getServerInfo.mockRejectedValueOnce(new Error("Connection refused"));
    const result = await backend.healthCheck();
    expect(result.healthy).toBe(false);
    expect(result.error).toContain("Connection refused");
  });

  // ------------------------------------------------------------------
  // fromEnv
  // ------------------------------------------------------------------

  it("should create from environment variables", async () => {
    const originalUri = process.env.GOVERNOR_NEO4J_URI;
    const originalUser = process.env.GOVERNOR_NEO4J_USER;
    const originalPassword = process.env.GOVERNOR_NEO4J_PASSWORD;

    try {
      process.env.GOVERNOR_NEO4J_URI = "neo4j://env-host:7687";
      process.env.GOVERNOR_NEO4J_USER = "env-user";
      process.env.GOVERNOR_NEO4J_PASSWORD = "env-pass";

      const envBackend = await Neo4jBackend.fromEnv();
      expect(envBackend).toBeInstanceOf(Neo4jBackend);
      await envBackend.close();
    } finally {
      // Restore
      if (originalUri) process.env.GOVERNOR_NEO4J_URI = originalUri;
      else delete process.env.GOVERNOR_NEO4J_URI;
      if (originalUser) process.env.GOVERNOR_NEO4J_USER = originalUser;
      else delete process.env.GOVERNOR_NEO4J_USER;
      if (originalPassword) process.env.GOVERNOR_NEO4J_PASSWORD = originalPassword;
      else delete process.env.GOVERNOR_NEO4J_PASSWORD;
    }
  });

  it("should throw when env vars missing", async () => {
    const originalUri = process.env.GOVERNOR_NEO4J_URI;
    const originalUser = process.env.GOVERNOR_NEO4J_USER;
    const originalPassword = process.env.GOVERNOR_NEO4J_PASSWORD;

    try {
      delete process.env.GOVERNOR_NEO4J_URI;
      delete process.env.GOVERNOR_NEO4J_USER;
      delete process.env.GOVERNOR_NEO4J_PASSWORD;

      await expect(Neo4jBackend.fromEnv()).rejects.toThrow(
        "Missing required Neo4j configuration",
      );
    } finally {
      if (originalUri) process.env.GOVERNOR_NEO4J_URI = originalUri;
      if (originalUser) process.env.GOVERNOR_NEO4J_USER = originalUser;
      if (originalPassword) process.env.GOVERNOR_NEO4J_PASSWORD = originalPassword;
    }
  });

  // ------------------------------------------------------------------
  // retry logic
  // ------------------------------------------------------------------

  it("should retry on transient errors", async () => {
    let callCount = 0;
    mockSession.executeRead.mockImplementation(async (fn: (tx: MockTx) => Promise<unknown>) => {
      callCount++;
      if (callCount === 1) {
        const err = new Error("transient failure");
        (err as { code?: string }).code = "Neo.TransientError.Transaction.DeadlockDetected";
        throw err;
      }
      const tx: MockTx = {
        run: vi.fn().mockResolvedValue(makeRecords([{ cnt: 1 }])),
      };
      return fn(tx);
    });

    expect(await backend.taskExists("T1")).toBe(true);
    expect(callCount).toBe(2);
  });

  it("should not retry on client errors", async () => {
    mockSession.executeRead.mockImplementation(async () => {
      const err = new Error("client error");
      (err as { code?: string }).code = "Neo.ClientError.Statement.SyntaxError";
      throw err;
    });

    await expect(backend.taskExists("T1")).rejects.toThrow("client error");
  });

  // ------------------------------------------------------------------
  // ensureSchema
  // ------------------------------------------------------------------

  it("should apply schema statements", async () => {
    const queries: string[] = [];
    mockSession.executeWrite.mockImplementation(async (fn: (tx: MockTx) => Promise<unknown>) => {
      const tx: MockTx = {
        run: vi.fn().mockImplementation((q: string) => {
          queries.push(q);
          return makeRecords([]);
        }),
      };
      return fn(tx);
    });

    const result = await backend.ensureSchema([
      "CREATE CONSTRAINT task_id IF NOT EXISTS FOR (t:Task) REQUIRE t.task_id IS UNIQUE",
      "CREATE INDEX task_status IF NOT EXISTS FOR (t:Task) ON (t.status)",
    ]);

    expect(result.success).toBe(true);
    expect(result.statements_applied).toBe(2);
    expect(queries).toHaveLength(2);
  });

  it("should report partial schema failures", async () => {
    let callIdx = 0;
    mockSession.executeWrite.mockImplementation(async (fn: (tx: MockTx) => Promise<unknown>) => {
      callIdx++;
      if (callIdx === 2) throw new Error("syntax error");
      const tx: MockTx = {
        run: vi.fn().mockResolvedValue(makeRecords([])),
      };
      return fn(tx);
    });

    const result = await backend.ensureSchema([
      "CREATE CONSTRAINT c1 IF NOT EXISTS FOR (t:Task) REQUIRE t.task_id IS UNIQUE",
      "INVALID CYPHER",
      "CREATE INDEX i1 IF NOT EXISTS FOR (t:Task) ON (t.status)",
    ]);

    expect(result.success).toBe(false);
    expect(result.statements_applied).toBe(2);
    expect((result.errors as unknown[]).length).toBe(1);
  });
});
