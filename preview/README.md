# OBS Overlay Import Utility — UI preview (dev branch)

A functional web demo of the Windows Tk app's UI, used to review and fix the
interface before changes are ported back to `src/obs_overlay_import_utility/ui.py`
and later to an Electron app.

The preview is **Windows-shaped**: same palettes (from `appearance.py`), same
pages/controls, Windows-style paths, system/White/Dark themes, and the app's
75–150% zoom.

## Run

```bash
python serve.py             # http://127.0.0.1:8642/index.html (opens browser)
python serve.py --lan       # also reachable on the LAN (binds 0.0.0.0)
python serve.py --port 9000 # different port
```

Works on Windows and Linux — standard library only.

## What works (simulated)

| Control | Behavior |
| --- | --- |
| Navigation | Switches between Import / Export / Auto Resizer / Settings |
| Import method cards | Expand/collapse with ▸ / ▾; strict checks and case-sensitive matching always enabled |
| Browse… buttons | Real file/folder pickers (demo path shown, real dialogs are Windows-only) |
| Run Import | Simulated scan → detect → relink → install flow, console log, strict-mode block |
| Run Export | Inventory modal → simulated publish + ZIP, console log |
| Run Resize | Scope/target/behavior/size logic, simulated resize, Undo restores backup |
| Theme + zoom | Windows default/White/Dark (system follows OS), 75–150% (settings persist via localStorage) |
| Settings | Save/restore defaults with persistence (demo) |

Everything logged is clearly simulated — the real import/export/resize engine
runs only in the Windows application.

## Regression check

Open `index.html?selftest` in any browser: every flow runs automatically via
dom events and the page renders a **SELFTEST** report (PASS/FAIL per flow,
"ALL GREEN" at the end). Pane webviews throttle background timers heavily
(mock steps take ~3–4 s each), so the suite takes ~1 minute and uses
poll-based asserts — no clicks needed. Re-run `index.html?selftest` after any
UI change and update the pass count in this file.

## Files

- `index.html` — page structure + styles + embedded logo (self-contained)
- `app.js` — all interaction logic (simulated flows)
- `serve.py` — no-cache localhost server