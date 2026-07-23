# ==============================================================================
# File: phronesis_app/tests/test_p1_capture_focus.py
# Description: P1 tests — capture parser, focus engine, inbox triage, HTMX cmd, VN-A04 UI
# Component: Tests
# Version: 1.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-21
# ==============================================================================
"""Automated coverage for Phronesis V2 P1 Capture & Focus (incl. VN-A04 + title slash)."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from phronesis_app.models import (
    ExecutionItem,
    FocusSession,
    ItemContainerLink,
    SystemEnums,
    WorkspaceContainer,
)
from phronesis_app.services.capture import parse_capture
from phronesis_app.services.cmd import commit_command, detect_mode, preview_command
from phronesis_app.services.focus import complete_focus, get_open_session, pause_focus, start_focus
from phronesis_app.services.triage import triage_item


class CaptureParserTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")
        self.sprint = WorkspaceContainer.objects.get(slug="p0-foundation")

    def test_parse_container_priority_tags(self):
        preview = parse_capture("#p0-foundation Ship capture p2 @deep-work", tz_name="UTC")
        self.assertEqual(preview.container_slug, "p0-foundation")
        self.assertTrue(preview.container_found)
        self.assertEqual(preview.priority, 2)
        self.assertIn("deep-work", preview.tag_slugs)
        self.assertIn("Ship capture", preview.title)
        self.assertEqual(preview.status, SystemEnums.ItemStatus.BACKLOG)

    def test_unknown_container_warns_inbox(self):
        preview = parse_capture("#nope-sprint Something", tz_name="UTC")
        self.assertFalse(preview.container_found)
        self.assertTrue(any("Unknown container" in w for w in preview.warnings))
        self.assertEqual(preview.status, SystemEnums.ItemStatus.INBOX)

    def test_common_title_words_not_eaten_as_chrono(self):
        """Regression: multilang dateparser must not strip Do/more from titles."""
        a = parse_capture("Do silly stuff", tz_name="UTC")
        b = parse_capture("Do more silly stuff", tz_name="UTC")
        self.assertEqual(a.title, "Do silly stuff")
        self.assertEqual(b.title, "Do more silly stuff")
        self.assertNotEqual(a.title, b.title)
        self.assertIsNone(a.due_at)
        self.assertIsNone(b.due_at)

    def test_buy_more_milk_keeps_more(self):
        preview = parse_capture("Buy more milk", tz_name="UTC")
        self.assertEqual(preview.title, "Buy more milk")
        self.assertIsNone(preview.due_at)

    def test_slash_attrs_keep_title_verbatim(self):
        preview = parse_capture(
            "Do more silly stuff / #p0-foundation p2 @deep-work due friday",
            tz_name="UTC",
        )
        self.assertEqual(preview.title, "Do more silly stuff")
        self.assertEqual(preview.container_slug, "p0-foundation")
        self.assertTrue(preview.container_found)
        self.assertEqual(preview.priority, 2)
        self.assertIn("deep-work", preview.tag_slugs)
        self.assertIsNotNone(preview.due_at)

    def test_slash_attrs_fuzzy_and_estimate(self):
        preview = parse_capture("Do silly stuff / tomorrow ~30m", tz_name="UTC")
        self.assertEqual(preview.title, "Do silly stuff")
        self.assertEqual(preview.fuzzy_timeframe, SystemEnums.FuzzyTimeframe.TOMORROW)
        self.assertEqual(preview.estimated_minutes, 30)

    def test_slash_friday_in_title_stays_in_title(self):
        preview = parse_capture("Ship friday update / p3", tz_name="UTC")
        self.assertEqual(preview.title, "Ship friday update")
        self.assertEqual(preview.priority, 3)
        self.assertIsNone(preview.due_at)

    def test_bare_friday_still_chrono_without_slash(self):
        preview = parse_capture("Ship docs friday", tz_name="UTC")
        self.assertEqual(preview.title, "Ship docs")
        self.assertIsNotNone(preview.due_at)

    def test_only_first_spaced_slash_delimits_attributes(self):
        preview = parse_capture(
            "Review API / p2 / @deep-work ~30m",
            tz_name="UTC",
        )
        self.assertEqual(preview.title, "Review API")
        self.assertEqual(preview.priority, 2)
        self.assertIn("deep-work", preview.tag_slugs)
        self.assertEqual(preview.estimated_minutes, 30)
        self.assertTrue(any("Ignored in attributes" in warning for warning in preview.warnings))

    def test_unspaced_slash_stays_in_verbatim_title(self):
        preview = parse_capture("Review docs/api / p2", tz_name="UTC")
        self.assertEqual(preview.title, "Review docs/api")
        self.assertEqual(preview.priority, 2)

    def test_slash_attrs_parse_recurrence_without_touching_title(self):
        preview = parse_capture(
            "Do friday maintenance / #p0-foundation @ops every weekday at 9am",
            tz_name="UTC",
        )
        self.assertEqual(preview.title, "Do friday maintenance")
        self.assertEqual(preview.container_slug, "p0-foundation")
        self.assertIn("ops", preview.tag_slugs)
        self.assertIsNotNone(preview.recurrence)
        self.assertFalse(preview.recurrence.ambiguous)
        self.assertEqual(preview.recurrence.freq, "WEEKDAY")
        self.assertEqual(preview.recurrence.byhour, 9)

    def test_quoted_title_keeps_go_prefix_as_capture(self):
        preview = parse_capture('"go grocery shopping" / #p0-foundation p2', tz_name="UTC")
        self.assertEqual(preview.title, "go grocery shopping")
        self.assertEqual(preview.container_slug, "p0-foundation")
        self.assertEqual(preview.priority, 2)

    def test_single_quoted_title_with_attrs_no_slash(self):
        preview = parse_capture("'focus on breathing' tomorrow ~15m", tz_name="UTC")
        self.assertEqual(preview.title, "focus on breathing")
        self.assertEqual(preview.fuzzy_timeframe, SystemEnums.FuzzyTimeframe.TOMORROW)
        self.assertEqual(preview.estimated_minutes, 15)

    def test_quoted_title_can_contain_slash(self):
        preview = parse_capture('"Review docs / api notes" p3', tz_name="UTC")
        self.assertEqual(preview.title, "Review docs / api notes")
        self.assertEqual(preview.priority, 3)

    def test_unclosed_quote_falls_through_to_mixed_parse(self):
        preview = parse_capture('"Do silly stuff', tz_name="UTC")
        self.assertEqual(preview.title, '"Do silly stuff')
        self.assertIsNone(preview.recurrence)


class FocusEngineTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")
        self.shell = ExecutionItem.objects.get(title="Build cockpit shell + Home bento")
        self.focus_item = ExecutionItem.objects.get(title="Implement Focus Engine start/pause/complete")

    def test_start_preempts_open_session(self):
        r1 = start_focus(self.shell)
        self.assertTrue(r1.ok)
        r2 = start_focus(self.focus_item)
        self.assertTrue(r2.ok)
        self.assertEqual(FocusSession.objects.filter(ended_at__isnull=True).count(), 1)
        preempted = FocusSession.objects.filter(end_reason=SystemEnums.FocusEndReason.PREEMPTED).count()
        self.assertEqual(preempted, 1)

    def test_complete_blocked_by_dependency(self):
        start_focus(self.focus_item)
        result = complete_focus(self.focus_item)
        self.assertFalse(result.ok)
        self.assertIn("prerequisites", result.message.lower())
        self.focus_item.refresh_from_db()
        self.assertNotEqual(self.focus_item.status, SystemEnums.ItemStatus.COMPLETED)

    def test_pause_accumulates_time(self):
        start_focus(self.shell)
        session = get_open_session()
        self.assertIsNotNone(session)
        before = self.shell.time_spent_seconds
        pause_focus()
        self.shell.refresh_from_db()
        self.assertGreater(self.shell.time_spent_seconds, before)


class TriageTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")

    def test_triage_moves_to_backlog(self):
        item = ExecutionItem.objects.filter(status=SystemEnums.ItemStatus.INBOX).first()
        result = triage_item(item, "p0-foundation")
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertEqual(item.status, SystemEnums.ItemStatus.BACKLOG)
        self.assertTrue(
            ItemContainerLink.objects.filter(item=item, container__slug="p0-foundation", is_primary=True).exists()
        )


class CmdPaletteViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser("owner", "owner@test", "pass")
        self.client = Client()
        self.client.login(username="owner", password="pass")
        call_command("seed_data", "--flush")

    def test_preview_returns_fragment(self):
        response = self.client.post(reverse("cmd-preview"), {"input": "go inbox"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"inbox", response.content.lower())

    def test_capture_commit_creates_item(self):
        before = ExecutionItem.objects.count()
        result = commit_command("Inbox triage test p3 @quick-win")
        self.assertTrue(result.ok)
        self.assertEqual(ExecutionItem.objects.count(), before + 1)
        item = ExecutionItem.objects.get(title="Inbox triage test")
        self.assertEqual(item.status, SystemEnums.ItemStatus.INBOX)

    def test_do_title_preview_uses_capture_mode(self):
        preview = preview_command("Do more silly stuff / p2")
        self.assertEqual(preview.mode, "capture")
        self.assertIsNotNone(preview.capture)
        self.assertEqual(preview.capture.title, "Do more silly stuff")
        self.assertEqual(preview.capture.priority, 2)

    def test_quoted_go_title_is_capture_not_navigate(self):
        self.assertEqual(detect_mode('"go grocery shopping"')[0], "capture")
        preview = preview_command('"go grocery shopping" / p2')
        self.assertEqual(preview.mode, "capture")
        self.assertEqual(preview.capture.title, "go grocery shopping")
        self.assertEqual(preview.capture.priority, 2)
        self.assertIsNone(preview.redirect_url)

    def test_quoted_focus_title_is_capture_not_do(self):
        self.assertEqual(detect_mode("'focus on breathing'")[0], "capture")
        preview = preview_command("'focus on breathing' p3")
        self.assertEqual(preview.mode, "capture")
        self.assertEqual(preview.capture.title, "focus on breathing")
        self.assertEqual(preview.capture.priority, 3)

    def test_commit_keeps_similar_do_titles_distinct(self):
        first = commit_command("Do silly stuff")
        second = commit_command("Do more silly stuff")
        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertNotEqual(first.item_id, second.item_id)
        self.assertTrue(ExecutionItem.objects.filter(title="Do silly stuff").exists())
        self.assertTrue(ExecutionItem.objects.filter(title="Do more silly stuff").exists())

    def test_go_preview_has_redirect(self):
        preview = preview_command("go matrix")
        self.assertEqual(preview.mode, "go")
        self.assertIsNotNone(preview.redirect_url)

    def test_inbox_surface_loads(self):
        response = self.client.get(reverse("canvas-inbox"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Inbox Triage", response.content)

    def test_focus_start_fragment(self):
        item = ExecutionItem.objects.get(title="Build cockpit shell + Home bento")
        response = self.client.post(
            reverse("focus-start", args=[item.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Active Focus", response.content)

    def test_focus_pause_endpoint_closes_active_session(self):
        item = ExecutionItem.objects.get(title="Build cockpit shell + Home bento")
        start_focus(item)

        response = self.client.post(
            reverse("focus-pause"),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(get_open_session())
        self.assertIn("refreshHome", response["HX-Trigger"])

    def test_focus_pause_without_session_returns_validation_error(self):
        FocusSession.objects.filter(ended_at__isnull=True).update(
            ended_at=FocusSession.objects.first().started_at
        )

        response = self.client.post(
            reverse("focus-pause"),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 422)

    def test_focus_complete_item_endpoint_updates_status(self):
        item = ExecutionItem.objects.create(
            title="Independent focus completion",
            status=SystemEnums.ItemStatus.PLANNED,
        )
        start_focus(item)

        response = self.client.post(
            reverse("focus-complete-item", args=[item.pk]),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.status, SystemEnums.ItemStatus.COMPLETED)
        self.assertIsNone(get_open_session())


class VisibleCaptureUITests(TestCase):
    """VN-A04 — Capture is a visible click path on shell / Home (not Cmd-only)."""

    def setUp(self):
        User = get_user_model()
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        from phronesis_app.services.modules import apply_preset

        apply_preset("simple")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_home_shows_shell_and_home_capture_controls(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('data-testid="capture-open"', body)
        self.assertIn('data-testid="home-capture-open"', body)
        self.assertIn('data-testid="cmd-palette-open"', body)
        self.assertIn("openCapture()", body)

    def test_inbox_shell_still_exposes_capture(self):
        response = self.client.get(reverse("canvas-inbox"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="capture-open"')

    def test_palette_enter_commits_via_helper(self):
        """Regression: Alpine semicolon expression broke Enter; use phronesisCommitPalette."""
        response = self.client.get(reverse("home"))
        body = response.content.decode()
        self.assertIn("@keydown.enter.prevent=\"phronesisCommitPalette($el)\"", body)
        # Script is loaded via partial include — ensure helper exists in static partial source
        from pathlib import Path

        script = (Path(__file__).resolve().parents[1] / "templates/partials/cockpit_script.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("window.phronesisCommitPalette", script)
