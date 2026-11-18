"""Minimal client for T3 Code's local server.

T3 Code exposes a WebSocket RPC on localhost. Usage Floor issues a short-lived session token with
the T3 CLI (`t3 auth session issue`), scoped to reading and operating threads only, and revokes it
when done. The token never leaves this machine and is never written to disk.

These RPC methods are internal to T3 Code, not a published API. They can change between releases.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import socket
import sqlite3
import struct
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from usage_floor.paths import Paths

SCOPES = ("orchestration:read", "orchestration:operate")
ACTIVE_RUNS_SQL = (
    "select run_id, thread_id, status, provider_instance_id from orchestration_v2_projection_runs "
    "where status in ('running', 'starting', 'preparing', 'waiting')"
)
MAX_FRAME = 32 * 1024 * 1024
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class T3Error(RuntimeError):
    """T3 Code rejected a request or could not be reached."""


def _websocket_accept(nonce: str) -> str:
    # RFC 6455 mandates SHA-1 for the handshake digest; it is not used for security.
    digest = hashlib.sha1((nonce + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii"), usedforsecurity=False)
    return base64.b64encode(digest.digest()).decode("ascii")


class T3Client:
    """Context manager holding one authenticated WebSocket connection to the local T3 server."""

    def __init__(self, paths: Paths, label: str = "Usage Floor") -> None:
        self.paths = paths
        self.label = label
        self.sock: socket.socket | None = None
        self.session: dict[str, Any] | None = None
        self.sequence = 0

    # -- lifecycle ---------------------------------------------------------------------------

    def _cli(self, *args: str) -> str:
        result = subprocess.run(  # noqa: S603 -- fixed executable, explicit argv, no shell
            [self.paths.t3_cli, *args],
            capture_output=True,
            encoding="utf-8",
            check=False,
            timeout=60,
            creationflags=NO_WINDOW,
        )
        if result.returncode:
            raise T3Error(f"t3 CLI exited with {result.returncode}: {result.stderr.strip()[:300]}")
        return result.stdout

    def __enter__(self) -> T3Client:
        scopes = [arg for scope in SCOPES for arg in ("--scope", scope)]
        issued = self._cli(
            "auth", "session", "issue", "--base-dir", str(self.paths.t3_home), *scopes,
            "--ttl", "10m", "--label", self.label, "--json",
        )
        self.session = json.loads(issued)
        try:
            self._connect(self.session["token"])
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        if self.session is not None:
            session_id = self.session.get("sessionId")
            self.session = None
            if session_id:  # a failed revoke is harmless: the token expires on its own after ten minutes
                with contextlib.suppress(OSError, T3Error, subprocess.TimeoutExpired):
                    self._cli("auth", "session", "revoke", "--base-dir", str(self.paths.t3_home), session_id)

    def _connect(self, token: str) -> None:
        runtime = json.loads(self.paths.t3_runtime.read_text(encoding="utf-8"))
        endpoint = urlparse(runtime["origin"])
        if endpoint.scheme != "http" or endpoint.hostname not in ("127.0.0.1", "localhost"):
            raise T3Error("Refusing to connect: the recorded T3 server is not on localhost.")
        self.sock = socket.create_connection((endpoint.hostname, endpoint.port), timeout=40)
        nonce = base64.b64encode(os.urandom(16)).decode("ascii")
        request = [
            "GET /ws?orchestrationProtocol=2 HTTP/1.1",
            f"Host: {endpoint.netloc}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            "Sec-WebSocket-Version: 13",
            "Sec-WebSocket-Key: " + nonce,
            "Authorization: Bearer " + token,
            "",
            "",
        ]
        self._sock().sendall("\r\n".join(request).encode("ascii"))
        response = bytearray()
        while not response.endswith(b"\r\n\r\n"):
            response += self._read(1)
            if len(response) > 32768:
                raise T3Error("Oversized WebSocket upgrade response")
        text = response.decode("latin-1")
        if not text.startswith("HTTP/1.1 101"):
            raise T3Error("T3 refused the connection: " + text.splitlines()[0])
        fields = (line.split(":", 1) for line in text.split("\r\n")[1:] if ":" in line)
        headers = {key.strip().lower(): value.strip() for key, value in fields}
        if headers.get("sec-websocket-accept") != _websocket_accept(nonce):
            raise T3Error("WebSocket handshake mismatch")
        self.sequence = 0

    # -- framing -----------------------------------------------------------------------------

    def _sock(self) -> socket.socket:
        if self.sock is None:
            raise T3Error("Not connected")
        return self.sock

    def _read(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = self._sock().recv(size - len(data))
            if not chunk:
                raise T3Error("T3 closed the connection")
            data.extend(chunk)
        return bytes(data)

    def _send(self, payload: bytes, opcode: int = 1) -> None:
        length = len(payload)
        if length < 126:
            header = bytes([0x80 | opcode, 0x80 | length])
        elif length < 65536:
            header = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack("!H", length)
        else:
            header = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack("!Q", length)
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self._sock().sendall(header + mask + masked)

    def _receive(self) -> Any:
        message = bytearray()
        while True:
            first, second = self._read(2)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
            if length > MAX_FRAME:
                raise T3Error("Oversized frame")
            mask = self._read(4) if second & 0x80 else None
            payload = self._read(length)
            if mask:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            opcode = first & 0x0F
            if opcode == 8:
                raise T3Error("T3 closed the connection")
            if opcode == 9:
                self._send(payload, 10)
                continue
            if opcode == 10:
                continue
            message.extend(payload)
            if first & 0x80:
                return json.loads(message.decode("utf-8"))

    def call(self, method: str, payload: dict[str, Any], timeout: float = 60) -> Any:
        """Send one request and wait for its result."""
        self.sequence += 1
        key = str(self.sequence)
        self._sock().settimeout(timeout)
        request = {"_tag": "Request", "id": key, "tag": method, "payload": payload, "headers": []}
        self._send(json.dumps(request).encode("utf-8"))
        while True:
            response = self._receive()
            for event in response if isinstance(response, list) else [response]:
                if event.get("_tag") == "Ping":
                    self._send(b'{"_tag":"Pong"}')
                elif event.get("_tag") == "Defect":
                    raise T3Error("Protocol defect: " + str(event.get("defect"))[:300])
                elif event.get("_tag") == "Exit" and str(event.get("requestId")) == key:
                    result = event["exit"]
                    if result.get("_tag") != "Success":
                        raise T3Error(f"{method} rejected: {json.dumps(result)[:600]}")
                    return result.get("value")

    # -- operations --------------------------------------------------------------------------

    def server_config(self) -> dict[str, Any]:
        return self.call("server.getConfig", {}, timeout=120)

    def dispatch(self, command: dict[str, Any]) -> None:
        self.call("orchestration.dispatchCommand", {"commandId": f"usage-floor:{uuid.uuid4()}", **command})

    def steer(self, thread_id: str, run_id: str, text: str) -> None:
        self._message(thread_id, text, {"type": "steer_active", "targetRunId": run_id})

    def queue_message(self, thread_id: str, text: str) -> None:
        self._message(thread_id, text, {"type": "queue_after_active"})

    def interrupt(self, thread_id: str, run_id: str, reason: str) -> None:
        self.dispatch({
            "type": "run.interrupt", "threadId": thread_id, "runId": run_id, "reason": reason, "holdQueue": True,
        })

    def resume_queue(self, thread_id: str) -> None:
        self.dispatch({"type": "queue.resume", "threadId": thread_id})

    def _message(self, thread_id: str, text: str, mode: dict[str, Any]) -> None:
        self.dispatch({
            "type": "message.dispatch",
            "createdBy": "agent",
            "creationSource": "mcp",
            "threadId": thread_id,
            "messageId": f"message:usage-floor:{uuid.uuid4()}",
            "text": text,
            "attachments": [],
            "dispatchMode": mode,
        })


def active_runs(state_db: Path) -> list[dict[str, Any]]:
    """Runs currently using a provider, read from T3's state database in read-only mode."""
    uri = state_db.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as db:
        rows = db.execute(ACTIVE_RUNS_SQL).fetchall()
    return [{"runId": r[0], "threadId": r[1], "status": r[2], "instanceId": r[3]} for r in rows]
