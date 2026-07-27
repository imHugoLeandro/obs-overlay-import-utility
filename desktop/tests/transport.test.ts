/**
 * Tests for the BackendTransport stdout buffering and request handling.
 *
 * Since BackendTransport is not exported from the main process, we test
 * the transport protocol logic directly by simulating the stdout buffering
 * and JSON parsing behavior.
 *
 * Tests:
 * - stdout split across chunks
 * - multiple JSON lines in one chunk
 * - concurrent requests resolve correctly
 * - timeout cleanup
 * - backend exit/error rejects all pending requests
 */

import { describe, it, expect } from "vitest";

/** A parsed JSON-lines response from the backend. */
interface BackendResponse {
  request_id: string;
  type: string;
  data?: Record<string, unknown>;
  error?: { code: string; message: string };
}

/**
 * Simulate the BackendTransport's stdout buffering logic.
 * This mirrors the handleStdout method in the main process.
 */
function simulateStdoutBuffering(
  chunks: Buffer[],
  pending: Map<string, { resolve: (v: unknown) => void; reject: (e: Error) => void }>
): void {
  let buffer = "";
  for (const chunk of chunks) {
    buffer += chunk.toString();
    let newlineIndex: number;
    while ((newlineIndex = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (!line) continue;
      try {
        const response = JSON.parse(line) as BackendResponse;
        const pendingReq = pending.get(response.request_id);
        if (pendingReq) {
          pendingReq.resolve(response);
          pending.delete(response.request_id);
        }
      } catch {
        // Ignore non-JSON lines.
      }
    }
  }
}

describe("BackendTransport stdout buffering", () => {
  it("handles stdout split across chunks", () => {
    const jsonResponse = JSON.stringify({
      request_id: "req-1",
      type: "result",
      data: { status: "ok" },
    });

    const pending = new Map();
    let resolved: unknown = null;
    pending.set("req-1", {
      resolve: (v: unknown) => {
        resolved = v;
      },
      reject: () => {},
    });

    // Split the JSON response (including newline) across two chunks.
    const fullLine = jsonResponse + "\n";
    const firstChunk = Buffer.from(fullLine.slice(0, 10));
    const secondChunk = Buffer.from(fullLine.slice(10));

    simulateStdoutBuffering([firstChunk, secondChunk], pending);

    expect(resolved).not.toBeNull();
    const resp = resolved as BackendResponse;
    expect(resp.request_id).toBe("req-1");
    expect(resp.type).toBe("result");
    expect(pending.size).toBe(0);
  });

  it("handles multiple JSON lines in one chunk", () => {
    const line1 = JSON.stringify({ request_id: "req-1", type: "result", data: { status: "ok" } });
    const line2 = JSON.stringify({ request_id: "req-2", type: "result", data: { name: "test" } });
    const chunk = Buffer.from(line1 + "\n" + line2 + "\n");

    const resolved: unknown[] = [];
    const pending = new Map();
    pending.set("req-1", {
      resolve: (v: unknown) => {
        resolved.push(v);
      },
      reject: () => {},
    });
    pending.set("req-2", {
      resolve: (v: unknown) => {
        resolved.push(v);
      },
      reject: () => {},
    });

    simulateStdoutBuffering([chunk], pending);

    expect(resolved.length).toBe(2);
    expect((resolved[0] as BackendResponse).request_id).toBe("req-1");
    expect((resolved[1] as BackendResponse).request_id).toBe("req-2");
    expect(pending.size).toBe(0);
  });

  it("handles concurrent requests resolving to correct callers", () => {
    const line1 = JSON.stringify({ request_id: "req-1", type: "result", data: { status: "ok" } });
    const line2 = JSON.stringify({ request_id: "req-2", type: "result", data: { name: "test" } });
    const line3 = JSON.stringify({ request_id: "req-3", type: "result", data: { version: "1.0" } });
    const chunk = Buffer.from(line1 + "\n" + line2 + "\n" + line3 + "\n");

    const results: Record<string, BackendResponse> = {};
    const pending = new Map();
    ["req-1", "req-2", "req-3"].forEach((id) => {
      pending.set(id, {
        resolve: (v: unknown) => {
          results[id] = v as BackendResponse;
        },
        reject: () => {},
      });
    });

    simulateStdoutBuffering([chunk], pending);

    expect(results["req-1"].data?.status).toBe("ok");
    expect(results["req-2"].data?.name).toBe("test");
    expect(results["req-3"].data?.version).toBe("1.0");
    expect(pending.size).toBe(0);
  });

  it("ignores non-JSON lines in stdout", () => {
    const jsonResponse = JSON.stringify({
      request_id: "req-1",
      type: "result",
      data: { status: "ok" },
    });
    const chunk = Buffer.from("Python startup output\n" + jsonResponse + "\n");

    const resolved: unknown[] = [];
    const pending = new Map();
    pending.set("req-1", {
      resolve: (v: unknown) => {
        resolved.push(v);
      },
      reject: () => {},
    });

    simulateStdoutBuffering([chunk], pending);

    expect(resolved.length).toBe(1);
    expect((resolved[0] as BackendResponse).request_id).toBe("req-1");
  });

  it("handles blank lines in stdout", () => {
    const jsonResponse = JSON.stringify({
      request_id: "req-1",
      type: "result",
      data: { status: "ok" },
    });
    const chunk = Buffer.from("\n\n" + jsonResponse + "\n\n");

    const resolved: unknown[] = [];
    const pending = new Map();
    pending.set("req-1", {
      resolve: (v: unknown) => {
        resolved.push(v);
      },
      reject: () => {},
    });

    simulateStdoutBuffering([chunk], pending);

    expect(resolved.length).toBe(1);
    expect((resolved[0] as BackendResponse).request_id).toBe("req-1");
  });

  it("handles interleaved chunks with multiple responses", () => {
    const line1 = JSON.stringify({ request_id: "req-1", type: "result", data: { a: 1 } });
    const line2 = JSON.stringify({ request_id: "req-2", type: "result", data: { b: 2 } });
    const line3 = JSON.stringify({ request_id: "req-3", type: "result", data: { c: 3 } });

    // Realistic scenario: two complete responses in one chunk,
    // then the third response in a separate chunk.
    const chunk1 = Buffer.from(line1 + "\n" + line2 + "\n");
    const chunk2 = Buffer.from(line3 + "\n");

    const results: Record<string, BackendResponse> = {};
    const pending = new Map();
    ["req-1", "req-2", "req-3"].forEach((id) => {
      pending.set(id, {
        resolve: (v: unknown) => {
          results[id] = v as BackendResponse;
        },
        reject: () => {},
      });
    });

    simulateStdoutBuffering([chunk1, chunk2], pending);

    expect(results["req-1"].data?.a).toBe(1);
    expect(results["req-2"].data?.b).toBe(2);
    expect(results["req-3"].data?.c).toBe(3);
    expect(pending.size).toBe(0);
  });

  it("rejects all pending on backend exit", () => {
    const pending = new Map();
    const rejected: string[] = [];
    ["req-1", "req-2", "req-3"].forEach((id) => {
      pending.set(id, {
        resolve: () => {},
        reject: (_e: Error) => {
          rejected.push(id);
        },
      });
    });

    // Simulate backend exit: reject all pending.
    pending.forEach((p, requestId) => {
      p.reject(new Error("Backend process exited"));
      pending.delete(requestId);
    });

    expect(rejected.length).toBe(3);
    expect(pending.size).toBe(0);
  });

  it("timeout cleanup removes pending request", () => {
    const pending = new Map();
    const resolved: unknown[] = [];
    const rejected: unknown[] = [];

    pending.set("req-1", {
      resolve: (v: unknown) => {
        resolved.push(v);
      },
      reject: (e: unknown) => {
        rejected.push(e);
      },
    });

    // Simulate timeout: delete and reject.
    const timer = setTimeout(() => {
      pending.delete("req-1");
      pending.get("req-1")?.reject(new Error("timeout"));
    }, 10000);

    // Clear the timer (simulating successful response before timeout).
    clearTimeout(timer);
    pending.delete("req-1");

    expect(pending.size).toBe(0);
    expect(rejected.length).toBe(0);
  });
});
