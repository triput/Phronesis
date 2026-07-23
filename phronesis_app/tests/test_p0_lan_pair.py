# ==============================================================================
# File: phronesis_app/tests/test_p0_lan_pair.py
# Description: VN-D04 LAN pair token auth + pack GET/POST apply path
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Ephemeral LAN receive — token gate and sync-pack HTTP apply."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import timedelta

from django.core.management import call_command
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from phronesis_app.models import ExecutionItem
from phronesis_app.services.lan_pair import (
    authenticate_lan_token,
    start_lan_pair,
    stop_lan_pair,
)
from phronesis_app.services.sync_pack import SYNC_PACK_FORMAT, build_sync_pack_dict


class LanPairServiceTests(TransactionTestCase):
    """In-process ThreadingHTTPServer for stretch LAN pair.

    Uses TransactionTestCase so the HTTP worker thread can see committed rows
    (TestCase's outer transaction is invisible to other threads).
    """

    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        stop_lan_pair()

    def tearDown(self):
        stop_lan_pair()

    def test_token_required_and_pack_roundtrip(self):
        status = start_lan_pair(port=18766, ttl_seconds=120)
        self.assertTrue(status.active, msg=status.last_error or status.message)
        self.assertTrue(authenticate_lan_token(status.token))
        self.assertFalse(authenticate_lan_token("nope"))

        base = f"http://127.0.0.1:{status.port}"

        # No token → 401
        req = urllib.request.Request(f"{base}/pack", method="GET")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=3)
        self.assertEqual(ctx.exception.code, 401)

        # GET with bearer → pack JSON
        req = urllib.request.Request(
            f"{base}/pack",
            headers={"Authorization": f"Bearer {status.token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self.fail(f"GET /pack HTTP {exc.code}: {detail}")
        self.assertEqual(payload["format"], SYNC_PACK_FORMAT)

        # POST pack that updates an item title (newer LWW)
        item = ExecutionItem.objects.filter(is_deleted=False).first()
        pack = build_sync_pack_dict()
        for row in pack["entities"]["items"]:
            if row["sync_id"] == str(item.sync_id):
                row["title"] = "LAN Remote Title"
                row["updated_at"] = (timezone.now() + timedelta(hours=2)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                break
        body = json.dumps(pack).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/pack?token={status.token}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(result.get("ok"), msg=result)
        item.refresh_from_db()
        self.assertEqual(item.title, "LAN Remote Title")

        stop_lan_pair()
        self.assertFalse(authenticate_lan_token(status.token))


class LanPairViewTests(TransactionTestCase):
    """Settings Sync tab start/stop."""

    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.assertTrue(self.client.login(username="owner", password="ownerpass"))
        stop_lan_pair()

    def tearDown(self):
        stop_lan_pair()

    def test_start_stop_via_settings(self):
        resp = self.client.post(reverse("settings-lan-start"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "data-testid=\"lan-pair-active\"")
        self.assertContains(resp, "data-testid=\"lan-pair-token\"")

        resp = self.client.post(reverse("settings-lan-stop"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "data-testid=\"lan-pair-start\"")
