"""Real backend integration smoke test.

Verifies the actual desktop_backend can process requests via subprocess,
not a copied simulation.  The test starts a real Python subprocess running
the desktop_backend module, sends JSON-line requests over stdin, and reads
structured responses from stdout.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class BackendSmokeTest(unittest.TestCase):
    """Real backend process integration tests."""

    def _start_backend(self) -> subprocess.Popen[bytes]:
        """Start the real desktop_backend as a subprocess."""
        return subprocess.Popen(
            [sys.executable, "-m", "obs_overlay_import_utility.desktop_backend"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=SRC,
            text=False,
        )

    def test_health_returns_ok(self) -> None:
        """Verify the real backend responds to health requests."""
        proc = self._start_backend()
        try:
            assert proc.stdin is not None
            assert proc.stdout is not None
            request = json.dumps({"request_id": "h1", "command": "health"}) + "\n"
            proc.stdin.write(request.encode("utf-8"))
            proc.stdin.flush()
            proc.stdin.close()

            response_line = proc.stdout.readline().decode("utf-8").strip()
            response = json.loads(response_line)

            self.assertEqual(response["request_id"], "h1")
            self.assertEqual(response["type"], "result")
            self.assertIsNotNone(response.get("data"))
            self.assertEqual(response["data"]["status"], "ok")
            self.assertIn("pid", response["data"])
            self.assertIn("python_version", response["data"])
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_app_info_returns_name_version(self) -> None:
        """Verify the real backend responds to app_info requests."""
        proc = self._start_backend()
        try:
            assert proc.stdin is not None
            assert proc.stdout is not None
            request = json.dumps({"request_id": "a1", "command": "app_info"}) + "\n"
            proc.stdin.write(request.encode("utf-8"))
            proc.stdin.flush()
            proc.stdin.close()

            response_line = proc.stdout.readline().decode("utf-8").strip()
            response = json.loads(response_line)

            self.assertEqual(response["request_id"], "a1")
            self.assertEqual(response["type"], "result")
            self.assertIn("name", response["data"])
            self.assertIn("version", response["data"])
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_unknown_command_returns_error(self) -> None:
        """Verify unknown commands are rejected without crashing."""
        proc = self._start_backend()
        try:
            assert proc.stdin is not None
            assert proc.stdout is not None
            request = json.dumps({"request_id": "u1", "command": "rm_rf"}) + "\n"
            proc.stdin.write(request.encode("utf-8"))
            proc.stdin.flush()
            proc.stdin.close()

            response_line = proc.stdout.readline().decode("utf-8").strip()
            response = json.loads(response_line)

            self.assertEqual(response["request_id"], "u1")
            self.assertEqual(response["type"], "error")
            self.assertEqual(response["error"]["code"], "unknown_command")
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_backend_survives_malformed_json(self) -> None:
        """Verify malformed input doesn't crash the backend."""
        proc = self._start_backend()
        try:
            assert proc.stdin is not None
            assert proc.stdout is not None
            proc.stdin.write(b"not valid json\n")
            proc.stdin.write(b'{"request_id": "h2", "command": "health"}\n')
            proc.stdin.flush()
            proc.stdin.close()

            lines = []
            for line in proc.stdout:
                lines.append(line.decode("utf-8").strip())

            self.assertEqual(len(lines), 2)
            first = json.loads(lines[0])
            second = json.loads(lines[1])

            self.assertEqual(first["type"], "error")
            self.assertEqual(first["error"]["code"], "malformed_request")
            self.assertEqual(second["request_id"], "h2")
            self.assertEqual(second["type"], "result")
        finally:
            proc.terminate()
            proc.wait(timeout=5)