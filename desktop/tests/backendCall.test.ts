/**
 * Tests for the backendCall module — expected error preservation vs
 * generic unavailability.
 *
 * Tests:
 * - Expected backend error (structured { code, message }) reaches React
 *   as its useful safe message.
 * - Transport failure becomes the generic unavailable message.
 * - Neither case leaks an absolute path.
 * - ExpectedBackendError carries the code.
 */

import { describe, it, expect, vi } from "vitest";
import { callBackend, BACKEND_UNAVAILABLE_ERROR, ExpectedBackendError } from "../src/main/backendCall";
import type { BackendTransport } from "../src/main/transport";

/**
 * Helper: create a mock BackendTransport whose sendRequest resolves
 * with the given response.
 */
function makeTransport(response: unknown): BackendTransport {
  return {
    sendRequest: vi.fn().mockResolvedValue(response),
    generateRequestId: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    handleStdout: vi.fn(),
    rejectAllPending: vi.fn(),
    isRunning: vi.fn().mockReturnValue(true),
    getPendingCount: vi.fn().mockReturnValue(0),
  } as unknown as BackendTransport;
}

/**
 * Helper: create a mock BackendTransport whose sendRequest rejects
 * with the given error (simulating transport failure).
 */
function makeFailingTransport(error: Error): BackendTransport {
  return {
    sendRequest: vi.fn().mockRejectedValue(error),
    generateRequestId: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    handleStdout: vi.fn(),
    rejectAllPending: vi.fn(),
    isRunning: vi.fn().mockReturnValue(true),
    getPendingCount: vi.fn().mockReturnValue(0),
  } as unknown as BackendTransport;
}

/** Type-cast helper for caught errors. */
function asError(err: unknown): Error {
  return err as Error;
}

describe("callBackend — expected backend errors", () => {
  it("preserves an expected scan_failed error message", async () => {
    const transport = makeTransport({
      request_id: "r1",
      type: "error",
      error: { code: "scan_failed", message: "Choose a valid overlay folder first." },
    });

    await expect(callBackend(transport, "scan_collections", { folder_path: "/tmp" }))
      .rejects.toThrow("Choose a valid overlay folder first.");

    const err = asError(await callBackend(transport, "scan_collections", { folder_path: "/tmp" }).catch(e => e));
    expect(err).toBeInstanceOf(ExpectedBackendError);
    expect((err as ExpectedBackendError).code).toBe("scan_failed");
    expect(err.message).toBe("Choose a valid overlay folder first.");
  });

  it("preserves an expected invalid-collection error message", async () => {
    const transport = makeTransport({
      request_id: "r2",
      type: "error",
      error: { code: "invalid_collection", message: "The selected collection is no longer available. Scan the folder again." },
    });

    const err = asError(await callBackend(transport, "convert_collection", {
      folder_path: "/tmp",
      collection_path: "/tmp/collection.json",
      strict: true,
      case_sensitive: true,
    }).catch(e => e));

    expect(err).toBeInstanceOf(ExpectedBackendError);
    expect((err as ExpectedBackendError).code).toBe("invalid_collection");
    expect(err.message).toBe("The selected collection is no longer available. Scan the folder again.");
  });

  it("does not leak an absolute path in expected error messages", async () => {
    const transport = makeTransport({
      request_id: "r3",
      type: "error",
      error: { code: "invalid_folder", message: "Choose a valid overlay folder first." },
    });

    const err = asError(await callBackend(transport, "scan_collections", { folder_path: "/secret/path" }).catch(e => e));
    expect(err.message).not.toContain("/secret/path");
    expect(err.message).not.toContain("/tmp");
  });
});

describe("callBackend — transport failures", () => {
  it("converts a transport failure to the generic unavailable message", async () => {
    const transport = makeFailingTransport(new Error("Backend process exited"));

    const err = asError(await callBackend(transport, "health").catch(e => e));
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe(BACKEND_UNAVAILABLE_ERROR);
    expect(err.message).not.toContain("Backend process exited");
  });

  it("converts a timeout to the generic unavailable message", async () => {
    const transport = makeFailingTransport(new Error("Backend request timed out: health"));

    const err = asError(await callBackend(transport, "health").catch(e => e));
    expect(err.message).toBe(BACKEND_UNAVAILABLE_ERROR);
    expect(err.message).not.toContain("timed out");
  });

  it("converts a malformed backend response to the generic unavailable message", async () => {
    const transport = makeTransport({ request_id: "r4", type: "unknown_type" });

    const err = asError(await callBackend(transport, "health").catch(e => e));
    expect(err.message).toBe(BACKEND_UNAVAILABLE_ERROR);
  });

  it("converts a null response to the generic unavailable message", async () => {
    const transport = makeTransport(null);

    const err = asError(await callBackend(transport, "health").catch(e => e));
    expect(err.message).toBe(BACKEND_UNAVAILABLE_ERROR);
  });

  it("converts an error response without a message to the generic unavailable message", async () => {
    const transport = makeTransport({
      request_id: "r5",
      type: "error",
      error: { code: "something" },
    });

    const err = asError(await callBackend(transport, "health").catch(e => e));
    expect(err.message).toBe(BACKEND_UNAVAILABLE_ERROR);
  });

  it("does not leak an absolute path in the generic unavailable message", async () => {
    const transport = makeFailingTransport(new Error("Backend process exited"));

    const err = asError(await callBackend(transport, "scan_collections", { folder_path: "/secret/path" }).catch(e => e));
    expect(err.message).not.toContain("/secret/path");
    expect(err.message).toBe(BACKEND_UNAVAILABLE_ERROR);
  });
});

describe("callBackend — success", () => {
  it("returns result data on success", async () => {
    const transport = makeTransport({
      request_id: "r6",
      type: "result",
      data: { status: "ok", pid: 1234 },
    });

    const result = await callBackend(transport, "health");
    expect(result).toEqual({ status: "ok", pid: 1234 });
  });
});
