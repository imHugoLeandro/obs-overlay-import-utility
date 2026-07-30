# Project Handoff

Last updated: 2026-07-16

## Project

OBS Overlay Import Utility is an open-source, portable Windows desktop application for repairing local asset paths in exported OBS scene collections. It is built with Python and Tkinter and distributed as a one-file PyInstaller executable.

Repository: <https://github.com/imHugoLeandro/obs-overlay-import-utility>

## Current state

- Branch: `main`
- Latest pushed commit before these working changes: `333e1ea` — `fix: adjust indicator margins and sizes for better UI consistency`
- Working tree has uncommitted vertical-scrollbar thickness enhancement.
- Latest GitHub Actions test run passed: <https://github.com/imHugoLeandro/obs-overlay-import-utility/actions/runs/29268864090>
- Local portable executable: `dist/OBS Overlay Import Utility.exe`
- Current executable SHA-256: `F4C5310B92CB5AF18B7182F4021631F9C24D7A337D0491353159293583CCA5E0`
- `dist/` is intentionally Git-ignored. Release executables should be built locally or through GitHub Actions.

## Electron portable delivery (current branch)

- The Electron + React shell under `desktop/` is the primary portable delivery path. The Tk executable remains the explicitly named fallback built by `scripts/build_portable_tk.ps1`.
- Renderer-to-main channels are fixed in `desktop/src/main/contracts/channels.ts`; preload and main process imports must use that registry. There is no generic renderer-to-main invoke endpoint.
- The Python JSON-lines backend command allow-list is independent at `desktop/src/main/contracts/backendCommands.ts`. Native file-selection operations remain local Electron handlers and must not be treated as backend commands.
- `desktop/scripts/package-backend.cjs` packages only `tools/desktop_backend.py`, with the explicit `OBS_OVERLAY_BUILD_PYTHON` executable. It never packages the Tk launcher.
- `scripts/build_portable_electron.ps1` is the primary local build command. It creates/uses `.venv-build-electron`, installs the Python build dependencies through that executable, runs `npm ci`, builds renderer/main/preload once, verifies that exact output, packages the backend once, then invokes Electron Builder.
- `-CleanDependencies` is opt-in. Normal builds preserve a valid `desktop/node_modules`; cleanup errors must never kill unrelated processes.
- The Windows workflow follows the same order and smoke-tests the packaged app. No Windows packaged smoke result is authoritative until the workflow completes for the committed SHA.

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
- Export Overlay: functional. It selects the active OBS scene collection by default, inventories every file and missing reference for confirmation, packages direct and browser resources transactionally, rewrites the collection JSON, and uses Windows-safe package names.
- Auto Resizer: functional. Active collections resize and undo through obs-websocket while OBS remains open; inactive collection files retain atomic undo backups. Stretch, Scale Ratio, collection/scene/UUID source scopes, active bounds, and custom/profile canvases are supported.
- Settings: functional.

### Branding and settings

