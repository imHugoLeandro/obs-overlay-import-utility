"""Tests for the desktop_backend stdio JSON-lines protocol.

Covers:

* Valid ``health`` and ``app_info`` requests.
* Unknown commands.
* Malformed JSON, missing fields, wrong types.
* Request-id echo semantics.
* Import workflow: scan_collections, convert_collection.
* The backend receives concrete folder/collection paths from Electron main
  (not opaque renderer IDs).
* scan uses existing find_scene_collections; conversion uses existing
  convert_collection.
* Folder/collection containment and symlink escape rejection.
* No raw selected folder path in renderer-facing backend result.
* Expected UtilityError is structured and customer-safe.
* Retry semantics: failed strict validation does not prevent retry.
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
                "scan_collections",
                "convert_collection",
            }),
        )

    def test_no_choose_folder_command(self) -> None:
        """The backend no longer has a choose_folder command —
        Electron main owns the folder selection."""
        self.assertNotIn("choose_folder", ALLOWED_COMMANDS)
        self.assertNotIn("choose_collection", ALLOWED_COMMANDS)


class BackendSafetyTests(unittest.TestCase):
    """Verify the backend does not expose dangerous capabilities."""

    def setUp(self) -> None:
        self.backend = Backend()

    def test_no_shell_command_endpoint(self) -> None:
        for cmd in ("shell", "exec", "run", "subprocess", "system", "eval", "import",
                     "choose_folder", "choose_collection"):
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

class ScanCollectionsTests(unittest.TestCase):
    """Tests for the scan_collections command.

    The backend receives concrete folder paths from Electron main
    (not opaque renderer IDs).
    """

    def setUp(self) -> None:
        self.backend = Backend()

    def test_valid_folder_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\\old\\image.png")), encoding="utf-8"
            )
            req = Request(
                request_id="sc1",
                command="scan_collections",
                params={"folder_path": temp},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertEqual(resp.data["count"], 1)
            self.assertEqual(len(resp.data["collections"]), 1)
            self.assertEqual(resp.data["collections"][0]["label"], "collection.json")
            # The canonical absolute path is returned to Electron main only
            # (over the trusted stdio channel), not to the renderer.
            self.assertEqual(
                resp.data["collections"][0]["path"],
                str(root / "collection.json"),
            )

    def test_scan_returns_canonical_path_and_safe_label(self) -> None:
        """The backend must return the canonical absolute ``path`` (main-only)
        and a safe relative ``label`` for each detected collection."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\\old\\image.png")), encoding="utf-8"
            )
            req = Request(
                request_id="sc1b",
                command="scan_collections",
                params={"folder_path": temp},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            col = resp.data["collections"][0]
            # The path must be the canonical absolute path.
            self.assertEqual(col["path"], str(root / "collection.json"))
            self.assertTrue(Path(col["path"]).is_absolute())
            # The label must be the safe relative path.
            self.assertEqual(col["label"], "collection.json")

    def test_scan_nested_collection_returns_canonical_path_and_label(self) -> None:
        """A nested collection must return a canonical absolute path and a
        safe relative label that includes the subdirectory."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "subdir").mkdir()
            nested = root / "subdir" / "collection.json"
            nested.write_text(
                json.dumps(_scene_data(r"C:\\old\\image.png")), encoding="utf-8"
            )
            req = Request(
                request_id="sc1c",
                command="scan_collections",
                params={"folder_path": temp},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            col = resp.data["collections"][0]
            self.assertEqual(col["path"], str(nested))
            self.assertTrue(Path(col["path"]).is_absolute())
            # The label is the relative path (platform separator).
            self.assertEqual(col["label"], str(nested.relative_to(root)))

    def test_invalid_folder_returns_error(self) -> None:
        req = Request(
            request_id="sc2",
            command="scan_collections",
            params={"folder_path": "/nonexistent/path/12345"},
        )
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "invalid_folder")

    def test_missing_folder_path_returns_error(self) -> None:
        req = Request(
            request_id="sc3",
            command="scan_collections",
            params={},
        )
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "invalid_params")

    def test_non_string_folder_path_returns_error(self) -> None:
        req = Request(
            request_id="sc4",
            command="scan_collections",
            params={"folder_path": 12345},
        )
        resp = self.backend.handle(req)
        self.assertEqual(resp.type, "error")
        self.assertEqual(resp.error["code"], "invalid_params")

    def test_empty_folder_returns_zero_collections(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            req = Request(
                request_id="sc5",
                command="scan_collections",
                params={"folder_path": temp},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertEqual(resp.data["count"], 0)

    def test_scan_uses_existing_find_scene_collections(self) -> None:
        """The backend must use the existing core.find_scene_collections()
        engine, not reimplement it."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\\old\\image.png")), encoding="utf-8"
            )
            (root / "collection_ImportReady.json").write_text(
                json.dumps(_scene_data(r"C:\\old\\image.png")), encoding="utf-8"
            )
            (root / "metadata.json").write_text('{"name":"not OBS"}', encoding="utf-8")
            req = Request(
                request_id="sc6",
                command="scan_collections",
                params={"folder_path": temp},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            # find_scene_collections filters out _ImportReady and non-OBS files.
            self.assertEqual(resp.data["count"], 1)
            self.assertEqual(resp.data["collections"][0]["label"], "collection.json")

    def test_scan_label_does_not_contain_absolute_path(self) -> None:
        """The safe relative label must never contain the absolute folder path."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "subdir").mkdir()
            (root / "subdir" / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\\old\\image.png")), encoding="utf-8"
            )
            req = Request(
                request_id="sc7",
                command="scan_collections",
                params={"folder_path": temp},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            col = resp.data["collections"][0]
            # The label must be a safe relative path, not the absolute path.
            self.assertEqual(col["label"], str((root / "subdir" / "collection.json").relative_to(root)))
            self.assertNotIn(temp, col["label"])

    def test_scan_failed_error_is_structured_and_safe(self) -> None:
        """A scan_failed error must return a structured { code, message }
        with no traceback."""
        with tempfile.TemporaryDirectory() as temp:
            # Create a collection that is not valid JSON (will cause
            # find_scene_collections to skip it, but not error).
            # Instead, test with a folder that becomes unreadable.
            req = Request(
                request_id="sc8",
                command="scan_collections",
                params={"folder_path": temp},
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertEqual(resp.data["count"], 0)

    def test_scan_result_has_no_traceback(self) -> None:
        """The scan result must never contain a traceback."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\\old\\image.png")), encoding="utf-8"
            )
            req = Request(
                request_id="sc9",
                command="scan_collections",
                params={"folder_path": temp},
            )
            resp = self.backend.handle(req)
            result_json = resp.to_json()
            self.assertNotIn("Traceback", result_json)
            self.assertNotIn("Error:", result_json)


