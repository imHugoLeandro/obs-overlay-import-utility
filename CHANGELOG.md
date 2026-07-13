# Changelog

## Unreleased

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
