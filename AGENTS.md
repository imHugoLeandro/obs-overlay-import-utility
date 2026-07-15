# AGENTS.md

## Mission

Maintain **OBS Overlay Import Utility**, a safe, lightweight Windows application for importing, exporting, repairing, resizing, and activating OBS overlay scene collections.

Preserve these product qualities:

- Simple enough for non-technical streamers.
- Portable as one Windows executable.
- Standard-library runtime bundled with PyInstaller; avoid heavy GUI/runtime dependencies.
- Conservative with customer assets and existing OBS configuration.
- Usable while OBS is open whenever live control can make the operation safe.

Keep this file at the repository root and commit it with the project.

## Work From Current Evidence

At the start of a task, inspect the current repository instead of trusting old conversations, hashes, test counts, or handoff claims:

```powershell
git status --short
git branch --show-current
git log --oneline --decorate -8
Get-ChildItem src\obs_overlay_import_utility
Get-ChildItem tests
```

Read only the relevant files. Usually start with:

```text
README.md
HANDOFF.md
pyproject.toml
src/obs_overlay_import_utility/<relevant module>.py
tests/<relevant tests>.py
```

`HANDOFF.md` contains detailed history, but the current code and tests are authoritative.

Do not switch branches, pull, commit, push, tag, publish, or rewrite Git history unless the user explicitly asks. Preserve unrelated user changes and untracked files.

For planning, research, or review-only requests, do not edit files or build artifacts.

## Product Goals

1. **Easy import**
   - Keep three clearly separated methods on the main Import Overlay page:
     - **Fix Scene Collection Paths**
     - **Import Streamlabs Scene File**
     - **Automatic Scene Collection**
   - Automatic mode prefers an OBS export JSON when both OBS and Streamlabs formats are present.
   - Minimize manual setup without hiding unresolved files or unsupported sources.

2. **Portable export**
   - Export a selected OBS collection with all discoverable local resources.
   - Show an inventory and missing-reference report before publishing.
   - Produce an organized package and a rewritten collection that references packaged files.

3. **Safe resizing**
   - Resize a collection, scene, or UUID-selected source.
   - Support Stretch and aspect-preserving Scale Ratio.
   - Support active-profile or custom canvas dimensions.
   - Respect OBS bounds modes and preserve undo.

4. **Live OBS operation**
   - Prefer OBS WebSocket for active collection switching and live transforms.
   - Never overwrite the active collection JSON behind OBS's back.

5. **Lightweight modern UI**
   - Retain the Social Space visual identity, sharp mixed-DPI rendering, system/light/dark themes, and app zoom without migrating to a heavyweight framework by default.

6. **Plugin-aware portability**
   - Preserve unknown sources, filters, nested settings, plugin metadata, UUIDs, and custom local-file references.

Possible future features—health checks, collection history/diff, dependency maps, and cross-collection scene copying—are ideas only. Do not implement them unless requested.

## Architecture

Keep domain logic outside `ui.py` and reuse shared engines instead of duplicating format-specific logic.

```text
src/obs_overlay_import_utility/
  automatic.py      Automatic pack detection/import orchestration
  appearance.py     DPI awareness, palettes, typography/display helpers
  constants.py      Application constants/version
  core.py           Collection discovery, validation, relinking, atomic helpers
  device_setup.py   Device detection and safe post-import mapping
  exporter.py       Inventory, staging, resource collection, package publication
  live_resize.py    Live OBS resize and undo
  models.py         Shared models, results, UtilityError
  obs_live.py       Lightweight OBS WebSocket client
  paths.py          Windows/POSIX path recognition and matching
  resizer.py        File-based transforms, backups, and resize calculations
  settings.py       Settings validation and atomic persistence
  streamlabs.py     Archive validation, extraction, conversion, installation
  ui.py             Tk/ttk shell, pages, dialogs, queues, workflows
  assets/           Packaged branding assets (SVGs, PNGs, logo)

tests/              Unit and failure-oriented regression tests
scripts/build_portable.ps1  Official Windows build entry point
scripts/app.manifest       Per-Monitor V2 manifest
tools/launcher.py          Packaged entry point
tools/render_icons.py      Design-time icon PNG generator (Pillow + svg.path)
```

Update this map when responsibilities change.

## Non-Negotiable Safety Invariants

### Original data and output

- Never modify an original imported scene-collection export.
- Never silently overwrite a collection, previous conversion, or package.
- Use unique output names and atomic JSON writes.
- Back up file-based collection changes before resizing.
- Undo must target the exact operation that created its snapshot or backup.

### Transactional import and export

Streamlabs installation and Export Overlay must remain transactional:

1. Validate and inventory first.
2. Stage work on the destination filesystem.
3. Publish only after every required step succeeds.
4. Roll back pending JSON, extracted folders, staging directories, and partial output after failure.

Do not weaken rollback or preflight behavior merely to simplify implementation.

