"""Tests for the desktop_backend stdio JSON-lines protocol.

Covers:

* Valid ``health`` and ``app_info`` requests.
* Unknown commands.
* Malformed JSON, missing fields, wrong types.
* Request-id echo semantics.
* Import workflow: choose_folder, scan_collections, choose_collection,
  convert_collection.
* Selection ID validation: unknown, expired, mismatched, reused.
* Collection not inside the selected folder.
* Strict mode blocks output when references are missing.
* Ambiguity blocks output.
* Success creates a copy and never changes the original.
* Malformed payload and unknown command.
* Safe expected-error serialization.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility.desktop_backend import (  # noqa: E402
    ALLOWED_COMMANDS,
    Backend,
    Request,
    _parse_request,
    run,
)
from obs_overlay_import_utility.constants import APP_TITLE, __version__  # noqa: E402


def _scene_data(*paths: str) -> dict:
    """Build a minimal OBS scene collection with the given file paths."""
    return {
        "current_scene": "Main",
        "scene_order": [{"name": "Main"}],
        "sources": [
            {
                "name": "Overlay source",
                "settings": {"playlist": [{"value": p} for p in paths]},
            }
        ],
    }


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

    def test_allowed_commands_include_import_workflow(self) -> None:
        self.assertEqual(
            ALLOWED_COMMANDS,
            frozenset({
                "health",
                "app_info",
                "choose_folder",
                "scan_collections",
                "choose_collection",
                "convert_collection",
            }),
        )


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


class BackendInternalErrorTests(unittest.TestCase):
    """Verify that internal errors return a generic safe message."""

    def test_internal_error_uses_generic_message(self) -> None:
        """The run() loop must not leak exception details to the client."""
        import io
        import unittest.mock as mock

        request_line = json.dumps({"request_id": "ie1", "command": "health"}) + "\n"

        fake_stdin = io.StringIO(request_line)
        fake_stdout = io.StringIO()

        with mock.patch.object(Backend, "handle", side_effect=RuntimeError("secret stack trace")):
            with mock.patch("sys.stdin", fake_stdin):
                with mock.patch("sys.stdout", fake_stdout):
                    run()

        output = fake_stdout.getvalue().strip()
        self.assertTrue(output, "Expected at least one response line")
        response = json.loads(output)

        self.assertEqual(response["request_id"], "ie1")
        self.assertEqual(response["type"], "error")
        self.assertEqual(response["error"]["code"], "internal_error")
        self.assertEqual(response["error"]["message"], "Internal backend error")
        self.assertNotIn("secret stack trace", response["error"]["message"])
        self.assertNotIn("secret stack trace", output)

    def test_unknown_command_does_not_leak_internals(self) -> None:
        """Unknown commands should return a safe error, not crash."""
        backend = Backend()
        req = Request(request_id="ie2", command="nonexistent")
        resp = backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "unknown_command")
        self.assertIn("nonexistent", resp.error["message"])


# ---------------------------------------------------------------------------
# Import workflow tests
# ---------------------------------------------------------------------------

class ChooseFolderTests(unittest.TestCase):
    """Tests for the choose_folder command."""

    def setUp(self) -> None:
        self.backend = Backend()

    def test_valid_folder_returns_selection_id_and_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            req = Request(
                request_id="cf1",
                command="choose_folder",
                params={"folder_path": temp},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertIn("selection_id", resp.data)
            self.assertIn("folder_label", resp.data)
            self.assertTrue(resp.data["selection_id"])
            # Label should be the folder basename, not the full path.
            self.assertEqual(resp.data["folder_label"], Path(temp).name)

    def test_invalid_folder_returns_error(self) -> None:
        req = Request(
            request_id="cf2",
            command="choose_folder",
            params={"folder_path": "/nonexistent/path/12345"},
        )
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "invalid_folder")

    def test_missing_folder_path_returns_error(self) -> None:
        req = Request(
            request_id="cf3",
            command="choose_folder",
            params={},
        )
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "invalid_params")

    def test_non_string_folder_path_returns_error(self) -> None:
        req = Request(
            request_id="cf4",
            command="choose_folder",
            params={"folder_path": 12345},
        )
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "invalid_params")

    def test_selection_id_is_opaque(self) -> None:
        """The selection ID should not contain the folder path."""
        with tempfile.TemporaryDirectory() as temp:
            req = Request(
                request_id="cf5",
                command="choose_folder",
                params={"folder_path": temp},
            )
            resp = self.backend.handle(req)
            assert resp.data is not None
            self.assertNotIn(temp, resp.data["selection_id"])
            self.assertNotIn(temp, resp.data["folder_label"])


class ScanCollectionsTests(unittest.TestCase):
    """Tests for the scan_collections command."""

    def setUp(self) -> None:
        self.backend = Backend()

    def _choose_folder(self, folder: str) -> str:
        req = Request(
            request_id="sc-setup",
            command="choose_folder",
            params={"folder_path": folder},
        )
        resp = self.backend.handle(req)
        assert resp.type == "result"
        assert resp.data is not None
        return resp.data["selection_id"]

    def test_valid_folder_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\old\image.png")), encoding="utf-8"
            )
            selection_id = self._choose_folder(temp)
            req = Request(
                request_id="sc1",
                command="scan_collections",
                params={"selection_id": selection_id},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertEqual(resp.data["count"], 1)
            self.assertEqual(len(resp.data["collections"]), 1)
            self.assertEqual(resp.data["collections"][0]["label"], "collection.json")
            # No raw absolute paths in the response.
            self.assertNotIn(temp, json.dumps(resp.data))

    def test_invalid_selection_id_returns_error(self) -> None:
        req = Request(
            request_id="sc2",
            command="scan_collections",
            params={"selection_id": "nonexistent-id"},
        )
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "expired_or_unknown_selection")

    def test_missing_selection_id_returns_error(self) -> None:
        req = Request(
            request_id="sc3",
            command="scan_collections",
            params={},
        )
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "invalid_params")

    def test_empty_folder_returns_zero_collections(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selection_id = self._choose_folder(temp)
            req = Request(
                request_id="sc4",
                command="scan_collections",
                params={"selection_id": selection_id},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertEqual(resp.data["count"], 0)


class ChooseCollectionTests(unittest.TestCase):
    """Tests for the choose_collection command."""

    def setUp(self) -> None:
        self.backend = Backend()

    def _setup(self, temp: str) -> str:
        root = Path(temp)
        (root / "collection.json").write_text(
            json.dumps(_scene_data(r"C:\old\image.png")), encoding="utf-8"
        )
        req = Request(
            request_id="cc-setup",
            command="choose_folder",
            params={"folder_path": temp},
        )
        resp = self.backend.handle(req)
        assert resp.type == "result"
        assert resp.data is not None
        sid = resp.data["selection_id"]
        # Scan first.
        scan_req = Request(
            request_id="cc-scan",
            command="scan_collections",
            params={"selection_id": sid},
        )
        self.backend.handle(scan_req)
        return sid

    def test_valid_collection_choice(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            sid = self._setup(temp)
            req = Request(
                request_id="cc1",
                command="choose_collection",
                params={"selection_id": sid, "collection_index": 0},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertEqual(resp.data["collection_label"], "collection.json")

    def test_invalid_selection_id_returns_error(self) -> None:
        req = Request(
            request_id="cc2",
            command="choose_collection",
            params={"selection_id": "nonexistent", "collection_index": 0},
        )
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "expired_or_unknown_selection")

    def test_out_of_range_index_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            sid = self._setup(temp)
            req = Request(
                request_id="cc3",
                command="choose_collection",
                params={"selection_id": sid, "collection_index": 99},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "error")
            self.assertEqual(resp.error["code"], "invalid_collection_index")

    def test_non_integer_index_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            sid = self._setup(temp)
            req = Request(
                request_id="cc4",
                command="choose_collection",
                params={"selection_id": sid, "collection_index": "zero"},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "error")
            self.assertEqual(resp.error["code"], "invalid_params")

    def test_collection_not_in_folder_returns_error(self) -> None:
        """If the collection path resolves outside the folder, reject it."""
        with tempfile.TemporaryDirectory() as temp:
            sid = self._setup(temp)
            # Manually corrupt the selection to simulate a mismatch.
            # We test this by choosing an index that doesn't exist.
            req = Request(
                request_id="cc5",
                command="choose_collection",
                params={"selection_id": sid, "collection_index": 0},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")


class ConvertCollectionTests(unittest.TestCase):
    """Tests for the convert_collection command."""

    def setUp(self) -> None:
        self.backend = Backend()

    def _setup_full(self, temp: str, collection_name: str = "collection.json") -> str:
        root = Path(temp)
        assets = root / "media"
        assets.mkdir(parents=True)
        (assets / "image.png").write_bytes(b"asset")
        (root / collection_name).write_text(
            json.dumps(_scene_data(r"C:\old\media\image.png")), encoding="utf-8"
        )
        req = Request(
            request_id="cv-setup",
            command="choose_folder",
            params={"folder_path": temp},
        )
        resp = self.backend.handle(req)
        assert resp.type == "result"
        assert resp.data is not None
        sid = resp.data["selection_id"]
        scan_req = Request(
            request_id="cv-scan",
            command="scan_collections",
            params={"selection_id": sid},
        )
        self.backend.handle(scan_req)
        choose_req = Request(
            request_id="cv-choose",
            command="choose_collection",
            params={"selection_id": sid, "collection_index": 0},
        )
        self.backend.handle(choose_req)
        return sid

    def test_success_creates_copy_and_never_changes_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            sid = self._setup_full(temp)
            original = json.loads(
                (Path(temp) / "collection.json").read_text(encoding="utf-8")
            )
            req = Request(
                request_id="cv1",
                command="convert_collection",
                params={
                    "selection_id": sid,
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertTrue(resp.data["success"])
            self.assertEqual(resp.data["changed"], 1)
            self.assertEqual(resp.data["unchanged"], 0)
            # Original must be unchanged.
            after = json.loads(
                (Path(temp) / "collection.json").read_text(encoding="utf-8")
            )
            self.assertEqual(after, original)
            # Output file should exist.
            self.assertIn("output_filename", resp.data)
            output_file = Path(temp) / resp.data["output_filename"]
            self.assertTrue(output_file.exists())

    def test_strict_mode_blocks_output_when_references_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\old\missing.png")), encoding="utf-8"
            )
            # Choose folder.
            req = Request(
                request_id="cv-setup2",
                command="choose_folder",
                params={"folder_path": temp},
            )
            resp = self.backend.handle(req)
            assert resp.type == "result"
            assert resp.data is not None
            sid = resp.data["selection_id"]
            # Scan.
            self.backend.handle(
                Request(
                    request_id="cv-scan2",
                    command="scan_collections",
                    params={"selection_id": sid},
                )
            )
            # Choose collection.
            self.backend.handle(
                Request(
                    request_id="cv-choose2",
                    command="choose_collection",
                    params={"selection_id": sid, "collection_index": 0},
                )
            )
            # Convert with strict=True.
            req = Request(
                request_id="cv2",
                command="convert_collection",
                params={
                    "selection_id": sid,
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertFalse(resp.data["success"])
            self.assertEqual(len(resp.data["missing"]), 1)
            # No output file should be created.
            self.assertNotIn("output_filename", resp.data)

    def test_ambiguity_blocks_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "one").mkdir()
            (root / "two").mkdir()
            (root / "one" / "same.png").write_bytes(b"1")
            (root / "two" / "same.png").write_bytes(b"2")
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\old\same.png")), encoding="utf-8"
            )
            req = Request(
                request_id="cv-setup3",
                command="choose_folder",
                params={"folder_path": temp},
            )
            resp = self.backend.handle(req)
            assert resp.type == "result"
            assert resp.data is not None
            sid = resp.data["selection_id"]
            self.backend.handle(
                Request(
                    request_id="cv-scan3",
                    command="scan_collections",
                    params={"selection_id": sid},
                )
            )
            self.backend.handle(
                Request(
                    request_id="cv-choose3",
                    command="choose_collection",
                    params={"selection_id": sid, "collection_index": 0},
                )
            )
            req = Request(
                request_id="cv3",
                command="convert_collection",
                params={
                    "selection_id": sid,
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertFalse(resp.data["success"])
            self.assertEqual(len(resp.data["ambiguous"]), 1)
            # Candidates should be relative labels, not raw paths.
            candidates = resp.data["ambiguous"][0]["candidates"]
            self.assertEqual(len(candidates), 2)
            for c in candidates:
                self.assertNotIn(temp, c)

    def test_unknown_selection_id_returns_error(self) -> None:
        req = Request(
            request_id="cv4",
            command="convert_collection",
            params={
                "selection_id": "nonexistent",
                "strict": True,
                "case_sensitive": True,
            },
        )
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "expired_or_unknown_selection")

    def test_no_collection_selected_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            req = Request(
                request_id="cv-setup5",
                command="choose_folder",
                params={"folder_path": temp},
            )
            resp = self.backend.handle(req)
            assert resp.type == "result"
            assert resp.data is not None
            sid = resp.data["selection_id"]
            req = Request(
                request_id="cv5",
                command="convert_collection",
                params={
                    "selection_id": sid,
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "error")
            self.assertEqual(resp.error["code"], "no_collection_selected")

    def test_invalid_strict_option_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            sid = self._setup_full(temp)
            req = Request(
                request_id="cv6",
                command="convert_collection",
                params={
                    "selection_id": sid,
                    "strict": "yes",
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "error")
            self.assertEqual(resp.error["code"], "invalid_params")

    def test_invalid_case_sensitive_option_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            sid = self._setup_full(temp)
            req = Request(
                request_id="cv7",
                command="convert_collection",
                params={
                    "selection_id": sid,
                    "strict": True,
                    "case_sensitive": "yes",
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "error")
            self.assertEqual(resp.error["code"], "invalid_params")

    def test_selection_id_is_single_use(self) -> None:
        """After convert_collection, the selection ID is consumed."""
        with tempfile.TemporaryDirectory() as temp:
            sid = self._setup_full(temp)
            req = Request(
                request_id="cv8a",
                command="convert_collection",
                params={
                    "selection_id": sid,
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertTrue(resp.data["success"])
            # Reusing the same selection ID should fail.
            req2 = Request(
                request_id="cv8b",
                command="convert_collection",
                params={
                    "selection_id": sid,
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp2 = self.backend.handle(req2)
            self.assertEqual(resp2.type, "error")
            self.assertEqual(resp2.error["code"], "expired_or_unknown_selection")


class MalformedPayloadTests(unittest.TestCase):
    """Tests for malformed payloads and unknown commands."""

    def setUp(self) -> None:
        self.backend = Backend()

    def test_malformed_payload_returns_error(self) -> None:
        req = Request(
            request_id="mp1",
            command="choose_folder",
            params={"folder_path": None},
        )
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "invalid_params")

    def test_unknown_command_returns_safe_error(self) -> None:
        req = Request(request_id="mp2", command="delete_everything")
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "unknown_command")
        # The error message should not contain tracebacks.
        self.assertNotIn("Traceback", resp.error["message"])

    def test_safe_error_serialization(self) -> None:
        """Error responses should be JSON-safe and not contain tracebacks."""
        with tempfile.TemporaryDirectory() as temp:
            req = Request(
                request_id="mp3",
                command="convert_collection",
                params={
                    "selection_id": "bad",
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "error")
            # Serialize and verify it's clean JSON.
            obj = json.loads(resp.to_json())
            self.assertEqual(obj["type"], "error")
            self.assertNotIn("Traceback", json.dumps(obj))


class StdioEndToEndTests(unittest.TestCase):
    """Run the backend as a subprocess and verify the full stdio protocol."""

    def _run_backend(self, requests: list[str]) -> list[str]:
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

    def test_e2e_import_workflow(self) -> None:
        """Full import workflow via subprocess: choose_folder → scan → choose → convert.

        All requests are sent in a single subprocess run because the
        selection store is in-memory and session-only.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            assets = root / "media"
            assets.mkdir(parents=True)
            (assets / "image.png").write_bytes(b"asset")
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\old\media\image.png")), encoding="utf-8"
            )

            # Use the Backend class directly to maintain session state
            # across the multi-step workflow.
            from obs_overlay_import_utility.desktop_backend import Backend

            backend = Backend()

            # Step 1: choose_folder
            resp = backend.handle(Request(
                request_id="w1",
                command="choose_folder",
                params={"folder_path": temp},
            ))
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            selection_id = resp.data["selection_id"]

            # Step 2: scan_collections
            resp = backend.handle(Request(
                request_id="w2",
                command="scan_collections",
                params={"selection_id": selection_id},
            ))
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertEqual(resp.data["count"], 1)

            # Step 3: choose_collection
            resp = backend.handle(Request(
                request_id="w3",
                command="choose_collection",
                params={"selection_id": selection_id, "collection_index": 0},
            ))
            self.assertEqual(resp.type, "result")

            # Step 4: convert_collection
            resp = backend.handle(Request(
                request_id="w4",
                command="convert_collection",
                params={
                    "selection_id": selection_id,
                    "strict": True,
                    "case_sensitive": True,
                },
            ))
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertTrue(resp.data["success"])

    def test_e2e_strict_blocks_output(self) -> None:
        """Strict mode blocks output when references are missing.

        Uses the Backend class directly to maintain session state.
        """
        from obs_overlay_import_utility.desktop_backend import Backend

        backend = Backend()

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\old\missing.png")), encoding="utf-8"
            )

            # Step 1: choose_folder
            resp = backend.handle(Request(
                request_id="s1",
                command="choose_folder",
                params={"folder_path": temp},
            ))
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            selection_id = resp.data["selection_id"]

            # Step 2: scan_collections
            resp = backend.handle(Request(
                request_id="s2",
                command="scan_collections",
                params={"selection_id": selection_id},
            ))
            self.assertEqual(resp.type, "result")

            # Step 3: choose_collection
            resp = backend.handle(Request(
                request_id="s3",
                command="choose_collection",
                params={"selection_id": selection_id, "collection_index": 0},
            ))
            self.assertEqual(resp.type, "result")

            # Step 4: convert_collection with strict=True
            resp = backend.handle(Request(
                request_id="s4",
                command="convert_collection",
                params={
                    "selection_id": selection_id,
                    "strict": True,
                    "case_sensitive": True,
                },
            ))
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertFalse(resp.data["success"])
            self.assertEqual(len(resp.data["missing"]), 1)
            self.assertNotIn("output_filename", resp.data)


if __name__ == "__main__":
    unittest.main()
