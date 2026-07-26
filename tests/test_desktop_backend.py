"""Tests for the desktop_backend stdio JSON-lines protocol.

Covers:

* Valid ``health`` and ``app_info`` requests.
* Unknown commands.
* Malformed JSON, missing fields, wrong types.
* Request-id echo semantics.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility.desktop_backend import (  # noqa: E402
    ALLOWED_COMMANDS,
    Backend,
    Request,
    _parse_request,
)
from obs_overlay_import_utility.constants import APP_TITLE, __version__  # noqa: E402


class ParseRequestTests(unittest.TestCase):
    def test_parses_valid_request(self) -> None:
        req = _parse_request('{"request_id":"r1","command":"health"}')
        assert req is not None
        self.assertEqual(req.request_id, "r1")
        self.assertEqual(req.command, "health")
        self.assertEqual(req.params, {})

    def test_parses_request_with_params(self) -> None:
        req = _parse_request(
            '{"request_id":"r2","command":"app_info","params":{"foo":"bar"}}'
        )
        assert req is not None
        self.assertEqual(req.params, {"foo": "bar"})

    def test_blank_line_returns_none(self) -> None:
        self.assertIsNone(_parse_request(""))
        self.assertIsNone(_parse_request("   \n  "))

    def test_invalid_json_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_request("not json")

    def test_non_object_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_request("[1, 2, 3]")

    def test_missing_request_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_request('{"command":"health"}')

    def test_empty_request_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_request('{"request_id":"","command":"health"}')

    def test_missing_command_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_request('{"request_id":"r1"}')

    def test_non_string_request_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_request('{"request_id":123,"command":"health"}')

    def test_non_dict_params_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_request('{"request_id":"r1","command":"health","params":"x"}')


class BackendHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = Backend()

    def test_health_returns_ok(self) -> None:
        req = Request(request_id="h1", command="health")
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "result")
        self.assertEqual(resp.request_id, "h1")
        assert resp.data is not None
        self.assertEqual(resp.data["status"], "ok")
        self.assertIn("pid", resp.data)
        self.assertIn("uptime_seconds", resp.data)
        self.assertIn("python_version", resp.data)

    def test_health_pid_is_current(self) -> None:
        req = Request(request_id="h2", command="health")
        resp = self.backend.handle(req)
        assert resp.data is not None
        self.assertEqual(resp.data["pid"], os.getpid())


class BackendAppInfoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = Backend()

    def test_app_info_returns_name_and_version(self) -> None:
        req = Request(request_id="a1", command="app_info")
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "result")
        assert resp.data is not None
        self.assertEqual(resp.data["name"], APP_TITLE)
        self.assertEqual(resp.data["version"], __version__)


class BackendUnknownCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = Backend()

    def test_unknown_command_returns_error(self) -> None:
        req = Request(request_id="u1", command="rm_rf")
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "unknown_command")
        self.assertIn("rm_rf", resp.error["message"])

    def test_allowed_commands_only_health_and_app_info(self) -> None:
        self.assertEqual(ALLOWED_COMMANDS, frozenset({"health", "app_info"}))


class BackendSafetyTests(unittest.TestCase):
    """Verify the backend does not expose dangerous capabilities."""

    def setUp(self) -> None:
        self.backend = Backend()

    def test_no_shell_command_endpoint(self) -> None:
        for cmd in ("shell", "exec", "run", "subprocess", "system", "eval", "import"):
            req = Request(request_id="s", command=cmd)
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "error", f"Command {cmd!r} should be rejected")
            self.assertEqual(resp.error["code"], "unknown_command")

    def test_no_file_read_endpoint(self) -> None:
        for cmd in ("read_file", "read", "cat", "open", "file", "ls", "list_files"):
            req = Request(request_id="s", command=cmd)
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "error", f"Command {cmd!r} should be rejected")
            self.assertEqual(resp.error["code"], "unknown_command")


class ResponseSerializationTests(unittest.TestCase):
    def test_result_response_serializes(self) -> None:
        from obs_overlay_import_utility.desktop_backend import Response

        resp = Response(
            request_id="r1", type="result", data={"status": "ok"}
        )
        obj = json.loads(resp.to_json())
        self.assertEqual(obj["request_id"], "r1")
        self.assertEqual(obj["type"], "result")
        self.assertEqual(obj["data"], {"status": "ok"})
        self.assertNotIn("error", obj)

    def test_error_response_serializes(self) -> None:
        from obs_overlay_import_utility.desktop_backend import Response

        resp = Response(
            request_id="r2",
            type="error",
            error={"code": "bad", "message": "oops"},
        )
        obj = json.loads(resp.to_json())
        self.assertEqual(obj["request_id"], "r2")
        self.assertEqual(obj["type"], "error")
        self.assertEqual(obj["error"], {"code": "bad", "message": "oops"})
        self.assertNotIn("data", obj)


class StdioEndToEndTests(unittest.TestCase):
    """Run the backend as a subprocess and verify the full stdio protocol."""

    def _run_backend(self, requests: list[str]) -> list[str]:
        """Send JSON lines to the backend subprocess, return output lines."""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        proc = subprocess.run(
            [sys.executable, "-m", "obs_overlay_import_utility.desktop_backend"],
            input="\n".join(requests) + "\n",
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, f"Backend crashed: {proc.stderr}")
        return [line for line in proc.stdout.strip().split("\n") if line]

    def test_e2e_health(self) -> None:
        outputs = self._run_backend(
            ['{"request_id":"e1","command":"health"}']
        )
        self.assertEqual(len(outputs), 1)
        obj = json.loads(outputs[0])
        self.assertEqual(obj["request_id"], "e1")
        self.assertEqual(obj["type"], "result")
        self.assertEqual(obj["data"]["status"], "ok")

    def test_e2e_app_info(self) -> None:
        outputs = self._run_backend(
            ['{"request_id":"e2","command":"app_info"}']
        )
        self.assertEqual(len(outputs), 1)
        obj = json.loads(outputs[0])
        self.assertEqual(obj["request_id"], "e2")
        self.assertEqual(obj["type"], "result")
        self.assertEqual(obj["data"]["name"], APP_TITLE)
        self.assertEqual(obj["data"]["version"], __version__)

    def test_e2e_unknown_command(self) -> None:
        outputs = self._run_backend(
            ['{"request_id":"e3","command":"dangerous"}']
        )
        self.assertEqual(len(outputs), 1)
        obj = json.loads(outputs[0])
        self.assertEqual(obj["request_id"], "e3")
        self.assertEqual(obj["type"], "error")
        self.assertEqual(obj["error"]["code"], "unknown_command")

    def test_e2e_malformed_json(self) -> None:
        outputs = self._run_backend(["not json at all"])
        self.assertEqual(len(outputs), 1)
        obj = json.loads(outputs[0])
        self.assertEqual(obj["type"], "error")
        self.assertEqual(obj["error"]["code"], "malformed_request")

    def test_e2e_multiple_requests_preserve_order(self) -> None:
        outputs = self._run_backend(
            [
                '{"request_id":"m1","command":"health"}',
                '{"request_id":"m2","command":"app_info"}',
                '{"request_id":"m3","command":"health"}',
            ]
        )
        self.assertEqual(len(outputs), 3)
        ids = [json.loads(line)["request_id"] for line in outputs]
        self.assertEqual(ids, ["m1", "m2", "m3"])

    def test_e2e_blank_lines_ignored(self) -> None:
        outputs = self._run_backend(
            [
                "",
                '{"request_id":"b1","command":"health"}',
                "",
                "",
            ]
        )
        self.assertEqual(len(outputs), 1)
        obj = json.loads(outputs[0])
        self.assertEqual(obj["request_id"], "b1")


if __name__ == "__main__":
    unittest.main()