### Conservative path handling

- Never guess between ambiguous duplicate filenames.
- Prefer exact relative paths, then safe trailing-folder context, then a unique filename only when unambiguous.
- Respect case-sensitive matching.
- Recognize Windows and POSIX source paths regardless of the host OS.
- Exclude URLs, `data:` values, and unrelated strings from local-file rewriting.
- Rewrite only references proven to match files that were found or copied.
- Recursively inspect custom plugin and filter settings for real absolute local files, including non-media extensions.
- Preserve every unknown field not intentionally changed.

### Untrusted archives

Treat `.overlay` files as hostile input. Before extraction:

- Normalize `/` and `\` separators.
- Reject traversal, absolute, UNC, and drive-qualified paths.
- Reject links, special/encrypted entries, reparse-like content, and normalized duplicate names.
- Enforce entry-count, member-size, total-size, compression-ratio, and free-space limits.
- Validate the complete archive before writing files.
- Extract only under the new destination directory.

Changes to archive limits or validation require acceptance and rejection tests.

## Import Requirements

### Fix Scene Collection Paths

- The user selects the overlay pack folder.
- Detect valid OBS collection JSON automatically when possible.
- Keep strict validation and case-sensitive matching as advanced options, enabled by default unless requirements change.
- Report matched, missing, and ambiguous assets.
- Strict mode must prevent output when required references remain unresolved.

### Import Streamlabs Scene File

- Validate the chosen `.overlay` before extraction.
- Extract beside the archive into a unique Windows-safe folder.
- Convert supported sources while preserving/reporting unsupported configuration.
- Recursively relink built-in and custom/plugin resource paths.
- Install a unique OBS collection name: `Name`, `Name 1`, `Name 2`, and so on.
- Run the device wizard only when compatible device-like sources exist and the option is enabled.
- Complete device mapping before live activation.

### Automatic Scene Collection

- Scan the selected pack recursively.
- Prefer an OBS export JSON over `.overlay` when both are present.
- Call the existing OBS/Streamlabs engines; do not create a third conversion implementation.
- Stop on multiple equally valid candidates instead of guessing.

## Export Requirements

- Select the active collection by default when it can be identified safely.
- Inventory every discovered local file and missing reference before copying.
- Require explicit confirmation after showing the inventory.
- Revalidate at execution time.
- Recursively package local browser projects and their relative HTML/CSS/JS/fonts/images/media dependencies.
- Prevent destination-inside-source recursion.
- Reject broad personal/system roots, links/reparse points, and projects beyond configured count/size limits.
- Prevent collisions when different source files share a name.
- Sanitize package folder names for Windows.

Export does **not** bundle or install OBS plugin binaries, operating-system fonts, credentials, physical devices, or remote web services. Preserve their JSON configuration and report what still requires local setup.

## Device Setup Requirements

- Match imported devices only to local candidates with the exact OBS source ID/type.
- Copy only verified device-selector fields.
- Preserve imported resolution, FPS, filters, source IDs, plugin settings, and unrelated configuration.
- Never replace the complete settings dictionary broadly.
- Use UUID-backed identity when names can be duplicated.
- Keep the wizard modal, scrollable, and explicit about partial errors.

## Resize Requirements

- Collection scope may change the collection canvas.
- Scene and Source scopes must preserve the collection canvas.
- Display source choices as `Source Name (UUID)` and operate by UUID.
- Scale Ratio preserves aspect ratio; Stretch may use independent X/Y ratios.
- Handle active OBS bounds modes without double-scaling.
- Resize only real OBS scene/group item transforms, never similarly named values in arbitrary plugin settings.

## Running While OBS Is Open

- Export is read-only toward OBS and may run while OBS is open.
- New collections may be installed, then activated through OBS WebSocket.
- Active collection resize/undo must use live requests.
- If live control is unavailable, refuse to overwrite the active collection file and explain why.
- Inactive file-based changes still require backups and must avoid races with collection switching.

### OBS WebSocket

- Target OBS 28+, where WebSocket is built in.
- The current implementation assumes the standard local port `4455` unless configurable endpoints are explicitly added and tested.
- Keep credentials in memory only. Never save real passwords in settings, logs, source, fixtures, or documentation.
- Handle authentication, connection, timeout, malformed-frame, buffering, and request errors distinctly.
- Do not assume one socket read contains exactly one complete WebSocket message.
- If activation fails, the UI may report the collection as installed but must not claim it was activated.

## UI and Portability Rules

- Keep standard-library Tk/ttk and a one-file PyInstaller build unless the user approves a measured migration.
- Do not introduce Qt, Electron, a browser runtime, or another heavyweight GUI dependency by default.
- Preserve `scripts/app.manifest` and Per-Monitor V2 DPI awareness.
- Enable DPI awareness before creating `tk.Tk()`.
- Keep Windows display scaling separate from the 75–150% app zoom.
- App zoom changes fonts, controls, spacing, consoles, navigation, sliders, and logo size—not the window size itself.
- Preserve system/light/dark themes, Social Space red semantic accents, and at least WCAG AA 4.5:1 contrast for normal text.
- Keep import-method selection inside the main window. Modal dialogs are acceptable for focused flows such as device setup and export confirmation.
- Never update Tk widgets from worker threads. Use the existing queue and `root.after(...)` processing.
- File scans, archive work, import/export, and network operations must not block the UI thread.
- Show actionable errors without raw tracebacks.

## Python Standards

- Support Python 3.10+.
- Preserve zero runtime dependencies unless a requirement cannot reasonably be met otherwise.
- Prefer `pathlib.Path`, type hints, dataclasses/existing result models, and specific exceptions.
- Use `UtilityError` or a more specific project exception for expected user-facing failures.
- Avoid bare `except`, silent error swallowing, and duplicated walkers/relinkers/resizers.
- Keep validation, conversion, inventory, and transform logic testable without Tk.
- Comment safety invariants and non-obvious OBS format behavior, not obvious syntax.

## Tests and Verification

Every feature or bug fix needs tests for the requested behavior and important failures.

Run after code changes:

```powershell
python -m unittest discover -s tests -v
python -m ruff check .
git diff --check
```

If Ruff is unavailable, use the project's configured environment or clearly state that static analysis did not run.

When changing imports, packaging, or large patches, parse all Python files:

```powershell
@'
import ast
from pathlib import Path