- Social Space logo displayed in a persistent responsive left navigation sidebar.
- Original SVG and transparent PNG are stored under `src/obs_overlay_import_utility/assets/` and packaged in the executable.
- Logo scales from its 240×100 packaged source according to monitor DPI and user zoom without external imaging dependencies.
- Themes: Windows default, white, and dark. Windows default resolves the current Windows app theme at startup.
- Accessible light/dark semantic palettes use Social Space red primary actions, modern cards, styled consoles, clear focus states, and WCAG AA text contrast.
- UI scale: 75–150% in 5% increments.
- Per-Monitor V2 DPI awareness, monitor-change watching, and independent UI zoom scale fonts, buttons, fields, padding, navigation, sliders, consoles, and the logo without Windows bitmap stretching.
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
src/obs_overlay_import_utility/obs_live.py  Dependency-free obs-websocket 5.x client
src/obs_overlay_import_utility/live_resize.py Live active-collection resize and undo engine
src/obs_overlay_import_utility/paths.py      Cross-platform path matching
src/obs_overlay_import_utility/ui.py         Responsive Tk UI, navigation, themes, scaling
src/obs_overlay_import_utility/appearance.py  DPI awareness and semantic light/dark palettes
src/obs_overlay_import_utility/settings.py   Settings model and atomic persistence
src/obs_overlay_import_utility/assets/       Logo SVG and PNG
tests/test_core.py                           Conversion/path regression tests
tests/test_settings.py                       Settings persistence tests
tests/test_appearance.py                     DPI, contrast, manifest, and portability tests
scripts/build_portable.ps1                   Compatibility entry point (Electron by default; -LegacyTk for Tk)
scripts/app.manifest                         Per-Monitor V2 Windows manifest
.github/workflows/ci.yml                     Windows/Linux test matrix
.github/workflows/build-windows.yml          Tagged/manual portable build
docs/GITHUB_SYNC.md                          GitHub usage instructions
```

## Verification

Current working changes add transactional Streamlabs installation, hardened archive limits, recursive plugin-resource relinking, export inventory confirmation, UUID-backed source resizing, bounds-aware transforms, and a scrollable error-reporting device wizard.

The latest local verification completed successfully:

- 56 unit tests passed, including live OBS authentication/buffering, live resize/undo, DPI manifest embedding, accessible palette contrast, dependency-free portability, and import/export/resizer safety coverage.
- Source and test files pass Python compilation and AST parsing.
- UI construction and navigation passed.
- Windows default, white, and dark themes passed switching tests.
- UI controls were measured at 75%, 100%, and 150%.
- The DPI-aware initial window centered at `1055×757` logical pixels on the 144-DPI test display and remained responsive at 75%, 100%, and 150% zoom.
- Button, field, slider, and logo dimensions changed with UI scale.
- Both logo assets were confirmed inside the PyInstaller archive.
- The rebuilt 12,068,008-byte packaged executable launched successfully; its embedded Per-Monitor V2 manifest was verified by the build tests, and only its two one-file runtime processes were closed.
- `git diff --check` passed.

Run tests:

```powershell
python -m unittest discover -s tests -v
```

Build the portable executable:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_portable.ps1
# Optional legacy fallback: add -LegacyTk
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

- Export Overlay cannot bundle installed OBS plugins, fonts, credentials, device sources, or remote web resources. Live control currently targets the standard local obs-websocket port `4455`; a custom server port is not yet exposed in Settings. Live Undo is available for the current app session, while inactive-file backups are retained beside OBS scene collections.
- Custom Python and OBS paths are persisted for future tools; Import Overlay does not currently need either application path.
- Font and OBS plugin installation are outside the import utility's current scope.
- The executable is unsigned, so Windows SmartScreen may warn new users.
- At high UI scales, users may need to resize the window manually to expose more content; the UI slider intentionally does not resize the window.
- No automated release publishing is configured yet. Tagged builds create a downloadable workflow artifact.

## Portability rules for future AI work

When changing Import Overlay or Export Overlay, treat the complete OBS collection JSON as portable data—not just built-in OBS `file` settings.

For UI work, preserve the dependency-free Tk/ttk runtime and one-file build unless a measured requirement truly cannot be met. Keep `scripts/app.manifest`, call DPI awareness before `tk.Tk()`, retain Per-Monitor V2/mixed-DPI checks, and keep normal text contrast at 4.5:1 or better.

- Preserve unknown source IDs, plugin settings, filters, nested lists, and metadata without dropping or normalizing them away.
- Import matching must continue to discover local files referenced by custom plugin sources and filters, including non-media extensions where a real local file is present.
- Export must recursively inspect the entire collection for absolute local file paths, copy existing files with arbitrary extensions, rewrite only those copied references, and report missing files instead of silently guessing.
- Never claim that an exported pack installs plugins, fonts, device sources, credentials, or remote services. Preserve their configuration in JSON and clearly report that the destination OBS installation still needs the relevant plugin or manual setup.
- Keep duplicate handling conservative: preserve one copied target per original file, but avoid overwriting a package asset when two different source files share a name.
- Keep Streamlabs install and Export Overlay transactional. Preflight before copying, stage output under the destination filesystem, publish only complete results, and roll back partial extracted folders or pending collection files on failure.
- Treat archive limits as security boundaries: normalize both slash styles, reject traversal/absolute/drive paths, links, special/encrypted entries and normalized duplicates, and enforce entry, member, total, compression-ratio, and free-space limits before extraction.
## Device setup and browser-packer rules for future AI work

- Methods 2 and 3 expose an enabled-by-default device setup wizard, but it must appear only after a successful import whose resulting collection contains device-like sources.
- Do not invent operating-system device IDs. Offer only local candidates whose OBS source ID exactly matches the imported source, and copy only recognized device-selector fields. Never replace the source ID or overwrite resolution, FPS, filters, or complete settings dictionaries. If there is no match, allow the user to keep the imported setting, disable the source, or configure it later in OBS.
- Continue to detect built-in camera/audio/display/capture sources and custom/plugin sources that contain recognized device, monitor, display, or window selector settings. Preserve filters and every other source field when applying a device choice.
- Full browser-overlay export must retain a local HTML file's recursive folder structure so relative HTML, CSS, JavaScript, fonts, images, and media links remain valid. Reject drive roots and broad personal/system folders, reject export destinations inside the browser project, cap the project at 10,000 files and 2 GB, skip symlinks and Windows reparse points, and publish from staging only after the complete pack succeeds.
## Auto Resizer rules for future AI work

- Auto Resizer intentionally overwrites the selected OBS collection because the user explicitly requested live-compatible editing. Always create and atomically save an undo backup before writing the new collection.
## Live OBS rules for future AI work

- OBS 28+ bundles obs-websocket 5.x. Keep the live client dependency-free and local-only unless a deliberate settings/security design changes that.
- Never persist or log the WebSocket password; keep it only in application memory.
- Finish all file-based device setup before activating an imported collection in OBS.
- Never overwrite the JSON of the collection currently loaded by a running OBS instance. Use `SetSceneItemTransform` and `SetVideoSettings` live; if live control is unavailable, stop safely.
- Inactive collection files may use the existing atomic backup/undo workflow while OBS is open.
- Keep resize scopes clear: Collection changes all scene-item transforms and updates the canvas; Scene and Source change only selected scene-item transforms and preserve the current canvas.
- Stretch uses independent X/Y factors. Scale Ratio uses a uniform fit factor and centers the selected layout in the requested target size.
- Preserve all non-transform data exactly, including unknown plugin source settings, filters, resource paths, source IDs, and metadata. Automatic import resizing and Auto Resizer must traverse only the `items` arrays of OBS `scene` and `group` sources; never recursively resize arbitrary plugin dictionaries.
- Do not silently delete backups. Only remove the backup after a successful explicit Undo restore.
- Source scope must identify scene items by `source_uuid`, and the UI must show `Source Name (UUID)`; display names alone are not unique.
- Respect `bounds_type`: scale active bounds instead of also scaling source scale, and scale source scale only when bounds are inactive.
## Scrollbar thickness rules for future AI work

- Use the centralized ``ScrollbarMetrics`` frozen dataclass and ``scrollbar_metrics(ui_zoom)`` helper in ``dialogs.py`` as the single source of truth for scrollbar sizing.
- Base target at 96 DPI / 100% zoom: **28 px** vertical, 18 px horizontal, 16 px arrow size. Scaled linearly with ``ui_zoom`` (and combined DPI factor in ``_apply_ui_scale``).
- Minimum vertical thickness: 20 px.
- Dedicated styles: ``Vertical.TScrollbar`` / ``Horizontal.TScrollbar`` for main pages, ``Dialog.Vertical.TScrollbar`` / ``Dialog.Horizontal.TScrollbar`` for dialogs.
- Every scrollbar in the application must use one of these styles. New dialogs must use ``Dialog.Vertical.TScrollbar`` / ``Dialog.Horizontal.TScrollbar`` explicitly.
- ``_apply_ui_scale`` must re-call ``configure_dialog_styles`` so open dialogs receive updated scrollbar dimensions on zoom/dpi change.
- ``compute_body_wraplength`` defaults to ``scrollbar_metrics(ui_zoom).vertical_thickness``.
- The ``clam`` ttk theme controls scrollbar cross-axis width via ``sliderthickness`` and arrow-button size via ``arrowsize``; always set both.
## UI-size slider rules for future AI work

- The Settings UI-size control is now a classic ``tk.Scale``, not a ``ttk.Scale``. The ``clam`` ttk theme's ``Horizontal.Scale.slider`` and ``Horizontal.Scale.trough`` elements do not support ``sliderthickness``, so changing that value had no effect on the rendered widget height.
- Size is controlled via the centralized ``UiScaleMetrics`` frozen dataclass and ``ui_scale_metrics(dimension_factor)`` helper in ``dialogs.py``. This accepts the combined ``dimension_factor`` (UI zoom * DPI ratio).
- Base target at 96 DPI / 100% zoom: **32 px** widget height (``trough_width=30``, ``highlightthickness=1`` → ``height = 30 + 2 = 32``).
- ``slider_length=30`` controls the thumb length; ``trough_width`` controls the cross-axis height.
- Theming is handled by ``_apply_ui_scale_widget_theme()``, called during init, ``_apply_theme()``, ``_apply_ui_scale()``, and DPI refresh. It configures ``bg``, ``troughcolor``, ``activebackground``, ``highlightbackground``, ``highlightcolor``, ``width``, ``sliderlength``, and ``highlightthickness`` from the shared palette.
- The widget is safe-guarded with ``hasattr(self, "ui_scale")`` to avoid errors during early init before the Settings page is built.
- Checkbox ``indicatorsize`` was reduced from base 12 px to 10 px (~20%): ``max(8, round(10 * dimension_factor))``. Radio ``indicatordiameter`` from 11 to 9 px. ``indicatormargin`` top reduced from 4 to 3.
- Do not revert ``self.ui_scale`` to a ``ttk.Scale`` without first proving that the active ttk theme supports cross-axis thickness.
- Interaction state is tracked via three instance booleans: ``_ui_scale_hovered``, ``_ui_scale_focused``, ``_ui_scale_pressed``. Priority: pressed > focused or hovered > idle.
- ``_refresh_ui_scale_visual_state()`` resolves the current idle/hover/focus/pressed appearance using ``dlgs.ui_scale_colors(self.current_palette)``. Theme changes while hovered, focused, or pressed automatically resolve the current state with the new palette.
- ``_bind_ui_scale_interactions()`` is called once after slider construction and binds ``<Enter>``, ``<Leave>``, ``<FocusIn>``, ``<FocusOut>``, ``<ButtonPress-1>``, ``<ButtonRelease-1>`` to named methods. Bindings are not unbound or rebound during theme/zoom refreshes.
- ``_apply_ui_scale_widget_theme()`` updates only palette-based colors (``troughcolor``, ``activebackground``, ``highlightbackground``) and dimensions (``width``, ``sliderlength``, ``highlightthickness``), then calls ``_refresh_ui_scale_visual_state()``.
- ``_on_ui_scale_release()`` synchronizes ``_ui_scale_hovered`` from pointer position, calls ``_refresh_ui_scale_visual_state()``, then invokes ``_on_scale_released()`` once.
- Binding closures and ``unbind``/``bind`` cycles during theme refresh have been removed.
- ``UiScaleColors`` no longer exposes an unused ``widget_background`` field; ``tk.Scale`` ``background`` option controls the thumb color only and is mapped to ``thumb``/``thumb_active``.
- Windows CI geometry tests now use a platform-tolerant ``assertGreaterEqual(h, 20)`` and ``assertLessEqual(h, 50)`` with Tcl/Tk version diagnostics.
- Ubuntu CI tests run under ``xvfb-run`` from the main test step.
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
