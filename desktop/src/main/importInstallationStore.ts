/**
 * Import installation store — manages opaque installation IDs for
 * successful Streamlabs and Automatic imports.
 *
 * After a successful import, Electron main creates an opaque
 * installation_id that the renderer can use to:
 * - request device requirements
 * - request device candidates
 * - apply device choices
 * - activate the collection in OBS
 *
 * The renderer never receives the canonical collection path,
 * OBS scenes directory, or collection name — only the opaque ID.
 */

import { randomUUID } from "crypto";
import { realpathSync, statSync } from "fs";

/** Injectable clock interface for deterministic TTL testing. */
export interface Clock {
  now(): number;
}

const defaultClock: Clock = { now: () => Date.now() };
const INSTALLATION_TTL_MS = 30 * 60 * 1000; // 30 minutes

export const EXPIRED_INSTALLATION_ERROR =
  "This installation session has expired. Import the collection again.";

/** An installation record — holds the canonical paths the renderer never sees. */
export interface InstallationRecord {
  installationId: string;
  /** Canonical absolute collection path. */
  collectionPath: string;
  /** Canonical absolute OBS scenes directory. */
  obsScenesDirectory: string;
  /** Safe display name of the collection. */
  collectionName: string;
  /** Timestamp of creation. */
  createdAt: number;
}

/** Error for unknown/expired installation IDs. */
export class InstallationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InstallationError";
  }
}

/**
 * In-memory, session-only store for import installation records.
 * The renderer never sees the canonical paths stored here.
 */
export class ImportInstallationStore {
  private _store: Map<string, InstallationRecord> = new Map();
  private _clock: Clock;

  constructor(clock: Clock = defaultClock) {
    this._clock = clock;
  }

  /**
   * Create an installation record after a successful import.
   * @returns The opaque installation ID.
   */
  createInstallation(
    collectionPath: string,
    obsScenesDirectory: string,
    collectionName: string
  ): string {
    const installationId = randomUUID();
    this._store.set(installationId, {
      installationId,
      collectionPath,
      obsScenesDirectory,
      collectionName,
      createdAt: this._clock.now(),
    });
    return installationId;
  }

  /**
   * Get the canonical collection path for an installation.
   * Used by Electron main to pass to the Python backend.
   */
  getCollectionPath(installationId: string): string {
    const record = this._getValid(installationId);
    // Revalidate: the collection must still exist and be a regular file.
    try {
      const realPath = realpathSync(record.collectionPath);
      const stat = statSync(realPath);
      if (!stat.isFile()) {
        throw new InstallationError(
          "The installed collection is no longer available."
        );
      }
      return realPath;
    } catch (err) {
      if (err instanceof InstallationError) throw err;
      throw new InstallationError(
        "The installed collection is no longer available."
      );
    }
  }

  /** Get the OBS scenes directory for an installation. */
  getObsScenesDirectory(installationId: string): string {
    const record = this._getValid(installationId);
    return record.obsScenesDirectory;
  }

  /** Get the safe display name for an installation. */
  getCollectionName(installationId: string): string {
    const record = this._getValid(installationId);
    return record.collectionName;
  }

  /** Remove an installation record. */
  remove(installationId: string): void {
    this._store.delete(installationId);
  }

  /** Clear all installations. */
  clear(): void {
    this._store.clear();
  }

  private _getValid(installationId: string): InstallationRecord {
    const record = this._store.get(installationId);
    if (!record) {
      throw new InstallationError(EXPIRED_INSTALLATION_ERROR);
    }
    const age = this._clock.now() - record.createdAt;
    if (age > INSTALLATION_TTL_MS) {
      this._store.delete(installationId);
      throw new InstallationError(EXPIRED_INSTALLATION_ERROR);
    }
    return record;
  }
}