paths = list(Path("src").rglob("*.py")) + list(Path("tests").rglob("*.py"))
for path in paths:
    ast.parse(path.read_text(encoding="utf-8"))
print(f"AST OK: {len(paths)} files")
'@ | python -
```

Add failure-oriented coverage where relevant, especially for:

- Missing/ambiguous assets and duplicate output names.
- Atomic-write, extraction, publication, and rollback failures.
- Archive traversal, duplicate normalized paths, links, encryption, size/ratio limits, and low disk space.
- Browser-project recursion, unsafe roots, links, and limits.
- Duplicate display names with different UUIDs.
- Bounds modes and no double-scaling.
- Device type mismatch and partial wizard failure.
- Active collection protection and WebSocket authentication/buffering/timeouts.
- DPI manifest, theme switching, contrast, and dependency-free packaging.

Do not cite an old test count as proof. Run the current suite and report its actual result.

## Portable Build Requirement

After substantive user-facing code or UI changes, build the portable executable so the user can test it—unless the request was explicitly planning/review only or the user said not to build.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_portable.ps1
```

The expected output is:

```text
dist\OBS Overlay Import Utility.exe
```

Before building, pass source tests and close any running copy of the executable. Do not kill unrelated or pre-existing user processes.

After building:

- Confirm the file exists and report its size and SHA-256.
- Launch only the newly built executable for a brief smoke test.
- Close only processes created by that smoke test.
- Verify packaged assets and the DPI manifest when relevant.
- Report tests, build result, smoke-test result, and remaining limitations.

Do not commit `dist/`, `build/`, `.venv-build/`, generated `.spec` files, caches, customer archives/extractions, OBS collections, or settings containing personal paths.

## Documentation

Update only what the change affects:

- `README.md`: end-user behavior and instructions.
- `CHANGELOG.md`: user-visible changes.
- `HANDOFF.md`: current architecture, verification, limitations, and detailed continuation context.
- `AGENTS.md`: repository-wide engineering rules and invariants.

Do not hard-code transient hashes, branch state, executable sizes, or test counts in this file.

## Known Limitations

Do not hide or overstate these limitations:

- The executable is unsigned; Windows SmartScreen may warn users.
- OBS plugin binaries, OS-installed fonts, credentials, physical devices, and remote service state are not packaged or installed.
- Unsupported Streamlabs/plugin source types may need manual setup; preserve and report them instead of dropping them.
- Remote browser URLs are not made offline by preserving the URL.
- Live control requires OBS WebSocket to be enabled and reachable; current live control uses the standard local port.
- When live control is unavailable, active-collection file overwrites must remain blocked.
- Auto Resizer undo is the latest supported snapshot/backup workflow, not permanent version history.
- High app zoom may require the user to enlarge the window manually.
- Automated public release publishing is not guaranteed; tagged/manual workflows may only create artifacts.

## Completion Checklist

Before claiming completion:

1. Re-read the user's exact request and map every requirement to evidence.
2. Confirm unrelated user work was preserved.
3. Run applicable unit, static, AST, UI, and build checks.
4. Inspect `git diff --check`, `git diff`, and `git status --short`.
5. Update documentation only where required.
6. Build the portable executable after substantive user-facing changes.
7. Report what changed, what was verified, what was not tested in a real OBS installation, and all remaining limitations.

Happy-path tests alone do not prove the task is complete.
