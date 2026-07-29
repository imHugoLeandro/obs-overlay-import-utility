# Electron Desktop Shell

The Electron + React shell is the primary portable Windows application. It
ships the React renderer, Electron main/preload code, and a bundled Python
JSON-lines backend in one portable EXE. The Tk-based `ui.py` remains a
separately named legacy fallback build; it is not part of this package.

## Overview

This directory contains a parallel Electron-based desktop shell that
communicates with the existing Python engine via a stdio JSON-lines backend.

## Process Boundaries

```
┌─────────────────────────────────────────────────────────┐
│                    Electron Main Process                  │
│                                                           │
│  ┌──────────────┐    ┌──────────────┐    ┌────────────┐ │
│  │  BrowserWindow│    │  IPC Handler  │    │ Python     │ │
│  │  (sandboxed)  │◄──►│  (validated)  │◄──►│ Backend    │ │
│  │               │    │              │    │ (subprocess)│ │
│  └──────────────┘    └──────────────┘    └────────────┘ │
│                                                           │
│  ┌──────────────┐                                        │
│  │  Preload      │                                        │
│  │  (contextBridge)│                                      │
│  └──────────────┘                                        │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    Renderer Process                       │
│  (React + TypeScript, no Electron/Node imports)          │
│  ┌──────────────┐                                        │
│  │  App.tsx     │                                        │
│  │  (health +   │                                        │
│  │   version)   │                                        │
│  └──────────────┘                                        │
└─────────────────────────────────────────────────────────┘
```

### Key boundaries

| Layer | Responsibility |
|-------|---------------|
| **Main process** (`src/main/index.ts`) | Window management, IPC validation, Python backend lifecycle |
| **Preload** (`src/preload/index.ts`) | Exposes typed `electronAPI` via `contextBridge` |
| **Renderer** (`src/renderer/`) | React UI — never imports Electron, Node, filesystem, child_process, or IPC directly |
| **Python backend** (`desktop_backend.py`) | Stdio JSON-lines protocol for the supported import, export, resize, and health operations |

## Health/status API example

The renderer can call the typed, fixed methods on `window.electronAPI`,
including health/app-info and the supported import, export, and resize
workflows. It never receives raw filesystem, Node, or Electron access. For
example, its health/status methods are:

```typescript
window.electronAPI.health()    // → Promise<{ status, pid, uptime_seconds, python_version }>
window.electronAPI.appInfo()   // → Promise<{ name, version }>
```

**Not available** (by design):

- No shell command endpoint
- No arbitrary file-read endpoint
- No generic function-call endpoint
- No direct access to `ipcRenderer`, `fs`, `child_process`, or Node APIs

## Security Rules

1. **`nodeIntegration: false`** — The renderer cannot access Node.js APIs.
2. **`contextIsolation: true`** — The preload runs in an isolated context.
3. **`sandbox: true`** — The renderer runs in a sandboxed renderer process.
4. **`webSecurity: true`** — Standard web security is enforced.
5. **`webviewTag: false`** — No `<webview>` tags.
6. **Navigation blocked** — Unexpected navigation and new windows are denied.
7. **Permission requests denied** — No arbitrary permission grants.
8. **CSP restricted** — Production CSP restricts content to the packaged app.
   Development CSP includes the Vite HMR WebSocket source.
9. **IPC validation** — Every IPC sender, channel, and payload is validated
   in the main process before forwarding to the Python backend.
10. **Fixed IPC channels** — Uses `desktop:health` and `desktop:app-info`
    via `ipcMain.handle`/`ipcRenderer.invoke`. No dynamic channels.
11. **No remote content** — The app never loads remote URLs or remote content.

## Development Commands

### Prerequisites

- Node.js >= 20
- npm >= 10
- Python 3 (set via `OBS_OVERLAY_PYTHON` environment variable)

### Linux / macOS

```bash
# Set the Python executable
export OBS_OVERLAY_PYTHON=$(which python3)

# Install dependencies
cd desktop
npm ci

# Development (renderer + Electron with hot reload)
npm run dev

# Build all development artifacts (renderer + Electron main/preload)
npm run build

# Type checking
npm run typecheck

# Run tests
npm test

# Lint
npm run lint
```

### Windows (PowerShell)

```powershell
# Set the Python executable
$env:OBS_OVERLAY_PYTHON = (Get-Command python).Source

# Install dependencies
cd desktop
npm ci

# Development
npm run dev

# Build
npm run build

# Type checking
npm run typecheck

# Run tests
npm test

# Lint
npm run lint
```

## Project Structure

```
desktop/
├── package.json           # Dependencies and scripts
├── tsconfig.json          # TypeScript config (renderer + tests)
├── tsconfig.electron.json # TypeScript config (Electron main + preload)
├── vite.config.ts         # Vite build/dev server config
├── eslint.config.js       # ESLint configuration
├── .prettierrc.json       # Prettier configuration
├── README.md              # This file
├── src/
│   ├── main/
│   │   └── index.ts       # Electron main process
│   ├── preload/
│   │   └── index.ts       # Preload script (contextBridge)
│   ├── renderer/
│   │   ├── index.html     # HTML entry point
│   │   ├── main.tsx       # React entry point
│   │   ├── App.tsx        # Foundation shell component
│   │   ├── index.css      # Base styles
│   │   └── App.css        # Component styles
│   └── types/
│       └── api.ts         # Shared type definitions
├── tests/
│   ├── setup.ts           # Vitest setup (mock electronAPI)
│   ├── preload.test.ts    # Preload IPC transport tests
│   └── renderer.test.tsx  # Renderer component tests
├── dist/                  # Renderer build output (gitignored)
└── dist-electron/         # Electron main/preload build output (gitignored)
```

## Python Backend

The backend is located at:

```
src/obs_overlay_import_utility/desktop_backend.py
```

It implements a fixed, validated stdio JSON-lines protocol for health,
import, export, and resize operations. Its health/status commands include:

- **`health`** — Returns backend liveness and process metadata.
- **`app_info`** — Returns the application name and version.

### Protocol

**Request** (one JSON object per line on stdin):

```json
{"request_id": "req-123", "command": "health"}
```

**Success response** (one JSON object per line on stdout):

```json
{"request_id": "req-123", "type": "result", "data": {"status": "ok", ...}}
```

**Error response**:

```json
{"request_id": "req-123", "type": "error", "error": {"code": "unknown_command", "message": "..."}}
```

### Backend startup and packaging

In development, Electron starts the source backend only through the
`OBS_OVERLAY_PYTHON` environment variable and adds the repository `src/`
directory to `PYTHONPATH`.

In packaged mode, Electron loads `dist/index.html` with `loadFile()` and
starts only `obs-overlay-backend.exe` from `process.resourcesPath`. It does
not use a system Python, Node, source-tree path, `process.execPath`,
`tools/launcher.py`, or `ui.py`.

### Primary Windows portable build

From the repository root, run the one supported primary build command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_portable_electron.ps1
```

It creates:

```text
desktop\release\OBS Overlay Import Utility Electron Portable.exe
```

`npm run package` is the lower-level command used by that script and CI.
The legacy Tk fallback is built only with
`scripts\build_portable_tk.ps1`; the compatibility
`scripts\build_portable.ps1` redirects to that fallback script.