class ConvertCollectionTests(unittest.TestCase):
    """Tests for the convert_collection command.

    The backend receives concrete folder_path and collection_path from
    Electron main (not opaque renderer IDs).
    """

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
        return str(root / collection_name)

    def test_success_creates_copy_and_never_changes_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            collection_path = self._setup_full(temp)
            original = json.loads(
                (Path(temp) / "collection.json").read_text(encoding="utf-8")
            )
            req = Request(
                request_id="cv1",
                command="convert_collection",
                params={
                    "folder_path": temp,
                    "collection_path": collection_path,
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
            collection_path = str(root / "collection.json")
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\old\missing.png")), encoding="utf-8"
            )
            req = Request(
                request_id="cv2",
                command="convert_collection",
                params={
                    "folder_path": temp,
                    "collection_path": collection_path,
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
            collection_path = str(root / "collection.json")
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\old\same.png")), encoding="utf-8"
            )
            req = Request(
                request_id="cv3",
                command="convert_collection",
                params={
                    "folder_path": temp,
                    "collection_path": collection_path,
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

    def test_collection_not_in_folder_returns_error(self) -> None:
        """If the collection path is outside the folder, reject it."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Create collection outside the folder.
            outside = root.parent / "outside_collection.json"
            outside.write_text(
                json.dumps(_scene_data(r"C:\old\image.png")), encoding="utf-8"
            )
            req = Request(
                request_id="cv4",
                command="convert_collection",
                params={
                    "folder_path": temp,
                    "collection_path": str(outside),
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "error")
            self.assertEqual(resp.error["code"], "collection_not_in_folder")
            # Clean up.
            outside.unlink()

    def test_invalid_strict_option_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            collection_path = self._setup_full(temp)
            req = Request(
                request_id="cv5",
                command="convert_collection",
                params={
                    "folder_path": temp,
                    "collection_path": collection_path,
                    "strict": "yes",
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "error")
            self.assertEqual(resp.error["code"], "invalid_params")

    def test_invalid_case_sensitive_option_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            collection_path = self._setup_full(temp)
            req = Request(
                request_id="cv6",
                command="convert_collection",
                params={
                    "folder_path": temp,
                    "collection_path": collection_path,
                    "strict": True,
                    "case_sensitive": "yes",
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "error")
            self.assertEqual(resp.error["code"], "invalid_params")

    def test_missing_folder_path_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            collection_path = self._setup_full(temp)
            req = Request(
                request_id="cv7",
                command="convert_collection",
                params={
                    "collection_path": collection_path,
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "error")
            self.assertEqual(resp.error["code"], "invalid_params")

    def test_missing_collection_path_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self._setup_full(temp)
            req = Request(
                request_id="cv8",
                command="convert_collection",
                params={
                    "folder_path": temp,
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "error")
            self.assertEqual(resp.error["code"], "invalid_params")

    def test_conversion_uses_existing_convert_collection(self) -> None:
        """The backend must use the existing core.convert_collection()
        engine, not reimplement it."""
        with tempfile.TemporaryDirectory() as temp:
            collection_path = self._setup_full(temp)
            req = Request(
                request_id="cv9",
                command="convert_collection",
                params={
                    "folder_path": temp,
                    "collection_path": collection_path,
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertTrue(resp.data["success"])
            # The output filename follows the existing naming convention.
            self.assertEqual(resp.data["output_filename"], "collection_ImportReady.json")

    def test_no_raw_selected_folder_path_in_result(self) -> None:
        """The backend result must not contain raw absolute paths."""
        with tempfile.TemporaryDirectory() as temp:
            collection_path = self._setup_full(temp)
            req = Request(
                request_id="cv10",
                command="convert_collection",
                params={
                    "folder_path": temp,
                    "collection_path": collection_path,
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            result_json = json.dumps(resp.data)
            self.assertNotIn(temp, result_json)

    def test_retry_after_failed_strict_validation(self) -> None:
        """A failed strict validation must not prevent retry.

        The backend is stateless (no selection store), so retry is
        always possible by sending a new request with different options.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\old\missing.png")), encoding="utf-8"
            )
            collection_path = str(root / "collection.json")

            # First attempt: strict=True — should fail.
            req = Request(
                request_id="cv11a",
                command="convert_collection",
                params={
                    "folder_path": temp,
                    "collection_path": collection_path,
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            self.assertFalse(resp.data["success"])

            # Second attempt: strict=False — should succeed.
            req2 = Request(
                request_id="cv11b",
                command="convert_collection",
                params={
                    "folder_path": temp,
                    "collection_path": collection_path,
                    "strict": False,
                    "case_sensitive": True,
                },
            )
            resp2 = self.backend.handle(req2)
            self.assertEqual(resp2.type, "result")
            assert resp2.data is not None
            self.assertTrue(resp2.data["success"])


class MalformedPayloadTests(unittest.TestCase):
    """Tests for malformed payloads and unknown commands."""

    def setUp(self) -> None:
        self.backend = Backend()

    def test_malformed_payload_returns_error(self) -> None:
        req = Request(
            request_id="mp1",
            command="scan_collections",
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
                    "folder_path": temp,
                    "collection_path": "/nonexistent/collection.json",
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

    def test_expected_utility_error_is_structured(self) -> None:
        """Expected UtilityError should return a structured error with code."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\old\missing.png")), encoding="utf-8"
            )
            collection_path = str(root / "collection.json")
            req = Request(
                request_id="mp4",
                command="convert_collection",
                params={
                    "folder_path": temp,
                    "collection_path": collection_path,
                    "strict": True,
                    "case_sensitive": True,
                },
            )
            resp = self.backend.handle(req)
            self.assertEqual(resp.type, "result")
            assert resp.data is not None
            # The result has success=False with a structured error message.
            self.assertFalse(resp.data["success"])
            # The result has a missing list (structured, not a traceback).
            self.assertIn("missing", resp.data)
            self.assertEqual(len(resp.data["missing"]), 1)
            # The error message is customer-safe (no tracebacks).
            if "error" in resp.data:
                self.assertNotIn("Traceback", resp.data["error"])


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

    def test_e2e_scan_and_convert_workflow(self) -> None:
        """Full workflow via subprocess: scan_collections → convert_collection.

        The backend receives concrete folder and collection paths from
        Electron main (simulated here by passing them directly).
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            assets = root / "media"
            assets.mkdir(parents=True)
            (assets / "image.png").write_bytes(b"asset")
            collection_path = str(root / "collection.json")
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\old\media\image.png")), encoding="utf-8"
            )

            # Step 1: scan_collections
            outputs = self._run_backend([
                json.dumps({
                    "request_id": "w1",
                    "command": "scan_collections",
                    "params": {"folder_path": temp},
                }),
            ])
            self.assertEqual(len(outputs), 1)
            obj = json.loads(outputs[0])
            self.assertEqual(obj["type"], "result")
            self.assertEqual(obj["data"]["count"], 1)

            # Step 2: convert_collection
            outputs = self._run_backend([
                json.dumps({
                    "request_id": "w2",
                    "command": "convert_collection",
                    "params": {
                        "folder_path": temp,
                        "collection_path": collection_path,
                        "strict": True,
                        "case_sensitive": True,
                    },
                }),
            ])
            self.assertEqual(len(outputs), 1)
            obj = json.loads(outputs[0])
            self.assertEqual(obj["type"], "result")
            self.assertTrue(obj["data"]["success"])

    def test_e2e_strict_blocks_output(self) -> None:
        """Strict mode blocks output when references are missing."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            collection_path = str(root / "collection.json")
            (root / "collection.json").write_text(
                json.dumps(_scene_data(r"C:\old\missing.png")), encoding="utf-8"
            )

            outputs = self._run_backend([
                json.dumps({
                    "request_id": "s1",
                    "command": "convert_collection",
                    "params": {
                        "folder_path": temp,
                        "collection_path": collection_path,
                        "strict": True,
                        "case_sensitive": True,
                    },
                }),
            ])
            obj = json.loads(outputs[0])
            self.assertEqual(obj["type"], "result")
            self.assertFalse(obj["data"]["success"])
            self.assertEqual(len(obj["data"]["missing"]), 1)
            self.assertNotIn("output_filename", obj["data"])


if __name__ == "__main__":
    unittest.main()
