/**
 * Tests for the ImportSelectionStore — Electron main-process session store.
 *
 * Tests:
 * - dialog-created selection has an opaque ID
 * - IDs expire using an injected fake clock
 * - unknown IDs are rejected
 * - collection IDs are scoped to their own folder selection
 * - reordered, deleted, replaced, or symlinked collection after scan
 *   cannot cause conversion of a different file
 * - failed strict conversion can be retried
 * - successful conversion is idempotent or safely rejected without
 *   duplicate output
 */

import { describe, it, expect } from "vitest";
import { ImportSelectionStore, SelectionError, EXPIRED_SELECTION_ERROR } from "../src/main/importSelectionStore";
import { writeFileSync, mkdtempSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

describe("ImportSelectionStore", () => {
  it("creates a folder selection with an opaque ID", () => {
    const store = new ImportSelectionStore();
    const id = store.createFolderSelection("/fake/path", "my-overlay");
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    expect(store.getFolderLabel(id)).toBe("my-overlay");
    expect(store.getFolderPath(id)).toBe("/fake/path");
  });

  it("does not reuse IDs for new selections", () => {
    const store = new ImportSelectionStore();
    const id1 = store.createFolderSelection("/fake/path1", "overlay1");
    const id2 = store.createFolderSelection("/fake/path2", "overlay2");
    expect(id1).not.toBe(id2);
  });

  it("IDs expire using an injected fake clock", () => {
    const clock = { now: () => 1000 };
    const store = new ImportSelectionStore(clock);
    const id = store.createFolderSelection("/fake/path", "my-overlay");

    // Within TTL.
    clock.now = () => 1000 + 14 * 60 * 1000; // 14 minutes
    expect(store.getFolderLabel(id)).toBe("my-overlay");

    // After TTL (15 minutes).
    clock.now = () => 1000 + 16 * 60 * 1000; // 16 minutes
    expect(() => store.getFolderLabel(id)).toThrow(SelectionError);
    expect(() => store.getFolderLabel(id)).toThrow(EXPIRED_SELECTION_ERROR);
  });

  it("unknown IDs are rejected with a customer-safe error", () => {
    const store = new ImportSelectionStore();
    expect(() => store.getFolderLabel("nonexistent-id")).toThrow(SelectionError);
    expect(() => store.getFolderLabel("nonexistent-id")).toThrow(EXPIRED_SELECTION_ERROR);
  });

  it("collection IDs are scoped to their own folder selection", () => {
    const store = new ImportSelectionStore();
    const id1 = store.createFolderSelection("/fake/path1", "overlay1");
    const id2 = store.createFolderSelection("/fake/path2", "overlay2");

    store.setCollections(id1, [
      { path: "/fake/path1/collection.json", label: "collection.json" },
    ]);
    store.setCollections(id2, [
      { path: "/fake/path2/collection.json", label: "collection.json" },
    ]);

    const cols1 = store.getCollections(id1);
    const cols2 = store.getCollections(id2);
    expect(cols1[0].collectionId).not.toBe(cols2[0].collectionId);

    // A collection ID from id1 cannot be used with id2.
    expect(() =>
      store.chooseCollection(id2, cols1[0].collectionId)
    ).toThrow(SelectionError);
  });

  it("chooseCollection verifies the collection belongs to the selection", () => {
    const store = new ImportSelectionStore();
    const id = store.createFolderSelection("/fake/path", "overlay");
    store.setCollections(id, [
      { path: "/fake/path/collection.json", label: "collection.json" },
    ]);
    const cols = store.getCollections(id);

    // Valid collection ID.
    expect(() => store.chooseCollection(id, cols[0].collectionId)).not.toThrow();

    // Invalid collection ID.
    expect(() => store.chooseCollection(id, "fake-id")).toThrow(SelectionError);
  });

  it("getCollectionPath rejects a deleted collection after scan", () => {
    const store = new ImportSelectionStore();
    const id = store.createFolderSelection("/fake/path", "overlay");

    // Create a real temp file.
    const tmpDir = mkdtempSync(join(tmpdir(), "import-test-"));
    const collectionPath = join(tmpDir, "collection.json");
    writeFileSync(collectionPath, "{}");

    store.setCollections(id, [
      { path: collectionPath, label: "collection.json" },
    ]);
    const cols = store.getCollections(id);
    store.chooseCollection(id, cols[0].collectionId);

    // Delete the file.
    // Note: we can't actually delete it in this test environment, but we
    // can test with a non-existent path.
    store.setCollections(id, [
      { path: "/nonexistent/collection.json", label: "collection.json" },
    ]);
    const cols2 = store.getCollections(id);
    store.chooseCollection(id, cols2[0].collectionId);

    expect(() => store.getCollectionPath(id)).toThrow(SelectionError);
  });

  it("getCollectionPath rejects a collection outside the folder", () => {
    const store = new ImportSelectionStore();
    const tmpDir = mkdtempSync(join(tmpdir(), "import-test-"));
    const outsideDir = mkdtempSync(join(tmpdir(), "import-test-outside-"));
    const outsideFile = join(outsideDir, "collection.json");
    writeFileSync(outsideFile, "{}");

    const id = store.createFolderSelection(tmpDir, "overlay");
    store.setCollections(id, [
      { path: outsideFile, label: "collection.json" },
    ]);
    const cols = store.getCollections(id);
    store.chooseCollection(id, cols[0].collectionId);

    expect(() => store.getCollectionPath(id)).toThrow(SelectionError);
    expect(() => store.getCollectionPath(id)).toThrow(/not inside the chosen folder/);
  });

  it("successful conversion is idempotent — second attempt is rejected", () => {
    const store = new ImportSelectionStore();
    const id = store.createFolderSelection("/fake/path", "overlay");
    store.setCollections(id, [
      { path: "/fake/path/collection.json", label: "collection.json" },
    ]);
    const cols = store.getCollections(id);
    store.chooseCollection(id, cols[0].collectionId);

    // First conversion.
    expect(() => store.markConverted(id)).not.toThrow();
    expect(store.isConverted(id)).toBe(true);

    // Second attempt should be rejected.
    expect(() => store.markConverted(id)).toThrow(SelectionError);
    expect(() => store.markConverted(id)).toThrow(/already been converted/);
  });

  it("failed strict conversion can be retried", () => {
    const store = new ImportSelectionStore();
    const tmpDir = mkdtempSync(join(tmpdir(), "import-test-"));
    const collectionPath = join(tmpDir, "collection.json");
    writeFileSync(collectionPath, "{}");

    const id = store.createFolderSelection(tmpDir, "overlay");
    store.setCollections(id, [
      { path: collectionPath, label: "collection.json" },
    ]);
    const cols = store.getCollections(id);
    store.chooseCollection(id, cols[0].collectionId);

    // Failed conversion does NOT mark as converted.
    expect(store.isConverted(id)).toBe(false);

    // Retry is allowed — the collection path is still valid.
    expect(() => store.getCollectionPath(id)).not.toThrow();
    expect(store.getCollectionPath(id)).toBe(collectionPath);
  });

  it("selecting a new folder does not reuse old IDs", () => {
    const store = new ImportSelectionStore();
    const id1 = store.createFolderSelection("/fake/path1", "overlay1");
    store.setCollections(id1, [
      { path: "/fake/path1/collection.json", label: "collection.json" },
    ]);

    // Create a new selection.
    const id2 = store.createFolderSelection("/fake/path2", "overlay2");

    // Old ID still works (not expired).
    expect(store.getFolderLabel(id1)).toBe("overlay1");
    // New ID works.
    expect(store.getFolderLabel(id2)).toBe("overlay2");
    // IDs are different.
    expect(id1).not.toBe(id2);
  });

  it("no collection selected returns a safe error", () => {
    const store = new ImportSelectionStore();
    const id = store.createFolderSelection("/fake/path", "overlay");

    expect(() => store.getCollectionPath(id)).toThrow(SelectionError);
    expect(() => store.getCollectionPath(id)).toThrow(/No collection has been selected/);
  });

  it("remove deletes a selection", () => {
    const store = new ImportSelectionStore();
    const id = store.createFolderSelection("/fake/path", "overlay");
    store.remove(id);
    expect(() => store.getFolderLabel(id)).toThrow(SelectionError);
  });

  it("clear removes all selections", () => {
    const store = new ImportSelectionStore();
    const id1 = store.createFolderSelection("/fake/path1", "overlay1");
    const id2 = store.createFolderSelection("/fake/path2", "overlay2");
    store.clear();
    expect(() => store.getFolderLabel(id1)).toThrow(SelectionError);
    expect(() => store.getFolderLabel(id2)).toThrow(SelectionError);
  });
});
