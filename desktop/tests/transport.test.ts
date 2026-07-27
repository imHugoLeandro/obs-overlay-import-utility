/**
 * Tests for the BackendTransport class.
 *
 * These tests import and exercise the same production implementation used
 * by the Electron main process.  No protocol logic is reimplemented here.
 *
 * Tests:
 * - one response split across stdout chunks
 * - multiple lines in one chunk
 * - concurrent requests resolve to their correct caller
 * - malformed/unrelated output does not corrupt pending requests
 * - backend exit/error rejects every pending request
 * - timeout rejects and removes the request
 * - successful response clears the request timeout
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { BackendTransport } from "../src/main/transport";

/**
 * Helper: create a BackendResponse JSON line for a given request ID.
 */
function makeResponseLine(
  requestId: string,
  type: string,
  data?: Record<string, unknown>,
  error?: { code: string; message: string }
): string {
  const obj: { request_id: string; type: string; data?: Record<string, unknown>; error?: { code: string; message: string } } = {
    request_id: requestId,
    type,
  };
  if (data) obj.data = data;
  if (error) obj.error = error;
  return JSON.stringify(obj);
}

/**
 * Helper: create a BackendTransport with a mocked stdin so we can
 * feed stdout data without spawning a real subprocess.
 */
function makeTransport(): BackendTransport {
  const transport = new BackendTransport();
  // Inject a mock stdin so sendRequest can write to it.
  // We use a minimal mock that accepts writes and calls the callback.
  const mockStdin = {
    write: vi.fn((_data: unknown, cb?: (err: Error | null) => void) => {
      if (cb) cb(null);
      return true;
    }),
  };
  // Set the private pyStdin via type assertion.
  (transport as unknown as { pyStdin: unknown }).pyStdin = mockStdin;
  return transport;
}

