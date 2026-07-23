# ==============================================================================
# File: phronesis_app/tests/test_p3_planning.py
# Description: P3 tests — Plan Today, scheduler, planner, durations, reminders
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Automated coverage for Phronesis V2 P3 Time & Planning (core slice)."""

from datetime import datetime, time, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone as django_timezone

from phronesis_app.models import (
    AppSettings,
    CalendarEvent,
    ExecutionItem,
    ItemContainerLink,
    ScheduledAllocation,
    SystemEnums,
    TimeAvailabilityBlock,
    WorkspaceContainer,
)
from phronesis_app.services.cmd import commit_command, preview_command
from phronesis_app.services.notify import pending_alert_count, sweep_reminders
from phronesis_app.services.scheduler import run_scheduler, schedulable_candidates
from phronesis_app.services.time_format import (
    format_duration_minutes,
    format_duration_seconds,
    parse_duration_minutes,
)
from phronesis_app.services.today import clear_today, plan_today, today_item_ids


class TimeFormatTests(TestCase):
    def test_format_minutes(self):
        self.assertEqual(format_duration_minutes(90), "1h 30m")
        self.assertEqual(format_duration_minutes(1440), "1d")
        self.assertEqual(format_duration_minutes(45), "45m")

    def test_format_seconds(self):
        self.assertEqual(format_duration_seconds(45), "45s")
        self.assertEqual(format_duration_seconds(90), "1m")
        self.assertEqual(format_duration_seconds(7200), "2h")
        self.assertEqual(format_duration_seconds(0), "0m")

    def test_parse_duration(self):
        self.assertEqual(parse_duration_minutes("2h"), 120)
        self.assertEqual(parse_duration_minutes("1d 4h"), 1680)
        self.assertEqual(parse_duration_minutes("90"), 90)


class PlanTodayTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")
        self.today = WorkspaceContainer.objects.get(slug="today")
        self.capture = ExecutionItem.objects.get(title="Wire Cmd+K Lightning Capture")

    def test_plan_today_adds_non_primary_link(self):
        primary = ItemContainerLink.objects.get(item=self.capture, is_primary=True)
        self.assertNotEqual(primary.container, self.today)
        before = today_item_ids()
        result = plan_today(item_ids=[self.capture.pk])
        self.assertTrue(result.ok)
        self.assertIn(self.capture.pk, today_item_ids())
        primary.refresh_from_db()
        self.assertTrue(primary.is_primary)

    def test_clear_today_removes_links(self):
        plan_today(item_ids=[self.capture.pk])
        result = clear_today()
        self.assertTrue(result.ok)
        self.assertNotIn(self.capture.pk, today_item_ids())

    def test_cmd_plan_today_preview(self):
        preview = preview_command("plan today capture")
        self.assertEqual(preview.mode, "do")
        self.assertIn("Plan today", preview.summary)

    def test_cmd_plan_today_commit(self):
        result = commit_command("plan today capture")
        self.assertTrue(result.ok)
        self.assertIn(self.capture.pk, today_item_ids())


class SchedulerTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")
        self.focus = ExecutionItem.objects.get(
            title="Implement Focus Engine start/pause/complete"
        )
        ScheduledAllocation.objects.filter(execution_item=self.focus).delete()

    def test_blocked_item_excluded_from_candidates(self):
        self.assertNotIn(self.focus, list(schedulable_candidates()))

    def test_run_scheduler_places_items(self):
        before = ScheduledAllocation.objects.count()
        result = run_scheduler()
        self.assertTrue(result.ok)
        self.assertGreaterEqual(ScheduledAllocation.objects.count(), before)
        self.assertGreater(result.placed, 0)


class SchedulerEdgeCaseTests(TestCase):
    """Verify deterministic fitting, ranking, and exhausted-capacity behavior."""

    def setUp(self):
        self.now = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)  # Monday
        django_timezone.activate(dt_timezone.utc)
        self.settings = AppSettings.get_solo()
        self.settings.scheduler_buffer_minutes = 0
        self.settings.calendar_push_enabled = False
        self.settings.save()

    def tearDown(self):
        django_timezone.deactivate()
        super().tearDown()

    def _availability(self, start: time, end: time):
        """Create a Monday-only availability window for the frozen clock."""
        return TimeAvailabilityBlock.objects.create(
            name="Test Monday",
            start_time=start,
            end_time=end,
            day_monday=True,
            day_tuesday=False,
            day_wednesday=False,
            day_thursday=False,
            day_friday=False,
            day_saturday=False,
            day_sunday=False,
        )

    def _item(self, title: str, *, priority: int = 3, minutes: int = 30):
        return ExecutionItem.objects.create(
            title=title,
            status=SystemEnums.ItemStatus.PLANNED,
            priority=priority,
            urgency=SystemEnums.UrgencyLevel.NORMAL,
            estimated_minutes=minutes,
        )

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_no_availability_returns_actionable_failure(self, mock_now):
        mock_now.return_value = self.now
        self._item("Unscheduled item")

        result = run_scheduler(horizon_days=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.placed, 0)
        self.assertIn("No availability", result.message)

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_blocking_calendar_event_is_subtracted(self, mock_now):
        mock_now.return_value = self.now
        self._availability(time(9, 0), time(12, 0))
        item = self._item("After meeting", minutes=30)
        CalendarEvent.objects.create(
            title="Blocking meeting",
            start_at=self.now.replace(hour=9),
            end_at=self.now.replace(hour=10),
            is_blocking=True,
        )

        result = run_scheduler(horizon_days=0)

        self.assertTrue(result.ok)
        allocation = ScheduledAllocation.objects.get(execution_item=item)
        self.assertEqual(allocation.start_at, self.now.replace(hour=10))

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_priority_controls_placement_order(self, mock_now):
        mock_now.return_value = self.now
        self._availability(time(9, 0), time(11, 0))
        low = self._item("Low priority", priority=4)
        high = self._item("High priority", priority=1)

        result = run_scheduler(horizon_days=0)

        self.assertEqual(result.placed, 2)
        high_alloc = ScheduledAllocation.objects.get(execution_item=high)
        low_alloc = ScheduledAllocation.objects.get(execution_item=low)
        self.assertLess(high_alloc.start_at, low_alloc.start_at)

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_buffer_is_applied_once_between_allocations(self, mock_now):
        """Regression: a ten-minute policy buffer must not become twenty."""
        mock_now.return_value = self.now
        self.settings.scheduler_buffer_minutes = 10
        self.settings.save(update_fields=["scheduler_buffer_minutes", "updated_at"])
        self._availability(time(9, 0), time(11, 0))
        first = self._item("First", priority=1)
        second = self._item("Second", priority=2)

        result = run_scheduler(horizon_days=0)

        self.assertEqual(result.placed, 2)
        first_alloc = ScheduledAllocation.objects.get(execution_item=first)
        second_alloc = ScheduledAllocation.objects.get(execution_item=second)
        self.assertEqual(second_alloc.start_at - first_alloc.end_at, timedelta(minutes=10))

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_item_without_large_enough_slot_is_counted(self, mock_now):
        mock_now.return_value = self.now
        self._availability(time(9, 0), time(10, 0))
        item = self._item("Too large", minutes=90)

        result = run_scheduler(horizon_days=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.placed, 0)
        self.assertEqual(result.skipped_no_slot, 1)
        self.assertFalse(ScheduledAllocation.objects.filter(execution_item=item).exists())


class PlannerSurfaceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_plan_view_loads(self):
        response = self.client.get(reverse("canvas-plan"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Planner")
        self.assertContains(response, "#today")

    def test_schedule_run_htmx(self):
        response = self.client.post(
            reverse("schedule-run"),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scheduled")

    def test_alerts_glyph(self):
        response = self.client.get(reverse("alerts-glyph"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)

    def test_today_plan_endpoint_adds_requested_item(self):
        item = ExecutionItem.objects.filter(
            is_deleted=False,
            status=SystemEnums.ItemStatus.BACKLOG,
        ).first()
        self.assertIsNotNone(item)

        response = self.client.post(
            reverse("today-plan"),
            {"item_ids": str(item.pk)},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(item.pk, today_item_ids())
        self.assertIn("refreshHome", response["HX-Trigger"])

    def test_today_clear_endpoint_preserves_primary_home(self):
        item = ExecutionItem.objects.filter(
            is_deleted=False,
            status=SystemEnums.ItemStatus.BACKLOG,
        ).first()
        primary = ItemContainerLink.objects.filter(item=item, is_primary=True).first()
        plan_today(item_ids=[item.pk])

        response = self.client.post(
            reverse("today-clear"),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(item.pk, today_item_ids())
        if primary is not None:
            self.assertTrue(ItemContainerLink.objects.filter(pk=primary.pk).exists())


class ReminderSweepTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")

    def test_pending_alert_count(self):
        self.assertGreaterEqual(pending_alert_count(), 1)

    def test_sweep_without_webhook_skips(self):
        result = sweep_reminders()
        self.assertGreaterEqual(result.examined, 1)
        self.assertGreaterEqual(result.skipped + result.sent + result.failed, 1)
