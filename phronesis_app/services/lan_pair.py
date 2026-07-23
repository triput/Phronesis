# ==============================================================================
# File: phronesis_app/services/lan_pair.py
# Description: VN-D04 ephemeral LAN HTTP pair for sync-pack push/pull
# Component: Services / Sync
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Same-LAN pair without cloud: short-lived cleartext HTTP + one-time token.

Binds ``0.0.0.0`` on a dedicated port (default 18765) so Android on the same
LAN can GET/POST ``phronesis.sync_pack`` JSON. Not internet-facing by intent —
firewall + short TTL + bearer token are the controls. HTTPS is optional and
not required for stretch MVP.
"""

from __future__ import annotations

import json
import logging
import secrets
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from django.db import close_old_connections

from phronesis_app.services.sync_pack import (
    apply_sync_pack,
    export_sync_pack_bytes,
    parse_sync_pack_bytes,
)

logger = logging.getLogger(__name__)

LAN_PAIR_DEFAULT_PORT = 18765
LAN_PAIR_TTL_SECONDS = 600  # 10 minutes


@dataclass
class LanPairStatus:
    """Snapshot for Settings Sync tab / tests."""

    active: bool
    token: str = ""
    port: int = 0
    lan_ip: str = ""
    base_url: str = ""
    expires_at: str = ""
    warning: str = ""
    last_error: str = ""
    message: str = ""


_lock = threading.Lock()
_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None
_token: str = ""
_expires_at: datetime | None = None
_lan_ip: str = ""
_port: int = 0
_last_error: str = ""
_pack_export_lock = threading.Lock()


def _run_db(fn):
    """Run ORM work from the LAN HTTP thread with a fresh connection."""
    close_old_connections()
    try:
        with _pack_export_lock:
            return fn()
    finally:
        close_old_connections()


def discover_lan_ip() -> str:
    """Best-effort primary LAN IPv4 (not 127.0.0.1)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        # No packets sent; OS picks the route interface.
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            candidate = info[4][0]
            if candidate and not candidate.startswith("127."):
                return candidate
    except OSError:
        pass
    return "127.0.0.1"


def _utc_now() -> datetime:
    return datetime.now(dt_timezone.utc)


def _token_valid(provided: str | None) -> bool:
    global _token, _expires_at
    if not _token or not provided:
        return False
    if _expires_at is None or _utc_now() >= _expires_at:
        return False
    return secrets.compare_digest(provided, _token)


def _extract_token(handler: BaseHTTPRequestHandler) -> str:
    auth = handler.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    parsed = urlparse(handler.path)
    qs = parse_qs(parsed.query)
    vals = qs.get("token") or []
    return (vals[0] if vals else "").strip()


