# Changelog

## Unreleased
- Enlarged vertical scrollbars to approximately 28 px at 100% zoom (ranging 21-42 px from 75-150% zoom) with DPI-aware scaling, and introduced a centralized ``ScrollbarMetrics`` helper shared by main pages and dialogs.
- Replaced the Settings UI-size slider (formerly a thin ttk ``Scale``) with a DPI-aware classic ``tk.Scale`` using a centralized ``UiScaleMetrics`` helper, approximately doubling its visible height (32 px at 100% zoom).
- Reduced checkbox and radio-button indicator size by approximately 20% for a cleaner visual appearance.
- Added dependency-free obs-websocket 5.x live control for OBS 28+, with session-only password authentication.
- Streamlabs and Automatic imports now finish device setup and activate the new collection in an open OBS session without a restart.
- Auto Resizer now changes and undoes active collection transforms directly through OBS; it refuses unsafe active-JSON fallback writes when live control is unavailable.
- Removed restart/reload guidance and added live-protocol/authentication regression coverage.
- Rebuilt the interface as a responsive lightweight ttk shell with left-side navigation, modern cards, semantic red primary actions, centralized typography, accessible light/dark palettes, and styled consoles/dialogs.
- Added a dependency-free DPI layer plus an embedded Windows Per-Monitor V2 manifest so the portable executable remains sharp across high-DPI and mixed-monitor setups.
- Added monitor-DPI watching, bounded initial window sizing, system light/dark detection, sharper high-resolution logo scaling, and portable font fallbacks.
- Added UI regression tests for palette contrast, DPI manifest/build integration, system-theme selection, and the dependency-free runtime guarantee.
- Made Streamlabs installation transactional: extracted resources and the OBS collection now publish together, with rollback on collection-publish failure.
- Hardened Streamlabs archives with Windows-path normalization, entry/per-file/total limits, compression-ratio checks, encrypted/special-file rejection, duplicate detection, and free-space preflight.
- Added recursive resource relinking for Streamlabs custom/plugin source and filter settings while preserving remote URLs.
- Added a read-only export inventory and explicit confirmation window showing files, categories, sizes, browser dependencies, missing references, and the final Windows-safe package path.
- Made Auto Resizer source selection UUID-backed and labeled `Source Name (UUID)` so duplicate names resize only the selected source.
- Fixed OBS bounds-aware resizing so active bounds and source scale are not multiplied together.
- Improved the device wizard with explicit read errors, modal behavior, fixed actions, scrolling, and large-list support.
- Removed duplicate resize helpers and added failure-oriented tests for rollback, unsafe archives, disk exhaustion, custom resources, inventory, invalid device collections, and Windows names.

- Fixed browser-overlay exports so broad personal/system roots, recursively nested export destinations, links/reparse points, and projects beyond safe file/size limits are rejected before copying; failed exports now leave no partial package.
- Fixed the device wizard to require exact OBS source-type compatibility and merge only device-selector fields without replacing imported source configuration.
- Fixed Scene and Source resize scopes so they preserve the global collection canvas.
- Fixed automatic import resizing so arbitrary custom plugin settings named `pos`, `scale`, or `bounds` are never transformed.
- Added enabled-by-default post-import device setup for Streamlabs and Automatic imports, mapping camera/audio/display/custom device sources to compatible locally configured OBS sources.
- Added full local browser-overlay packing: HTML browser sources now retain their recursive dependency folders on export.
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
