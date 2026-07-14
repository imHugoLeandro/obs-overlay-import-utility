"""Dependency-free obs-websocket 5.x client for live local OBS control."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import struct
import subprocess
import uuid
from pathlib import Path
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4455
MAX_MESSAGE_BYTES = 8 * 1024 * 1024


class ObsLiveError(RuntimeError):
    """Base error for a live OBS connection or request."""


class ObsNotRunningError(ObsLiveError):
    """The local obs-websocket server could not be reached."""


class ObsAuthenticationRequired(ObsLiveError):
    """OBS requires a WebSocket password for this session."""


class ObsRequestError(ObsLiveError):
    """OBS rejected a live request."""


def is_obs_running() -> bool:
    """Return whether an OBS process appears to be running."""
    try:
        if os.name == "nt":
            completed = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return '"obs64.exe"' in completed.stdout.casefold()
        proc = Path("/proc")
        if proc.is_dir():
            for item in proc.iterdir():
                if not item.name.isdigit():
                    continue
                try:
                    name = (item / "comm").read_text(encoding="utf-8").strip().casefold()
                except (OSError, UnicodeError):
                    continue
                if name in {"obs", "obs-studio"}:
                    return True
    except (OSError, subprocess.SubprocessError):
        return False
    return False


class ObsWebSocketClient:
    """Small synchronous JSON client for the obs-websocket 5.x protocol."""

    def __init__(self, *, password: str | None = None, timeout: float = 3.0) -> None:
        self.password = password
        self.timeout = timeout
        self.socket: socket.socket | None = None
        self._buffer = bytearray()

    def __enter__(self) -> "ObsWebSocketClient":
        return self.connect()

    def __exit__(self, *_args: object) -> None:
        self.close()

    def connect(self) -> "ObsWebSocketClient":
        try:
            sock = socket.create_connection((DEFAULT_HOST, DEFAULT_PORT), self.timeout)
            sock.settimeout(self.timeout)
        except OSError as exc:
            raise ObsNotRunningError(
                "OBS live control is unavailable. Start OBS and enable Tools → "
                "WebSocket Server Settings."
            ) from exc
        self.socket = sock
        try:
            self._upgrade()
            hello = self._receive_json()
            if hello.get("op") != 0 or not isinstance(hello.get("d"), dict):
                raise ObsLiveError("OBS returned an invalid WebSocket greeting.")
            authentication = hello["d"].get("authentication")
            identify: dict[str, Any] = {"rpcVersion": 1, "eventSubscriptions": 0}
            if isinstance(authentication, dict):
                if not self.password:
                    raise ObsAuthenticationRequired(
                        "Enter the password from Tools → WebSocket Server Settings."
                    )
                identify["authentication"] = self._auth(
                    self.password,
                    str(authentication.get("salt", "")),
                    str(authentication.get("challenge", "")),
                )
            self._send_json({"op": 1, "d": identify})
            if self._receive_json().get("op") != 2:
                raise ObsAuthenticationRequired("OBS rejected the WebSocket password.")
            return self
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        sock, self.socket = self.socket, None
        if sock is None:
            return
        try:
            self._send_frame(0x8, struct.pack("!H", 1000), sock)
        except OSError:
            pass
        sock.close()
        self._buffer.clear()

    def request(self, kind: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        payload: dict[str, Any] = {"requestType": kind, "requestId": request_id}
        if data:
            payload["requestData"] = data
        self._send_json({"op": 6, "d": payload})
        while True:
            message = self._receive_json()
            response = message.get("d")
            if message.get("op") != 7 or not isinstance(response, dict):
                continue
            if response.get("requestId") != request_id:
                continue
            status = response.get("requestStatus")
            if not isinstance(status, dict) or not status.get("result"):
                detail = status.get("comment") if isinstance(status, dict) else None
                raise ObsRequestError(f"OBS rejected {kind}: {detail or 'request failed'}")
            value = response.get("responseData")
            return value if isinstance(value, dict) else {}

    def scene_collections(self) -> tuple[str, list[str]]:
        data = self.request("GetSceneCollectionList")
        items = data.get("sceneCollections")
        return str(data.get("currentSceneCollectionName", "")), (
            [str(item) for item in items] if isinstance(items, list) else []
        )

    def activate_scene_collection(self, name: str) -> None:
        self.request("SetCurrentSceneCollection", {"sceneCollectionName": name})

    def _upgrade(self) -> None:
        assert self.socket is not None
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            "GET / HTTP/1.1\r\nHost: 127.0.0.1:4455\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n"
        )
        self.socket.sendall(request.encode("ascii"))
        header = bytearray()
        while b"\r\n\r\n" not in header:
            chunk = self.socket.recv(4096)
            if not chunk or len(header) > 32768:
                raise ObsLiveError("OBS closed the WebSocket handshake.")
            header.extend(chunk)
        if not header.startswith(b"HTTP/1.1 101"):
            raise ObsLiveError("OBS did not accept the WebSocket connection.")
        expected = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
        ).digest()).lower()
        _headers, remainder = bytes(header).split(b"\r\n\r\n", 1)
        self._buffer.extend(remainder)
        if b"sec-websocket-accept: " + expected not in bytes(header).lower():
            raise ObsLiveError("OBS returned an invalid WebSocket handshake.")

    @staticmethod
    def _auth(password: str, salt: str, challenge: str) -> str:
        secret = base64.b64encode(hashlib.sha256(
            (password + salt).encode("utf-8")
        ).digest()).decode("ascii")
        return base64.b64encode(hashlib.sha256(
            (secret + challenge).encode("utf-8")
        ).digest()).decode("ascii")

    def _send_json(self, value: dict[str, Any]) -> None:
        self._send_frame(1, json.dumps(value, separators=(",", ":")).encode())

    def _receive_json(self) -> dict[str, Any]:
        fragments = bytearray()
        while True:
            final, opcode, payload = self._receive_frame()
            if opcode == 8:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 0
                if code == 4009:
                    raise ObsAuthenticationRequired("OBS rejected the WebSocket password.")
                raise ObsLiveError(f"OBS closed the live connection ({code}).")
            if opcode == 9:
                self._send_frame(10, payload)
                continue
            if opcode not in {0, 1}:
                continue
            fragments.extend(payload)
            if len(fragments) > MAX_MESSAGE_BYTES:
                raise ObsLiveError("OBS returned an oversized message.")
            if final:
                try:
                    value = json.loads(fragments.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ObsLiveError("OBS returned invalid WebSocket JSON.") from exc
                if not isinstance(value, dict):
                    raise ObsLiveError("OBS returned an invalid WebSocket message.")
                return value

    def _send_frame(self, opcode: int, payload: bytes, sock: socket.socket | None = None) -> None:
        active = sock or self.socket
        if active is None:
            raise ObsLiveError("OBS live control is not connected.")
        mask = secrets.token_bytes(4)
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length <= 65535:
            header.extend((0x80 | 126, *struct.pack("!H", length)))
        else:
            header.extend((0x80 | 127, *struct.pack("!Q", length)))
        header.extend(mask)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        active.sendall(bytes(header) + masked)

    def _receive_frame(self) -> tuple[bool, int, bytes]:
        first, second = self._read_exact(2)
        length = second & 127
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        if length > MAX_MESSAGE_BYTES:
            raise ObsLiveError("OBS returned an oversized frame.")
        mask = self._read_exact(4) if second & 128 else b""
        payload = self._read_exact(length)
        if mask:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        return bool(first & 128), first & 15, payload

    def _read_exact(self, size: int) -> bytes:
        assert self.socket is not None
        result = bytearray()
        if self._buffer:
            take = min(size, len(self._buffer))
            result.extend(self._buffer[:take])
            del self._buffer[:take]
        while len(result) < size:
            chunk = self.socket.recv(size - len(result))
            if not chunk:
                raise ObsLiveError("OBS closed the live connection unexpectedly.")
            result.extend(chunk)
        return bytes(result)