describe("BackendTransport", () => {
  let transport: BackendTransport;

  beforeEach(() => {
    vi.useFakeTimers();
    transport = makeTransport();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("stdout buffering", () => {
    it("handles one response split across stdout chunks", async () => {
      const promise = transport.sendRequest("health");
      const requestId = getRequestId(transport);

      // Split the JSON response (including newline) across two chunks.
      const fullLine = makeResponseLine(requestId, "result", { status: "ok" }) + "\n";
      const firstChunk = Buffer.from(fullLine.slice(0, 10));
      const secondChunk = Buffer.from(fullLine.slice(10));

      transport.handleStdout(firstChunk);
      // Promise should not resolve yet — the line is incomplete.
      await Promise.resolve();
      expect(transport.getPendingCount()).toBe(1);

      transport.handleStdout(secondChunk);

      const result = await promise;
      const resp = result as { request_id: string; type: string; data?: Record<string, unknown> };
      expect(resp.request_id).toBe(requestId);
      expect(resp.type).toBe("result");
      expect(resp.data?.status).toBe("ok");
      expect(transport.getPendingCount()).toBe(0);
    });

    it("handles multiple JSON lines in one chunk", async () => {
      const promise1 = transport.sendRequest("health");
      const promise2 = transport.sendRequest("app_info");
      const requestId1 = getRequestId(transport, 0);
      const requestId2 = getRequestId(transport, 1);

      const chunk = Buffer.from(
        makeResponseLine(requestId1, "result", { status: "ok" }) + "\n" +
          makeResponseLine(requestId2, "result", { name: "test" }) + "\n"
      );

      transport.handleStdout(chunk);

      const [result1, result2] = await Promise.all([promise1, promise2]);
      const resp1 = result1 as { data?: Record<string, unknown> };
      const resp2 = result2 as { data?: Record<string, unknown> };
      expect(resp1.data?.status).toBe("ok");
      expect(resp2.data?.name).toBe("test");
      expect(transport.getPendingCount()).toBe(0);
    });

    it("concurrent requests resolve to their correct caller", async () => {
      const promise1 = transport.sendRequest("health");
      const promise2 = transport.sendRequest("app_info");
      const promise3 = transport.sendRequest("health");
      const requestId1 = getRequestId(transport, 0);
      const requestId2 = getRequestId(transport, 1);
      const requestId3 = getRequestId(transport, 2);

      const chunk = Buffer.from(
        makeResponseLine(requestId1, "result", { a: 1 }) + "\n" +
          makeResponseLine(requestId2, "result", { b: 2 }) + "\n" +
          makeResponseLine(requestId3, "result", { c: 3 }) + "\n"
      );

      transport.handleStdout(chunk);

      const [result1, result2, result3] = await Promise.all([promise1, promise2, promise3]);
      const resp1 = result1 as { data?: Record<string, unknown> };
      const resp2 = result2 as { data?: Record<string, unknown> };
      const resp3 = result3 as { data?: Record<string, unknown> };
      expect(resp1.data?.a).toBe(1);
      expect(resp2.data?.b).toBe(2);
      expect(resp3.data?.c).toBe(3);
      expect(transport.getPendingCount()).toBe(0);
    });

    it("malformed/unrelated output does not corrupt pending requests", async () => {
      const promise = transport.sendRequest("health");
      const requestId = getRequestId(transport);

      // Send non-JSON output, then a valid response.
      const chunk = Buffer.from(
        "Python startup warning\n" +
          "{invalid json\n" +
          makeResponseLine(requestId, "result", { status: "ok" }) + "\n"
      );

      transport.handleStdout(chunk);

      const result = await promise;
      const resp = result as { data?: Record<string, unknown> };
      expect(resp.data?.status).toBe("ok");
      expect(transport.getPendingCount()).toBe(0);
    });

    it("ignores responses for unknown request IDs", async () => {
      const promise = transport.sendRequest("health");
      const requestId = getRequestId(transport);

      // A response for a request ID we never sent.
      const chunk = Buffer.from(
        makeResponseLine("req-unknown", "result", { data: "should be ignored" }) + "\n" +
          makeResponseLine(requestId, "result", { status: "ok" }) + "\n"
      );

      transport.handleStdout(chunk);

      const result = await promise;
      const resp = result as { data?: Record<string, unknown> };
      expect(resp.data?.status).toBe("ok");
      expect(transport.getPendingCount()).toBe(0);
    });
  });

  describe("backend exit / error", () => {
    it("rejects every pending request on backend exit", async () => {
      const promise1 = transport.sendRequest("health");
      const promise2 = transport.sendRequest("app_info");
      const promise3 = transport.sendRequest("health");

      expect(transport.getPendingCount()).toBe(3);

      transport.rejectAllPending(new Error("Backend process exited"));

      expect(transport.getPendingCount()).toBe(0);
      await expect(promise1).rejects.toThrow("Backend process exited");
      await expect(promise2).rejects.toThrow("Backend process exited");
      await expect(promise3).rejects.toThrow("Backend process exited");
    });
  });

  describe("timeout", () => {
    it("rejects and removes the request on timeout", async () => {
      const promise = transport.sendRequest("health");

      expect(transport.getPendingCount()).toBe(1);

      // Advance past the 10-second timeout.
      vi.advanceTimersByTime(10000);

      expect(transport.getPendingCount()).toBe(0);
      await expect(promise).rejects.toThrow("Backend request timed out: health");
    });

    it("successful response clears the request timeout", async () => {
      const promise = transport.sendRequest("health");
      const requestId = getRequestId(transport);

      expect(transport.getPendingCount()).toBe(1);

      // Send the response before the timeout fires.
      const chunk = Buffer.from(makeResponseLine(requestId, "result", { status: "ok" }) + "\n");
      transport.handleStdout(chunk);

      const result = await promise;
      const resp = result as { data?: Record<string, unknown> };
      expect(resp.data?.status).toBe("ok");
      expect(transport.getPendingCount()).toBe(0);

      // Advancing past the timeout should NOT reject (the timer was cleared).
      vi.advanceTimersByTime(10000);
      // The promise already resolved; advancing timers should not cause issues.
    });
  });

  describe("sendRequest without stdin", () => {
    it("rejects when backend is not running", async () => {
      const transport = new BackendTransport();
      await expect(transport.sendRequest("health")).rejects.toThrow("Backend not running");
    });
  });
});

/**
 * Extract the request ID that BackendTransport.generateRequestId() produced
 * for the Nth sendRequest call (0-indexed).
 *
 * Since generateRequestId uses Date.now() and a counter, we can predict
 * the IDs by calling sendRequest and reading the mock stdin writes.
 */
function getRequestId(transport: BackendTransport, callIndex = 0): string {
  const mockStdin = (transport as unknown as { pyStdin: { write: ReturnType<typeof vi.fn> } }).pyStdin;
  const writeCall = mockStdin.write.mock.calls[callIndex];
  if (!writeCall) {
    throw new Error(`No write call at index ${callIndex}`);
  }
  const data = writeCall[0] as string;
  const parsed = JSON.parse(data.trim());
  return parsed.request_id;
}
