# OBS Overlay Import Utility

A small, open-source Windows desktop utility that imports and exports portable OBS overlay packages. It is designed for independent overlay creators who want customers to import a package without manually finding and replacing every image, video, audio, local browser-source, plugin, or filter resource path.

The portable build is a single lightweight executable: it has no installer, does not require Python, and adds no heavyweight GUI runtime dependencies.

The Settings page supports the Windows default, white, and dark themes; adjustable UI scaling; remembered overlay folders; import defaults; and optional custom OBS/Python locations. Settings are saved per Windows user in `%APPDATA%\OBS Overlay Import Utility\settings.json`.

## Interface and display

- Lightweight standard-library Tk/ttk interface with no Qt, Electron, browser engine, or third-party theme runtime.
- Responsive left-side tool navigation with clear page titles, bordered option cards, semantic primary actions, and compact status consoles.
- Accessible light and dark palettes with the Social Space red accent; **Windows default** follows the current Windows app theme at startup.
- Windows Per-Monitor V2 DPI awareness is embedded in the executable and enabled before Tk starts, preventing Windows bitmap stretching on high-DPI displays.
- The interface watches for monitor-DPI changes, uses Segoe UI Variable/Segoe UI and Cascadia Mono/Consolas when available, and retains independent 75–150% user zoom.
- The Social Space logo is scaled from its packaged high-resolution source, and the initial window is centered and bounded to the available display.
## Customer workflow

### Method 1 — Import OBS Scene Collection File

1. Expand **Method 1** with its down arrow.
2. Choose the extracted **Overlay Folder path**, or browse a **ZIP archive** and the utility extracts it beside the file first.
3. Click **Run**. The utility finds the OBS scene collection export automatically.
4. The utility writes a new `_Updated.json` file, installs it into OBS as a new scene collection, and switches to it live when OBS is open.

Original collection is never changed. **Strict file checking and case-sensitive filename matching are always enabled** — no user toggle can weaken them. By default the import also scales the layout to your active OBS canvas (aspect-preserving) and finishes with a health report that tells you exactly what is online, what is missing, which plugin sources need a locally installed plugin, and which browser overlays need internet.

### Method 2 — Import Streamlabs Scene File

1. Expand **Method 2** with its down arrow.
2. Choose the Streamlabs `.overlay` package — or a **ZIP archive** that contains exactly one `.overlay` file, which is extracted first.
3. Click **Run** in the same Import Overlay window.

The utility validates the archive before extraction (including entry, per-file, total-size, compression-ratio, path, link, encryption, duplicate-name, and free-space limits), then extracts beside the archive into a new `name overlay` folder. It recursively relinks assets in built-in and custom/plugin source and filter settings and converts supported Streamlabs Desktop sources, including display/monitor sources placed without a screen mapping. Known Streamlabs filters (chroma key, color key, color correction, crop, sharpen, LUT, gain, noise suppression/gate, compressor, limiter, expander, invert, delays, scaling, rotate) are converted to the matching OBS filter type; unknown plugin filters are preserved with their relinked settings. The collection is transactionally published together with the extracted folder; a publish failure rolls back both. **Scale layout to my OBS canvas after import (aspect-preserving)** is enabled by default and fits the imported 16:9 layout uniformly to the active OBS profile's base canvas without stretching. Device sources (webcams, audio, displays, compatible custom devices) are auto-matched to locally configured sources with the same OBS source ID when exactly one candidate exists; unmapped sources are imported unconfigured so the user can set them up in OBS later. If the collection name already exists, it uses `name 1`, then `name 2`, without overwriting a collection. When OBS is open, the utility finishes device matching and then switches to the imported collection through OBS's built-in WebSocket server—no restart or collection reload is needed.

## Export Overlay workflow

1. Open **Export Overlay**.
2. Select an OBS scene collection. The collection currently selected in OBS is preselected when available.
3. Choose an export destination folder.
4. Click **Run**, review the complete file inventory and missing-reference list, then choose **Confirm Export**.

Before writing anything, the utility shows a read-only inventory with every unique file, category, size, total bytes, browser-file count, missing reference, and proposed package path. The utility then creates a Windows-safe package folder named after the collection only after confirmation. It copies direct local files into **images**, **videos**, **audio**, and **other resources**, then writes an OBS-compatible JSON with the copied paths. A local HTML browser overlay is exported as a complete recursive **browser overlays** folder so its relative CSS, JavaScript, fonts, images, and other dependencies remain intact. Browser projects are preflighted with a 10,000-file and 2 GB limit; drive roots, broad personal/system folders, links/reparse points, and export destinations inside the browser project are rejected. The package is assembled in a temporary staging folder and published only after its JSON and resources are complete. It traverses the full collection JSON, including nested plugin-source and filter settings, so existing absolute local files with arbitrary extensions are preserved rather than limiting export to built-in OBS source types. Missing local paths are reported in the console for manual review.

