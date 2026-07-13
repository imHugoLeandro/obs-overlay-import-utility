# Project Handoff

Last updated: 2026-07-13

## Project

OBS Overlay Import Utility is an open-source, portable Windows desktop application for repairing local asset paths in exported OBS scene collections. It is built with Python and Tkinter and distributed as a one-file PyInstaller executable.

Repository: <https://github.com/imHugoLeandro/obs-overlay-import-utility>

## Current state

- Branch: `main`
- Latest pushed commit: `217044c` — `Improve UI scaling theme contrast and Windows CI`
- Working tree was clean before this handoff file was added.
- Latest GitHub Actions test run passed: <https://github.com/imHugoLeandro/obs-overlay-import-utility/actions/runs/29268864090>
- Local portable executable: `dist/OBS Overlay Import Utility.exe`
- Current executable SHA-256: `85C804EDF4B940B44B560AFAAFAE02495901FD29EA5EAC3F0E7C1DFA9A5675FA`
- `dist/` is intentionally Git-ignored. Release executables should be built locally or through GitHub Actions.

## Implemented features

### Import Overlay

- Finds valid OBS scene collection JSON files inside an extracted overlay package.
- Relinks local image, video, audio, SVG, HTML, and third-party plugin asset paths.
- Supports Windows and POSIX-style source paths.
- Resolves duplicate filenames using trailing folder context.
- Refuses ambiguous matches instead of guessing.
- Requires all referenced files by default.
- Never edits the original collection.
- Writes a new `_ImportReady.json` atomically.
- Never overwrites an earlier converted output.

### Navigation

- Import Overlay: functional.
- Export Overlay: functional. It selects the active OBS scene collection by default, packages direct local resources, rewrites the collection JSON, and reports missing paths.
- Auto Resizer: functional. It can resize a collection, scene, or source with Stretch or aspect-preserving Scale Ratio, using the active OBS profile or a custom canvas. Every overwrite gets an undo backup.
- Settings: functional.

### Branding and settings

- Social Space logo displayed at the top-right.
- Original SVG and transparent PNG are stored under `src/obs_overlay_import_utility/assets/` and packaged in the executable.
- Logo is approximately 60×25 at 100% UI scale and responds to the UI scale setting.
- Themes: Windows default, white, and dark.
- Dark theme uses red-accent sliders, focus states, buttons, checkboxes, and borders.
- UI scale: 75–150% in 5% increments.
- UI scaling changes text, buttons, fields, padding, sliders, and logo size without changing the application window dimensions.
- Optional custom Python executable, disabled by default because the portable application bundles Python.
- Automatic OBS detection with an optional custom OBS executable.
- Remember-last-folder preference.
- Persistent strict/case-sensitive import defaults.
- Optional automatic opening of the output folder after conversion.

Settings are saved per user at:

```text
%APPDATA%\OBS Overlay Import Utility\settings.json
```

## Important files

```text
src/obs_overlay_import_utility/core.py       Conversion and discovery engine
src/obs_overlay_import_utility/exporter.py   Portable OBS package export engine
src/obs_overlay_import_utility/device_setup.py Device-source detection and post-import setup
src/obs_overlay_import_utility/resizer.py    Undoable OBS transform resize engine
src/obs_overlay_import_utility/paths.py      Cross-platform path matching
src/obs_overlay_import_utility/ui.py         Tkinter UI, navigation, themes, scaling
src/obs_overlay_import_utility/settings.py   Settings model and atomic persistence
src/obs_overlay_import_utility/assets/       Logo SVG and PNG
tests/test_core.py                           Conversion/path regression tests
tests/test_settings.py                       Settings persistence tests
scripts/build_portable.ps1                   Local Windows build entry point
.github/workflows/ci.yml                     Windows/Linux test matrix
.github/workflows/build-windows.yml          Tagged/manual portable build
docs/GITHUB_SYNC.md                          GitHub usage instructions
```

## Verification

The latest local verification completed successfully:

- 26 unit tests passed.
- 10 source/test files passed AST parsing.
- UI construction and navigation passed.
- Windows default, white, and dark themes passed switching tests.
- UI controls were measured at 75%, 100%, and 150%.
- Window geometry remained `820×700` throughout the scaling test.
- Button, field, slider, and logo dimensions changed with UI scale.
- Both logo assets were confirmed inside the PyInstaller archive.
- The packaged executable launched successfully and its test processes were closed cleanly.
- `git diff --check` passed.

