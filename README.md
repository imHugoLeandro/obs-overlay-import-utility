# OBS Overlay Import Utility

A small, open-source Windows desktop utility that repairs local file paths in exported OBS scene collections. It is designed for independent overlay creators who want customers to import a package without manually finding and replacing every image, video, audio, or local browser-source path.

The portable build has no installer and does not require Python.

The Settings page supports the Windows default, white, and dark themes; adjustable UI scaling; remembered overlay folders; import defaults; and optional custom OBS/Python locations. Settings are saved per Windows user in `%APPDATA%\OBS Overlay Import Utility\settings.json`.

## Customer workflow

1. Extract the complete overlay download to a normal folder.
2. Run `OBS Overlay Import Utility.exe` from the package.
3. Choose the extracted overlay folder.
4. Select the detected OBS scene collection.
5. Click **Validate and create import file**.
6. In OBS, open **Scene Collection → Import** and select the new `_ImportReady.json` file.

The original collection is never changed. The utility scans the chosen package once, matches files by filename and trailing folders, and creates a separate import-ready JSON only when the match is safe.

## Safety behavior

- Reads only JSON files that look like OBS scene collections.
- Ignores remote URLs, data URLs, unrelated text, and unsupported file types.
- Supports common images, video, audio, SVG, and local HTML files.
- Stops when two files are equally plausible rather than guessing.
- Requires every referenced local file by default.
- Writes through a temporary file and atomically renames it.
- Never overwrites an earlier converted file.
- Follows neither directory symlinks nor generated/build folders while scanning.

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

## License

MIT. You can use, modify, and distribute the utility, including with commercial overlay packages. See [LICENSE](LICENSE).