Exporting does not bundle OBS plugins, fonts, device sources, credentials, or web-hosted resources; those must be installed or configured on the destination computer.
## Auto Resizer workflow

1. Open **Auto Resizer** and select the OBS scene collection. OBS's active collection is selected by default when available.
2. Choose **Collection**, **Scene**, or **Source**, then select the specific scene or source when needed. Sources are labeled `Source Name (UUID)`, so duplicate display names remain unambiguous.
3. Choose **Stretch** for separate horizontal and vertical scaling, or **Scale Ratio** to preserve aspect ratio and center the layout.
4. Select **Screen size** to use the active OBS profile's base canvas, or enter a **Custom size**.
5. Click **Run**. The selected collection JSON is overwritten and a backup is created automatically. Click **Undo** to restore the last resize during the current app session.

When the selected collection is active in an open OBS session, Auto Resizer changes scene-item transforms and video settings through OBS's live API. OBS remains open, the result is immediately visible, and Undo restores the in-memory snapshot live. The app refuses to overwrite the active JSON if live control is unavailable. Inactive collections retain the file-based atomic backup workflow under `.obs-overlay-resizer-backups`. Collection scope changes every scene/group item transform and updates the canvas. Scene and Source scopes change only matching scene-item transforms and preserve the existing canvas. Items with active OBS bounds modes resize their bounds without also multiplying source scale; unbounded items resize source scale normally.

## Running tools while OBS is open

OBS Studio 28 and newer includes obs-websocket. Leave **Tools → WebSocket Server Settings → Enable WebSocket server** enabled on the default local port `4455`. If authentication is enabled, the app asks for the password only when live control is needed and keeps it in memory only until the app closes. Method 1 and Export Overlay are always safe while OBS is open. Method 2 activates its imported collection live after device setup. Auto Resizer uses live requests for the active collection and file backups only for inactive collections. If the server is disabled, uses a non-default port, or is unavailable, imports remain installed but cannot be selected automatically; the active collection is never overwritten as a fallback.
## Safety behavior

- Reads only JSON files that look like OBS scene collections.
- Ignores remote URLs, data URLs, unrelated text, and unsupported file types.
- Supports common images, video, audio, SVG, and local HTML files, plus local plugin/script/config/font files (`.lua`, `.py`, `.json`, `.js`, `.ttf`, and similar) referenced from plugin sources and filter settings, so plugin scenes, filters, and scripts keep working after the move.
- Stops when two files are equally plausible rather than guessing.
- Requires every referenced local file by default.
- Writes through a temporary file and atomically renames it.
- Never overwrites an earlier converted file.
- Follows neither directory symlinks nor generated/build folders while scanning.
- Validates Streamlabs ZIP paths (including Windows backslash traversal), duplicate entries, links/special files, encryption, entry count, per-file and total size, compression ratio, and available disk space before extraction.
- Streamlabs imports use a new OBS collection name and never overwrite an existing collection file.
- Export creates a new package folder and never edits the source OBS collection or overwrites an earlier package.
- Browser-overlay export is bounded, rejects broad or recursively nested roots, skips links and Windows reparse points, and leaves no partial package after failure.
- Device setup requires the exact OBS source ID and copies only recognized device-selector values.
- Scene/source resize scopes preserve the global collection canvas; only Collection scope changes it.
- Auto Resizer writes only after creating an undo backup; Undo restores the most recent resize made in the current application session.
- Live OBS passwords are never saved in settings or written to logs.

## Run from source

Python 3.10 or newer is required.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m obs_overlay_import_utility
```

Run the automated checks:

```powershell
python -m unittest discover -s tests -v
```

Build the portable Windows executable:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_portable.ps1
```

The executable will be written to `dist\OBS Overlay Import Utility.exe`.

## GitHub and releases

See [docs/GITHUB_SYNC.md](docs/GITHUB_SYNC.md) for the first push, normal daily syncing, cloning on another computer, and publishing a tagged build. GitHub Actions tests every push and can build the Windows executable.

Before publishing, replace `YOUR-GITHUB-USERNAME` in `pyproject.toml` with your GitHub username.

## Limitations

- The application fixes local file references; it does not install fonts or OBS plugins.
- A public executable is unsigned, so Windows SmartScreen may show an unrecognized-app warning until the project gains reputation or the executable is code-signed.
- Customers should keep the extracted overlay folder in place after importing because OBS continues to load media from those paths.
- Streamlabs webcam/device IDs and service labels are not portable. The setup wizard can reuse matching exact-type devices from local OBS collections; unmatched sources still need manual OBS configuration.

## License

MIT. You can use, modify, and distribute the utility, including with commercial overlay packages. See [LICENSE](LICENSE).