Run tests:

```powershell
python -m unittest discover -s tests -v
```

Build the portable executable:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_portable.ps1
```

Close the running portable application before rebuilding it. The build script detects a locked executable and reports a clear error.

## GitHub Actions history

The earlier Windows CI failure in run `29268022819` was caused by equivalent temporary paths being represented as long paths (`runneradmin`) and Windows 8.3 paths (`RUNNER~1`). Tests now compare resolved canonical paths. Production conversion behavior was not the cause.

Workflows now use current Node-compatible action majors:

- `actions/checkout@v7`
- `actions/setup-python@v6`
- `actions/upload-artifact@v7`

The follow-up test run `29268864090` passed on Windows and Ubuntu.

## Known limitations and future work

- Export Overlay handles direct file references, but it cannot bundle installed OBS plugins, fonts, credentials, device sources, or remote web resources. Auto Resizer Undo is available for the most recent resize in the current app session; retained backup files are stored beside OBS scene collections.
- Custom Python and OBS paths are persisted for future tools; Import Overlay does not currently need either application path.
- Font and OBS plugin installation are outside the import utility's current scope.
- The executable is unsigned, so Windows SmartScreen may warn new users.
- At high UI scales, users may need to resize the window manually to expose more content; the UI slider intentionally does not resize the window.
- No automated release publishing is configured yet. Tagged builds create a downloadable workflow artifact.

## Portability rules for future AI work

When changing Import Overlay or Export Overlay, treat the complete OBS collection JSON as portable data—not just built-in OBS `file` settings.

- Preserve unknown source IDs, plugin settings, filters, nested lists, and metadata without dropping or normalizing them away.
- Import matching must continue to discover local files referenced by custom plugin sources and filters, including non-media extensions where a real local file is present.
- Export must recursively inspect the entire collection for absolute local file paths, copy existing files with arbitrary extensions, rewrite only those copied references, and report missing files instead of silently guessing.
- Never claim that an exported pack installs plugins, fonts, device sources, credentials, or remote services. Preserve their configuration in JSON and clearly report that the destination OBS installation still needs the relevant plugin or manual setup.
- Keep duplicate handling conservative: preserve one copied target per original file, but avoid overwriting a package asset when two different source files share a name.
## Device setup and browser-packer rules for future AI work

- Methods 2 and 3 expose an enabled-by-default device setup wizard, but it must appear only after a successful import whose resulting collection contains device-like sources.
- Do not invent operating-system device IDs. The wizard maps imported sources to compatible device sources already configured in the user's local OBS collections, copying their verified OBS settings. If there is no match, allow the user to keep the imported setting, disable the source, or configure it later in OBS.
- Continue to detect built-in camera/audio/display/capture sources and custom/plugin sources that contain device, monitor, or window settings. Preserve filters and every other source field when applying a device choice.
- Full browser-overlay export must retain a local HTML file's recursive folder structure so relative HTML, CSS, JavaScript, fonts, images, and media links remain valid. Do not follow symlinks during this copy.
## Auto Resizer rules for future AI work

- Auto Resizer intentionally overwrites the selected OBS collection because the user explicitly requested live-compatible editing. Always create and atomically save an undo backup before writing the new collection.
- Keep resize scopes clear: collection changes all scene-item transforms, scene changes only one scene's item transforms, and source changes each matching source item. The collection canvas is updated to the selected target size.
- Stretch uses independent X/Y factors. Scale Ratio uses a uniform fit factor and centers the result in the target canvas.
- Preserve all non-transform data exactly, including unknown plugin source settings, filters, resource paths, source IDs, and metadata. Do not attempt to resize plugin internals unless their transform is an OBS scene item.
- Do not silently delete backups. Only remove the backup after a successful explicit Undo restore.
## Safe continuation checklist

```powershell
git checkout main
git pull --ff-only origin main
git status --short
python -m unittest discover -s tests -v
```

Before committing:

```powershell
git diff --check
git status --short
git diff
```

Do not commit virtual environments, `build/`, `dist/`, `.spec` files, caches, customer overlay packages, OBS scene collections, or settings containing personal paths.
