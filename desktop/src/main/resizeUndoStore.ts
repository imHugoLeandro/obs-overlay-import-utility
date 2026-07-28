/**
 * Session-only store for resize undo operations.
 *
 * Electron main is the sole owner of concrete backup paths.  When an
 * offline resize succeeds, the Python backend returns the concrete
 * `backup_path` to Electron main only.  Electron main stores that path
 * here under an opaque `undoId` and returns only the `undoId` to the
 * renderer.
 *
 * The renderer can never receive or submit a raw backup path.
 * Undo requests carry only the opaque `undoId` (and the `selectionId`
 * it was bound to), which Electron main resolves back to the concrete
 * path before forwarding it to the Python backend.
 *
 * Security:
 * - Undo IDs are cryptographically random (crypto.randomUUID).
 * - TTL of 15 minutes with injectable clock for deterministic tests.
 * - Each undoId is bound to the selectionId it was created under.
 * - Unknown, expired, or mismatched IDs are rejected.
 * - A backup can only be undone once (one-shot).
 * - In-flight state prevents concurrent/replay requests; on backend
 *   failure the token is released so the same valid token can be
 *   retried until its TTL expires.
 */

import { randomUUID } from "crypto";
import { statSync, existsSync } from "fs";

/** Injectable clock interface for deterministic TTL testing. */
export interface Clock {
  now(): number;
}

/** Default clock using Date.now(). */
const defaultClock: Clock = { now: () => Date.now() };

/** TTL for undo IDs: 15 minutes in milliseconds. */
const UNDO_TTL_MS = 15 * 60 * 1000;

/** Customer-safe error message for expired/unknown undo IDs. */
export const EXPIRED_UNDO_ERROR =
  "This undo operation is no longer available. Resize the collection again to create a new backup.";

/** Customer-safe error message for in-flight undo. */
export const IN_FLIGHT_UNDO_ERROR =
  "This undo operation is already in progress. Please wait for it to complete.";

/** A single undo record — owns the concrete backup path. */
interface UndoRecord {
  /** Opaque undo ID — safe to send to the renderer. */
  undoId: string;
  /** Opaque selection ID this undo was bound to. */
  selectionId: string;
  /** Canonical absolute backup path — never sent to the renderer. */
  backupPath: string;
  /** Canonical absolute collection path — never sent to the renderer. */
  collectionPath: string;
  /** Creation timestamp (ms since epoch). */
  createdAt: number;
  /** Whether this undo has already been consumed (one-shot). */
  consumed: boolean;
  /** Whether an undo is currently in-flight (being processed by the backend). */
  inFlight: boolean;
}

/**
 * Error thrown when an undo ID is unknown, expired, mismatched, already
 * consumed, or currently in-flight.  The message is customer-safe and
 * never contains raw paths.
 */
export class UndoError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UndoError";
  }
}

/**
 * In-memory, session-only store for resize undo operations.
 *
 * @param clock Optional injectable clock for deterministic TTL testing.
 */
export class ResizeUndoStore {
  private _store: Map<string, UndoRecord> = new Map();
  private _clock: Clock;

  constructor(clock: Clock = defaultClock) {
    this._clock = clock;
  }

  /**
   * Register a backup path and return an opaque undo ID.
   *
   * Called by Electron main after a successful offline resize.  The
   * concrete backup and collection paths stay in Electron main only.
   *
   * @param selectionId The opaque selection ID the resize was bound to.
   * @param collectionPath The canonical absolute collection path.
   * @param backupPath The canonical absolute backup path.
   * @returns The opaque undo ID to send to the renderer.
   */
  registerUndo(
    selectionId: string,
    collectionPath: string,
    backupPath: string
  ): string {
    const undoId = randomUUID();
    this._store.set(undoId, {
      undoId,
      selectionId,
      collectionPath,
      backupPath,
      createdAt: this._clock.now(),
      consumed: false,
      inFlight: false,
    });
    return undoId;
  }

  /**
   * Resolve an undo ID to its concrete backup and collection paths.
   *
   * Validates that:
   * - The undo ID exists and has not expired.
   * - The undo ID was bound to the given selectionId.
   * - The undo has not already been consumed (one-shot).
   * - The undo is not currently in-flight (concurrent/replay rejection).
   *
   * On success, marks the undo as **in-flight** so concurrent or replay
   * requests are rejected.  The token is NOT consumed yet — it must be
   * explicitly consumed via `consumeUndo()` after the backend restore
   * succeeds, or released via `releaseUndo()` on failure.
   *
   * @param undoId The opaque undo ID from the renderer.
   * @param selectionId The opaque selection ID to match against.
   * @returns { backupPath, collectionPath } — concrete paths for the
   *   Python backend.
   * @throws {UndoError} if the undo ID is unknown, expired, mismatched,
   *   already consumed, or currently in-flight.
   */
  resolveUndo(undoId: string, selectionId: string): {
    backupPath: string;
    collectionPath: string;
  } {
    const record = this._getValid(undoId, selectionId);

    // Mark as in-flight so concurrent/replay requests are rejected.
    // The token is NOT consumed yet — it must be explicitly consumed
    // after the backend restore succeeds, or released on failure.
    record.inFlight = true;

    // Revalidate the backup file still exists before returning the path.
    if (!existsSync(record.backupPath)) {
      record.inFlight = false;
      throw new UndoError(EXPIRED_UNDO_ERROR);
    }
    try {
      const stat = statSync(record.backupPath);
      if (!stat.isFile()) {
        record.inFlight = false;
        throw new UndoError(EXPIRED_UNDO_ERROR);
      }
    } catch {
      record.inFlight = false;
      throw new UndoError(EXPIRED_UNDO_ERROR);
    }

    return {
      backupPath: record.backupPath,
      collectionPath: record.collectionPath,
    };
  }

