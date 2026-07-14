from __future__ import annotations

import base64
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility.obs_live import ObsWebSocketClient  # noqa: E402


class FakeSocket:
    def __init__(self, payload: bytes) -> None:
        self.payload = bytearray(payload)

    def recv(self, size: int) -> bytes:
        result = bytes(self.payload[:size])
        del self.payload[:size]
        return result


class ObsLiveTests(unittest.TestCase):
    def test_authentication_matches_official_sha256_sequence(self) -> None:
        password, salt, challenge = "secret", "salt", "challenge"
        secret = base64.b64encode(
            hashlib.sha256((password + salt).encode()).digest()
        ).decode()
        expected = base64.b64encode(
            hashlib.sha256((secret + challenge).encode()).digest()
        ).decode()

        self.assertEqual(
            ObsWebSocketClient._auth(password, salt, challenge), expected
        )

    def test_receive_buffer_preserves_bytes_after_http_upgrade(self) -> None:
        client = ObsWebSocketClient()
        client.socket = FakeSocket(b"tail")  # type: ignore[assignment]
        client._buffer.extend(b"head")

        self.assertEqual(client._read_exact(6), b"headta")
        self.assertEqual(client._read_exact(2), b"il")


if __name__ == "__main__":
    unittest.main()
