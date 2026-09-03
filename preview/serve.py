"""Serve the OBS Overlay Import Utility UI preview on localhost.

Works on Windows and Linux with only the standard library:

    python serve.py            # http://127.0.0.1:8642/index.html
    python serve.py --lan      # also reachable on the LAN (binds 0.0.0.0)
    python serve.py --port 9000

The preview is a functional UI demo of the Windows Tk app (dev branch).
Real import/export/resize logic runs in the Windows application; here the
buttons drive simulated flows so the UI can be reviewed and fixed before
the changes are ported back to ui.py.
"""

from __future__ import annotations

import argparse
import http.server
import os
import socketserver
import webbrowser

PORT = 8642
PREVIEW_DIR = os.path.dirname(os.path.abspath(__file__))


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """Serve preview files with no caching so edits show immediately."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PREVIEW_DIR, **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class PreviewServer(socketserver.TCPServer):
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument(
        "--lan",
        action="store_true",
        help="bind 0.0.0.0 instead of 127.0.0.1 (exposes the preview on your network)",
    )
    args = parser.parse_args()

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    with PreviewServer((host, args.port), NoCacheHandler) as httpd:
        url = f"http://127.0.0.1:{args.port}/index.html"
        print("OBS Overlay Import Utility - UI preview (dev branch)")
        print(f"  local: {url}")
        if args.lan:
            print(f"  lan:   http://<this-machine-ip>:{args.port}/index.html")
        print("Press Ctrl+C to stop.")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()