  /**
   * Permanently consume an undo token after a successful restore.
   *
   * Called by Electron main only after the Python backend's
   * `undo_resize` operation has succeeded.  This makes the undo
   * one-shot: the token can never be replayed.
   *
   * @param undoId The opaque undo ID.
   * @param selectionId The opaque selection ID to match against.
   * @throws {UndoError} if the undo ID is unknown, expired, mismatched,
   *   or not currently in-flight.
   */
  consumeUndo(undoId: string, selectionId: string): void {
    const record = this._getValidForTransition(undoId, selectionId);
    if (!record.inFlight) {
      throw new UndoError(IN_FLIGHT_UNDO_ERROR);
    }
    record.inFlight = false;
    record.consumed = true;
    this._store.delete(undoId);
  }

  /**
   * Release the in-flight state of an undo token after a failed restore.
   *
   * Called by Electron main when the Python backend's `undo_resize`
   * operation fails or throws.  This clears the in-flight flag so the
   * same valid token can be retried until its TTL expires.
   *
   * @param undoId The opaque undo ID.
   * @param selectionId The opaque selection ID to match against.
   * @throws {UndoError} if the undo ID is unknown, expired, mismatched,
   *   or not currently in-flight.
   */
  releaseUndo(undoId: string, selectionId: string): void {
    const record = this._getValidForTransition(undoId, selectionId);
    if (!record.inFlight) {
      throw new UndoError(IN_FLIGHT_UNDO_ERROR);
    }
    record.inFlight = false;
  }

  /**
   * Remove an undo record (e.g., after successful undo or on cleanup).
   *
   * @param undoId The opaque undo ID.
   */
  remove(undoId: string): void {
    this._store.delete(undoId);
  }

  /**
   * Clear all undo records (used on app shutdown).
   */
  clear(): void {
    this._store.clear();
  }

  /**
   * Internal: get a valid (non-expired, non-consumed, non-in-flight,
   * matching) undo record.
   *
   * @param undoId The opaque undo ID.
   * @param selectionId The opaque selection ID to match against.
   * @returns The UndoRecord.
   * @throws {UndoError} if the undo ID is unknown, expired, mismatched,
   *   already consumed, or currently in-flight.
   */
  private _getValid(undoId: string, selectionId: string): UndoRecord {
    const record = this._store.get(undoId);
    if (!record) {
      throw new UndoError(EXPIRED_UNDO_ERROR);
    }

    // Check TTL.
    const age = this._clock.now() - record.createdAt;
    if (age > UNDO_TTL_MS) {
      this._store.delete(undoId);
      throw new UndoError(EXPIRED_UNDO_ERROR);
    }

    // Check one-shot consumption.
    if (record.consumed) {
      throw new UndoError(EXPIRED_UNDO_ERROR);
    }

    // Check in-flight state (concurrent/replay rejection).
    if (record.inFlight) {
      throw new UndoError(IN_FLIGHT_UNDO_ERROR);
    }

    // Check selection binding.
    if (record.selectionId !== selectionId) {
      throw new UndoError(
        "This undo operation does not match the current selection."
      );
    }

    return record;
  }

  /**
   * Internal: get a valid record for consume/release transitions.
   *
   * Same as `_getValid` but does NOT reject in-flight tokens — these
   * transitions are precisely the operations that act on in-flight
   * tokens.  The caller checks the in-flight state itself.
   *
   * @param undoId The opaque undo ID.
   * @param selectionId The opaque selection ID to match against.
   * @returns The UndoRecord.
   * @throws {UndoError} if the undo ID is unknown, expired, mismatched,
   *   or already consumed.
   */
  private _getValidForTransition(
    undoId: string,
    selectionId: string
  ): UndoRecord {
    const record = this._store.get(undoId);
    if (!record) {
      throw new UndoError(EXPIRED_UNDO_ERROR);
    }

    // Check TTL.
    const age = this._clock.now() - record.createdAt;
    if (age > UNDO_TTL_MS) {
      this._store.delete(undoId);
      throw new UndoError(EXPIRED_UNDO_ERROR);
    }

    // Check one-shot consumption.
    if (record.consumed) {
      throw new UndoError(EXPIRED_UNDO_ERROR);
    }

    // Check selection binding.
    if (record.selectionId !== selectionId) {
      throw new UndoError(
        "This undo operation does not match the current selection."
      );
    }

    return record;
  }
}