class _LanPairHandler(BaseHTTPRequestHandler):
    """Minimal pack GET/POST; rejects missing/expired tokens."""

    server_version = "PhronesisLanPair/0.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        logger.debug("lan_pair: " + fmt, *args)

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _require_token(self) -> bool:
        if not _token_valid(_extract_token(self)):
            self._json(401, {"ok": False, "error": "invalid_or_expired_token"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._json(
                200,
                {
                    "ok": True,
                    "service": "phronesis.lan_pair",
                    "active": lan_pair_status().active,
                },
            )
            return
        if path == "/pack":
            if not self._require_token():
                return
            try:
                raw = _run_db(export_sync_pack_bytes)
            except Exception as exc:  # noqa: BLE001 — surface to client
                self._json(500, {"ok": False, "error": str(exc)})
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
            return
        self._json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path != "/pack":
            self._json(404, {"ok": False, "error": "not_found"})
            return
        if not self._require_token():
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 32 * 1024 * 1024:
            self._json(400, {"ok": False, "error": "invalid_body_length"})
            return
        raw = self.rfile.read(length)
        try:

            def _apply():
                payload = parse_sync_pack_bytes(raw)
                return apply_sync_pack(payload)

            result = _run_db(_apply)
            self._json(
                200,
                {
                    "ok": result.ok,
                    "message": result.message,
                    "applied": result.applied,
                    "tombstones_applied": result.tombstones_applied,
                    "conflict_count": len(result.skipped_conflicts),
                    "conflicts": result.skipped_conflicts[:50],
                    "source_device_id": result.source_device_id,
                },
            )
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            global _last_error
            _last_error = str(exc)
            logger.exception("lan_pair POST /pack failed")
            self._json(500, {"ok": False, "error": str(exc)})


def _status_unlocked() -> LanPairStatus:
    """Build status snapshot; caller must hold ``_lock`` or accept races in tests."""
    active = (
        _server is not None
        and bool(_token)
        and _expires_at is not None
        and _utc_now() < _expires_at
    )
    warning = (
        "Cleartext HTTP on the LAN — treat like a cable sync file. "
        "Token expires soon; stop the session when done."
        if active
        else ""
    )
    base = f"http://{_lan_ip}:{_port}" if active else ""
    return LanPairStatus(
        active=active,
        token=_token if active else "",
        port=_port if active else 0,
        lan_ip=_lan_ip if active else "",
        base_url=base,
        expires_at=_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ") if active and _expires_at else "",
        warning=warning,
        last_error=_last_error,
        message=(
            f"Listening on {base}/pack — pass token as Bearer or ?token="
            if active
            else "LAN receive is off."
        ),
    )


def lan_pair_status() -> LanPairStatus:
    """Current receive session for Settings / API."""
    with _lock:
        # Expire lazily
        if (
            _server is not None
            and _expires_at is not None
            and _utc_now() >= _expires_at
        ):
            stop_lan_pair_locked()
        return _status_unlocked()


def start_lan_pair(
    *,
    port: int = LAN_PAIR_DEFAULT_PORT,
    ttl_seconds: int = LAN_PAIR_TTL_SECONDS,
) -> LanPairStatus:
    """Start (or refresh) ephemeral LAN receive; returns status with URL+token."""
    global _server, _thread, _token, _expires_at, _lan_ip, _port, _last_error

    with _lock:
        stop_lan_pair_locked()
        _token = secrets.token_urlsafe(18)
        _expires_at = _utc_now() + timedelta(seconds=max(60, int(ttl_seconds)))
        _lan_ip = discover_lan_ip()
        _port = int(port) or LAN_PAIR_DEFAULT_PORT
        _last_error = ""
        try:
            server = ThreadingHTTPServer(("0.0.0.0", _port), _LanPairHandler)
        except OSError as exc:
            _token = ""
            _expires_at = None
            _port = 0
            _last_error = f"Could not bind port {_port or port}: {exc}"
            return LanPairStatus(
                active=False,
                message=_last_error,
                last_error=_last_error,
            )

        _server = server
        thread = threading.Thread(
            target=server.serve_forever,
            name="phronesis-lan-pair",
            daemon=True,
        )
        _thread = thread
        thread.start()

        # Auto-stop after TTL
        def _auto_stop() -> None:
            import time

            time.sleep(max(60, int(ttl_seconds)))
            with _lock:
                if _expires_at is not None and _utc_now() >= _expires_at:
                    stop_lan_pair_locked()

        threading.Thread(target=_auto_stop, name="phronesis-lan-pair-ttl", daemon=True).start()
        return _status_unlocked()


def stop_lan_pair_locked() -> None:
    """Stop server; caller must hold ``_lock``."""
    global _server, _thread, _token, _expires_at, _port

    if _server is not None:
        try:
            _server.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            _server.server_close()
        except Exception:  # noqa: BLE001
            pass
    _server = None
    _thread = None
    _token = ""
    _expires_at = None
    _port = 0


def stop_lan_pair() -> LanPairStatus:
    """Stop LAN receive session."""
    with _lock:
        stop_lan_pair_locked()
        status = _status_unlocked()
    status.message = "LAN receive stopped."
    return status


def authenticate_lan_token(token: str) -> bool:
    """Test helper — verify bearer/query token against active session."""
    return _token_valid((token or "").strip())
