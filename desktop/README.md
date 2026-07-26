# Electron Desktop Shell

> **Foundation stage** — This is the initial Electron + React + TypeScript
> foundation for the OBS Overlay Import Utility. The real Import, Export,
> Resizer, and Settings pages are not yet implemented.

## Overview

This directory contains a parallel Electron-based desktop shell that
communicates with the existing Python engine via a stdio JSON-lines backend.
The existing Tk-based `ui.py` and all Python engines remain unchanged and
fully supported.

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
| **Renderer** (`src/renderer/`) | React UI — never imports Electron, Node, or IPC directly |
| **Python backend** (`desktop_backend.py`) | Stdio JSON-lines protocol — `health` and `app_info` only |

## Allowed API Surface

The renderer can call **only** two methods on `window.electronAPI`:

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
5. **`webview` disabled** — No `<webview>` tags.
6. **Navigation blocked** — Unexpected navigation and new windows are denied.
7. **CSP restricted** — Production CSP restricts content to the packaged app.
8. **IPC validation** — Every IPC sender, channel, and payload is validated
   in the main process before forwarding to the Python backend.
9. **No remote content** — The app never loads remote URLs or remote content.

## Development Commands

```bash
# Install dependencies
cd desktop
npm ci

# Development (renderer + Electron with hot reload)
npm run dev

# Type checking
npm run typecheck

# Run tests
npm test

# Build for production
npm run build

# Lint
npm run lint
```

## Project Structure

```
desktop/
├── package.json           # Dependencies and scripts
├── tsconfig.json          # TypeScript configuration
├── vite.config.ts         # Vite build/dev server config
├── .eslintrc.json         # ESLint configuration
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
└── tests/
    ├── setup.ts           # Vitest setup (mock electronAPI)
    ├── preload.test.ts    # Preload IPC transport tests
    └── renderer.test.tsx  # Renderer component tests
```

## Python Backend

The backend is located at:

```
src/obs_overlay_import_utility/desktop_backend.py
```

It implements a minimal stdio JSON-lines protocol with two commands:

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

## Migration Status

This is a **foundation** stage. The Electron shell is being developed in
parallel with the existing Tk-based UI. The Electron shell is **not** the
shipping default — the Tk-based `ui.py` remains the primary interface.

Future stages will add Import, Export, Resizer, and Settings pages to the
Electron shell.
