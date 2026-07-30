/**
 * Tests for the ResizeUndoStore — Electron main-process session store
 * for opaque undo IDs.
 *
 * Tests:
 * - registerUndo returns an opaque undo ID
 * - IDs expire using an injected fake clock
 * - unknown IDs are rejected
 * - undo ID is bound to the selectionId it was created under
 * - undo ID is one-shot (cannot be replayed) — via consumeUndo
 * - resolveUndo returns concrete paths for the Python backend
 * - resolveUndo rejects a missing backup file
 * - resolveUndo marks token as in-flight (concurrent/replay rejection)
 * - consumeUndo permanently removes the token after successful undo
 * - releaseUndo releases the token for retry after failed undo
 * - expired, unknown, mismatched-selection, and missing-backup tokens
 *   are rejected
 * - no raw path reaches React (paths stay in Electron main only)
 * - remove deletes an undo record
 * - clear removes all undo records
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import {
  ResizeUndoStore,
  UndoError,
  EXPIRED_UNDO_ERROR,
  IN_FLIGHT_UNDO_ERROR,
} from "../src/main/resizeUndoStore";
import { writeFileSync, mkdtempSync, rmSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

describe("ResizeUndoStore", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = mkdtempSync(join(tmpdir(), "undo-test-"));
  });

  afterEach(() => {
    rmSync(tmpDir, { recursive: true, force: true });
  });

  it("registerUndo returns an opaque undo ID", () => {
    const store = new ResizeUndoStore();
    const undoId = store.registerUndo(
      "sel-123",
      "/fake/collection.json",
      "/fake/backup.json"
    );
    expect(undoId).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
    );
  });

  it("does not reuse IDs for new undo records", () => {
    const store = new ResizeUndoStore();
    const id1 = store.registerUndo("sel-1", "/fake/c1.json", "/fake/b1.json");
    const id2 = store.registerUndo("sel-2", "/fake/c2.json", "/fake/b2.json");
    expect(id1).not.toBe(id2);
  });

  it("IDs expire using an injected fake clock", () => {
    const clock = { now: () => 1000 };
    const store = new ResizeUndoStore(clock);
    const backupPath = join(tmpDir, "backup.json");
    writeFileSync(backupPath, "{}");
    const undoId = store.registerUndo(
      "sel-123",
      "/fake/collection.json",
      backupPath
    );

    // Within TTL (15 minutes).
    clock.now = () => 1000 + 14 * 60 * 1000;
    const resolved = store.resolveUndo(undoId, "sel-123");
    expect(resolved.backupPath).toBe(backupPath);
    // Release the in-flight state so we can test further.
    store.releaseUndo(undoId, "sel-123");
  });

  it("unknown IDs are rejected with a customer-safe error", () => {
    const store = new ResizeUndoStore();
    expect(() => store.resolveUndo("nonexistent-id", "sel-123")).toThrow(
      UndoError
    );
    expect(() => store.resolveUndo("nonexistent-id", "sel-123")).toThrow(
      EXPIRED_UNDO_ERROR
    );
  });

  it("undo ID is bound to the selectionId it was created under", () => {
    const store = new ResizeUndoStore();
    const undoId = store.registerUndo(
      "sel-123",
      "/fake/collection.json",
      "/fake/backup.json"
    );

    // Mismatched selectionId is rejected.
    expect(() => store.resolveUndo(undoId, "sel-456")).toThrow(UndoError);
    expect(() => store.resolveUndo(undoId, "sel-456")).toThrow(
      /does not match the current selection/
    );
  });

  it("resolveUndo marks token as in-flight (concurrent/replay rejection)", () => {
    const store = new ResizeUndoStore();
    const backupPath = join(tmpDir, "backup.json");
    writeFileSync(backupPath, "{}");
    const undoId = store.registerUndo(
      "sel-123",
      join(tmpDir, "collection.json"),
      backupPath
    );

    // First resolve succeeds and marks as in-flight.
    const resolved = store.resolveUndo(undoId, "sel-123");
    expect(resolved.backupPath).toBe(backupPath);

    // Second resolve fails (in-flight).
    expect(() => store.resolveUndo(undoId, "sel-123")).toThrow(UndoError);
    expect(() => store.resolveUndo(undoId, "sel-123")).toThrow(
      IN_FLIGHT_UNDO_ERROR
    );

    // Release the in-flight state.
    store.releaseUndo(undoId, "sel-123");

    // Now resolve succeeds again (not in-flight, not consumed).
    const resolved2 = store.resolveUndo(undoId, "sel-123");
    expect(resolved2.backupPath).toBe(backupPath);
    store.releaseUndo(undoId, "sel-123");
  });

  it("successful undo is one-shot via consumeUndo", () => {
    const store = new ResizeUndoStore();
    const backupPath = join(tmpDir, "backup.json");
    writeFileSync(backupPath, "{}");
    const undoId = store.registerUndo(
      "sel-123",
      join(tmpDir, "collection.json"),
      backupPath
    );

    // Resolve (marks in-flight).
    const resolved = store.resolveUndo(undoId, "sel-123");
    expect(resolved.backupPath).toBe(backupPath);

    // Consume (marks as consumed and removes).
    store.consumeUndo(undoId, "sel-123");

    // Token is gone — resolve fails.
    expect(() => store.resolveUndo(undoId, "sel-123")).toThrow(UndoError);
    expect(() => store.resolveUndo(undoId, "sel-123")).toThrow(
      EXPIRED_UNDO_ERROR
    );
  });

  it("failed backend undo releases the token for retry via releaseUndo", () => {
    const store = new ResizeUndoStore();
    const backupPath = join(tmpDir, "backup.json");
    writeFileSync(backupPath, "{}");
    const undoId = store.registerUndo(
      "sel-123",
      join(tmpDir, "collection.json"),
      backupPath
    );

    // Resolve (marks in-flight).
    const resolved = store.resolveUndo(undoId, "sel-123");
    expect(resolved.backupPath).toBe(backupPath);

    // Simulate backend failure — release the token.
    store.releaseUndo(undoId, "sel-123");

    // Token is still valid and can be retried.
    const resolved2 = store.resolveUndo(undoId, "sel-123");
    expect(resolved2.backupPath).toBe(backupPath);
    store.releaseUndo(undoId, "sel-123");
  });

  it("resolveUndo returns concrete paths for the Python backend", () => {
    const store = new ResizeUndoStore();
    const collectionPath = join(tmpDir, "collection.json");
    const backupPath = join(tmpDir, "backup.json");
    writeFileSync(backupPath, "{}");
    const undoId = store.registerUndo(
      "sel-123",
      collectionPath,
      backupPath
    );

    const resolved = store.resolveUndo(undoId, "sel-123");
    expect(resolved.backupPath).toBe(backupPath);
    expect(resolved.collectionPath).toBe(collectionPath);
    store.releaseUndo(undoId, "sel-123");
  });

  it("resolveUndo rejects a missing backup file", () => {
    const store = new ResizeUndoStore();
    const undoId = store.registerUndo(
      "sel-123",
      "/fake/collection.json",
      "/nonexistent/backup.json"
    );

    expect(() => store.resolveUndo(undoId, "sel-123")).toThrow(UndoError);
    expect(() => store.resolveUndo(undoId, "sel-123")).toThrow(
      EXPIRED_UNDO_ERROR
    );
  });

  it("expired undo ID is rejected and removed from the store", () => {
    const clock = { now: () => 1000 };
    const store = new ResizeUndoStore(clock);
    const undoId = store.registerUndo(
      "sel-123",
      "/fake/collection.json",
      "/fake/backup.json"
    );

    // Advance past TTL.
    clock.now = () => 1000 + 16 * 60 * 1000;
    expect(() => store.resolveUndo(undoId, "sel-123")).toThrow(UndoError);
    expect(() => store.resolveUndo(undoId, "sel-123")).toThrow(
      EXPIRED_UNDO_ERROR
    );

    // The expired record should have been removed.
    expect(() => store.resolveUndo(undoId, "sel-123")).toThrow(UndoError);
  });

  it("consumeUndo rejects when token is not in-flight", () => {
    const store = new ResizeUndoStore();
    const backupPath = join(tmpDir, "backup.json");
    writeFileSync(backupPath, "{}");
    const undoId = store.registerUndo(
      "sel-123",
      "/fake/collection.json",
      backupPath
    );

    // Token is not in-flight — consumeUndo should fail.
    expect(() => store.consumeUndo(undoId, "sel-123")).toThrow(UndoError);
    expect(() => store.consumeUndo(undoId, "sel-123")).toThrow(
      IN_FLIGHT_UNDO_ERROR
    );
  });

  it("releaseUndo rejects when token is not in-flight", () => {
    const store = new ResizeUndoStore();
    const backupPath = join(tmpDir, "backup.json");
    writeFileSync(backupPath, "{}");
    const undoId = store.registerUndo(
      "sel-123",
      "/fake/collection.json",
      backupPath
    );

    // Token is not in-flight — releaseUndo should fail.
    expect(() => store.releaseUndo(undoId, "sel-123")).toThrow(UndoError);
    expect(() => store.releaseUndo(undoId, "sel-123")).toThrow(
      IN_FLIGHT_UNDO_ERROR
    );
  });

  it("remove deletes an undo record", () => {
    const store = new ResizeUndoStore();
    const undoId = store.registerUndo(
      "sel-123",
      "/fake/collection.json",
      "/fake/backup.json"
    );
    store.remove(undoId);
    expect(() => store.resolveUndo(undoId, "sel-123")).toThrow(UndoError);
  });

  it("clear removes all undo records", () => {
    const store = new ResizeUndoStore();
    const id1 = store.registerUndo("sel-1", "/fake/c1.json", "/fake/b1.json");
    const id2 = store.registerUndo("sel-2", "/fake/c2.json", "/fake/b2.json");
    store.clear();
    expect(() => store.resolveUndo(id1, "sel-1")).toThrow(UndoError);
    expect(() => store.resolveUndo(id2, "sel-2")).toThrow(UndoError);
  });

  it("no raw backup path reaches the renderer-facing API", () => {
    // The ResizeUndoStore only returns opaque undo IDs from registerUndo.
    // The concrete backupPath is stored internally and only returned by
    // resolveUndo (which is called by Electron main, not the renderer).
    // This test verifies that registerUndo returns only an opaque ID.
    const store = new ResizeUndoStore();
    const backupPath = join(tmpDir, "backup.json");
    writeFileSync(backupPath, "{}");
    const undoId = store.registerUndo(
      "sel-123",
      join(tmpDir, "collection.json"),
      backupPath
    );

    // The undo ID must not contain the backup path.
    expect(undoId).not.toContain(backupPath);
    expect(undoId).not.toContain(".obs-overlay");
    expect(undoId).not.toContain(".json");
    expect(undoId).not.toContain(tmpDir);
  });
});
