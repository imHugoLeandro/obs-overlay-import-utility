/**
 * Export store — manages opaque IDs for export workflow.
 *
 * Electron main owns:
 * - Export collection IDs: maps opaque IDs to canonical collection paths.
 * - Destination IDs: maps opaque IDs to canonical destination paths.
 *
 * The renderer never receives canonical paths — only opaque IDs and
 * safe display labels.
 */

import { randomUUID } from "crypto";
import { realpathSync, statSync } from "fs";

/** Injectable clock interface for deterministic TTL testing. */
export interface Clock {
  now(): number;
}

const defaultClock: Clock = { now: () => Date.now() };
const EXPORT_TTL_MS = 30 * 60 * 1000; // 30 minutes

export const EXPIRED_EXPORT_ERROR =
  "This export session has expired. Refresh the collection list.";

/** An export collection record. */
export interface ExportCollectionRecord {
  collectionId: string;
  /** Canonical absolute collection path — never sent to renderer. */
  collectionPath: string;
  /** Safe display label. */
  label: string;
  createdAt: number;
}

/** A destination record. */
export interface DestinationRecord {
  destinationId: string;
  /** Canonical absolute destination path — never sent to renderer. */
  destinationPath: string;
  /** Safe display label (folder basename). */
  destinationLabel: string;
  createdAt: number;
}

/** Error for unknown/expired IDs. */
export class ExportError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ExportError";
  }
}

/**
 * In-memory, session-only store for export workflow opaque IDs.
 */
export class ExportStore {
  private _collections: Map<string, ExportCollectionRecord> = new Map();
  private _destinations: Map<string, DestinationRecord> = new Map();
  private _obsScenesDirectory: string = "";
  private _clock: Clock;

  constructor(clock: Clock = defaultClock) {
    this._clock = clock;
  }

  /** Set the OBS scenes directory (configured once). */
  setObsScenesDirectory(dir: string): void {
    this._obsScenesDirectory = dir;
  }

  /** Get the OBS scenes directory. */
  getObsScenesDirectory(): string {
    return this._obsScenesDirectory;
  }

  /**
   * Store scanned export collections and return opaque IDs.
   * Called by Electron main after scanning via the Python backend.
   */
  setCollections(
    collections: { path: string; label: string }[]
  ): { collectionId: string; label: string }[] {
    this._prune();
    const result: { collectionId: string; label: string }[] = [];
    for (const c of collections) {
      const collectionId = randomUUID();
      this._collections.set(collectionId, {
        collectionId,
        collectionPath: c.path,
        label: c.label,
        createdAt: this._clock.now(),
      });
      result.push({ collectionId, label: c.label });
    }
    return result;
  }

  /**
   * Get all export collection records (returns opaque IDs + labels).
   */
  getCollections(): { collectionId: string; label: string }[] {
    this._prune();
    const result: { collectionId: string; label: string }[] = [];
    for (const record of this._collections.values()) {
      result.push({ collectionId: record.collectionId, label: record.label });
    }
    return result;
  }

  /**
   * Resolve an opaque collection ID to its canonical path.
   * Revalidates the file still exists.
   */
  getCollectionPath(collectionId: string): string {
    this._prune();
    const record = this._collections.get(collectionId);
    if (!record) {
      throw new ExportError(EXPIRED_EXPORT_ERROR);
    }
    try {
      const realPath = realpathSync(record.collectionPath);
      const stat = statSync(realPath);
      if (!stat.isFile()) {
        this._collections.delete(collectionId);
        throw new ExportError(
          "This collection is no longer available. Refresh the list."
        );
      }
      return realPath;
    } catch (err) {
      if (err instanceof ExportError) throw err;
      this._collections.delete(collectionId);
      throw new ExportError(EXPIRED_EXPORT_ERROR);
    }
  }

  /**
   * Create a destination record from a dialog result.
   * Returns an opaque destination ID and safe label.
   */
  createDestination(destinationPath: string): {
    destinationId: string;
    destinationLabel: string;
  } {
    this._prune();
    const destinationId = randomUUID();
    const destLabel = destinationPath.split(/[\\/]/).pop() || destinationPath;
    this._destinations.set(destinationId, {
      destinationId,
      destinationPath,
      destinationLabel: destLabel,
      createdAt: this._clock.now(),
    });
    return { destinationId, destinationLabel: destLabel };
  }

  /**
   * Resolve an opaque destination ID to its canonical path.
   */
  getDestinationPath(destinationId: string): string {
    this._prune();
    const record = this._destinations.get(destinationId);
    if (!record) {
      throw new ExportError(EXPIRED_EXPORT_ERROR);
    }
    try {
      const realPath = realpathSync(record.destinationPath);
      const stat = statSync(realPath);
      if (!stat.isDirectory()) {
        this._destinations.delete(destinationId);
        throw new ExportError("Destination folder is no longer available.");
      }
      return realPath;
    } catch (err) {
      if (err instanceof ExportError) throw err;
      this._destinations.delete(destinationId);
      throw new ExportError(EXPIRED_EXPORT_ERROR);
    }
  }

  /** Clear all export data. */
  clear(): void {
    this._collections.clear();
    this._destinations.clear();
  }

  private _prune(): void {
    const now = this._clock.now();
    for (const [id, record] of this._collections) {
      if (now - record.createdAt > EXPORT_TTL_MS) {
        this._collections.delete(id);
      }
    }
    for (const [id, record] of this._destinations) {
      if (now - record.createdAt > EXPORT_TTL_MS) {
        this._destinations.delete(id);
      }
    }
  }
}