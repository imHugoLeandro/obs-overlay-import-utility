# Changelog

## Unreleased

- Added Auto Resizer with collection, scene, and source scopes; Stretch or Scale Ratio modes; active-profile or custom target sizes; in-window logs; and undoable overwrite backups.
- Added Export Overlay: selects OBS's active scene collection by default, packages referenced local resources into organized folders, rewrites paths in an OBS JSON export, and retains custom plugin/filter configuration.
- Reworked Import Overlay into three expandable in-window methods with a shared Run button and console output; Method 1 now auto-detects the OBS export from the selected folder.

- Added a dedicated Streamlabs .overlay import workflow that extracts and recursively matches package assets safely, sizes scenes to the active OBS profile, converts supported sources, and installs a uniquely named OBS scene collection.
- Added Automatic Scene Collection, which recursively detects supported pack files, prioritizes OBS exports over Streamlabs packages, sizes imports to the active OBS profile, and installs the result safely.
- Added top-level tool navigation for Import Overlay, Export Overlay, Auto Resizer, and Settings.
- Added placeholder pages for Export Overlay and Auto Resizer while keeping Import Overlay fully functional.
- Added the Social Space logo to the tool bar.
- Added persistent system/light/dark themes and adjustable 75–150% UI scaling.
- Added automatic or custom OBS paths, optional custom Python, remembered folders, and import behavior settings.
- Changed UI scaling to resize controls, text, fields, spacing, and the logo without resizing the application window.
- Reduced the default logo to half its previous size and improved dark-theme control contrast with red accents.
- Fixed Windows CI assertions for long versus 8.3 temporary paths and updated GitHub Actions runtimes.

## 2.0.0 — 2026-07-13

- Rebuilt the utility as a standalone, portable Tkinter application.
- Added validated scene-collection discovery and cross-platform path handling.
- Added conservative duplicate detection, strict missing-file checks, and atomic output.
- Added automated tests, reproducible build tooling, and GitHub Actions workflows.
- Added open-source documentation and an MIT license.
