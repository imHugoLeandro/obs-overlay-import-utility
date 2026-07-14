# OBS Overlay Import Utility

A small, open-source Windows desktop utility that imports and exports portable OBS overlay packages. It is designed for independent overlay creators who want customers to import a package without manually finding and replacing every image, video, audio, local browser-source, plugin, or filter resource path.

The portable build has no installer and does not require Python.

The Settings page supports the Windows default, white, and dark themes; adjustable UI scaling; remembered overlay folders; import defaults; and optional custom OBS/Python locations. Settings are saved per Windows user in `%APPDATA%\OBS Overlay Import Utility\settings.json`.

## Customer workflow

### Method 1 — Fix Scene Collection Paths

1. Expand **Method 1** with its down arrow.
2. Choose the extracted **Overlay Folder path**.
3. Click **Run**. The utility finds the OBS scene collection export automatically.
4. In OBS, open **Scene Collection → Import** and select the new `_ImportReady.json` file.

The original collection is never changed. **Advanced options** is collapsed by default and contains the enabled-by-default strict file check and case-sensitive matching option.

### Method 2 — Import Streamlabs Scene File

1. Expand **Method 2** with its down arrow.
2. Choose the Streamlabs `.overlay` package.
3. Click **Run** in the same Import Overlay window.

The utility validates the archive before extraction (including entry, per-file, total-size, compression-ratio, path, link, encryption, duplicate-name, and free-space limits), then extracts beside the archive into a new `name overlay` folder. It recursively relinks assets in built-in and custom/plugin source and filter settings, converts supported Streamlabs Desktop sources, and transactionally publishes the extracted folder together with a new OBS collection. A publish failure rolls back the extracted folder and pending JSON. **Run device setup wizard after import** is enabled by default: when the package contains camera, audio, display, capture, or compatible custom device sources, a setup window lets the user map them only to locally configured sources with the same OBS source ID. The wizard copies device-selector fields while preserving the imported resolution, FPS, filters, source type, and other settings. It reads the active OBS profile and sizes the collection to that profile's base canvas. If that name already exists, it uses `name 1`, then `name 2`, without overwriting a collection. Restart OBS if it was already open, then select the new collection from **Scene Collection**.

### Method 3 — Automatic Scene Collection

1. Expand **Method 3** with its down arrow.
2. Choose the folder containing the scene collection pack.
3. Click **Run**.

The utility recursively searches the selected folder for all supported pack files and asset folders. **Run device setup wizard after import** is enabled by default and appears only when the detected collection includes device sources that can be mapped locally. It prioritizes exactly one OBS scene collection export when both that export and a Streamlabs `.overlay` package are present; otherwise it uses exactly one `.overlay` package. It matches local assets safely, sizes the imported collection to the active OBS profile's base canvas, installs it without overwriting an existing collection, and reports what it detected. If several candidates of the preferred format are found, it stops safely and asks you to use the specific method instead.

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

Auto Resizer can write while OBS is open. If the edited collection is already active, switch to another collection and back, or restart OBS, so OBS reloads the changed file. Backups are stored under `.obs-overlay-resizer-backups` beside OBS's scene-collection folder. Collection scope changes every scene-item transform and updates the collection canvas. Scene and Source scopes change only the selected scene-item transforms and preserve the existing canvas. Automatic import resizing also traverses only real OBS scene/group items, so similarly named fields inside custom plugin settings remain untouched. Items with active OBS bounds modes resize their bounds without also multiplying source scale; unbounded items resize source scale normally.
## Safety behavior

- Reads only JSON files that look like OBS scene collections.
- Ignores remote URLs, data URLs, unrelated text, and unsupported file types.
- Supports common images, video, audio, SVG, and local HTML files.
- Stops when two files are equally plausible rather than guessing.
- Requires every referenced local file by default.
- Writes through a temporary file and atomically renames it.
- Never overwrites an earlier converted file.
- Follows neither directory symlinks nor generated/build folders while scanning.
- Validates Streamlabs ZIP paths (including Windows backslash traversal), duplicate entries, links/special files, encryption, entry count, per-file and total size, compression ratio, and available disk space before extraction.
- Streamlabs and automatic imports use a new OBS collection name and never overwrite an existing collection file.
- Export creates a new package folder and never edits the source OBS collection or overwrites an earlier package.
- Browser-overlay export is bounded, rejects broad or recursively nested roots, skips links and Windows reparse points, and leaves no partial package after failure.
- Device setup requires the exact OBS source ID and copies only recognized device-selector values.
- Scene/source resize scopes preserve the global collection canvas; only Collection scope changes it.
- Auto Resizer writes only after creating an undo backup; Undo restores the most recent resize made in the current application session.

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
