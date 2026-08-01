# ==============================================================================
# File: phronesis_app/tests/test_vx01_scheduler_replan.py
# Description: VX-01 — multi-day re-plan scheduler (horizon, replan, due, pinned)
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-31
# Last Update: 2026-07-31
# ==============================================================================
"""VX-01 native greedy re-plan scheduler."""

from datetime import datetime, time, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone as django_timezone

from phronesis_app.models import (
    AppSettings,
    ExecutionItem,
    ScheduledAllocation,
    SystemEnums,
    TimeAvailabilityBlock,
)
from phronesis_app.services.cmd import commit_command, preview_command
from phronesis_app.services.scheduler import run_scheduler


class Vx01SchedulerReplanTests(TestCase):
    """Horizon, re-plan clearing, due ceiling, pinned start, and cmd dispatch."""

    def setUp(self):
        self.now = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)  # Monday
        django_timezone.activate(dt_timezone.utc)
        settings = AppSettings.get_solo()
        settings.scheduler_buffer_minutes = 0
        settings.calendar_push_enabled = False
        settings.scheduler_horizon_days = 7
        settings.scheduler_replan_enabled = False
        settings.save()
        self.client = Client()
        User = get_user_model()
        self.user, _ = User.objects.get_or_create(
            username="vx01owner",
            defaults={"is_staff": True, "is_superuser": True},
        )
        if not self.user.is_superuser:
            self.user.is_superuser = True
            self.user.is_staff = True
            self.user.save(update_fields=["is_superuser", "is_staff"])
        self.client.force_login(self.user)
        TimeAvailabilityBlock.objects.create(
            name="Weekday open",
            start_time=time(9, 0),
            end_time=time(17, 0),
            day_monday=True,
            day_tuesday=True,
            day_wednesday=True,
            day_thursday=True,
            day_friday=True,
        )

    def tearDown(self):
        django_timezone.deactivate()
        super().tearDown()

    def _item(self, title: str, **kwargs):
        defaults = {
            "status": SystemEnums.ItemStatus.PLANNED,
            "priority": 2,
            "urgency": SystemEnums.UrgencyLevel.NORMAL,
            "estimated_minutes": 30,
        }
        defaults.update(kwargs)
        return ExecutionItem.objects.create(title=title, **defaults)

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_horizon_from_settings(self, mock_now):
        mock_now.return_value = self.now
        settings = AppSettings.get_solo()
        settings.scheduler_horizon_days = 3
        settings.save(update_fields=["scheduler_horizon_days", "updated_at"])
        # Fill today+tomorrow so day-3 capacity is required.
        for i in range(16):
            self._item(f"Horizon task {i}", estimated_minutes=60)

        result = run_scheduler()

        self.assertTrue(result.ok)
        self.assertIn("3 day(s)", result.message)
        dates = {a.start_at.date() for a in ScheduledAllocation.objects.all()}
        self.assertTrue(dates)
        self.assertLessEqual(max(dates), (self.now + timedelta(days=2)).date())
        self.assertGreaterEqual(max(dates), (self.now + timedelta(days=1)).date())

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_replan_moves_solver_leaves_manual(self, mock_now):
        mock_now.return_value = self.now
        solver_item = self._item("Solver task")
        manual_item = self._item("Manual task")
        unscheduled = self._item("Fresh task")
        old_start = self.now.replace(hour=14)
        ScheduledAllocation.objects.create(
            execution_item=solver_item,
            start_at=old_start,
            end_at=old_start + timedelta(minutes=30),
            source=SystemEnums.AllocationSource.SOLVER,
        )
        manual_start = self.now.replace(hour=11)
        manual_alloc = ScheduledAllocation.objects.create(
            execution_item=manual_item,
            start_at=manual_start,
            end_at=manual_start + timedelta(minutes=30),
            source=SystemEnums.AllocationSource.MANUAL,
        )

        result = run_scheduler(replan=True, horizon_days=0)

        self.assertEqual(result.cleared, 1)
        manual = ScheduledAllocation.objects.get(pk=manual_alloc.pk)
        self.assertEqual(manual.execution_item_id, manual_item.pk)
        self.assertEqual(manual.start_at, manual_start)
        new_solver = ScheduledAllocation.objects.get(execution_item=solver_item)
        self.assertEqual(new_solver.source, SystemEnums.AllocationSource.SOLVER)
        self.assertNotEqual(new_solver.start_at, old_start)
        self.assertTrue(ScheduledAllocation.objects.filter(execution_item=unscheduled).exists())

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_due_ceiling_skips_late_placement(self, mock_now):
        mock_now.return_value = self.now
        due = self.now.replace(hour=9, minute=15)
        self._item("Too tight", due_at=due, estimated_minutes=30)

        result = run_scheduler(horizon_days=0)

        self.assertEqual(result.placed, 0)
        self.assertEqual(result.skipped_past_due, 1)
        self.assertFalse(ScheduledAllocation.objects.exists())

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_pinned_start_at_exact_placement(self, mock_now):
        mock_now.return_value = self.now
        pinned = self.now.replace(hour=10)
        item = self._item("Pinned", start_at=pinned)

        result = run_scheduler(horizon_days=0)

        self.assertEqual(result.placed, 1)
        self.assertEqual(result.pinned, 1)
        alloc = ScheduledAllocation.objects.get(execution_item=item)
        self.assertEqual(alloc.start_at, pinned)

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_pinned_start_infeasible_falls_back(self, mock_now):
        mock_now.return_value = self.now
        blocker = self._item("Blocker", estimated_minutes=60)
        ScheduledAllocation.objects.create(
            execution_item=blocker,
            start_at=self.now.replace(hour=10),
            end_at=self.now.replace(hour=11),
            source=SystemEnums.AllocationSource.MANUAL,
        )
        pinned = self.now.replace(hour=10, minute=15)
        item = self._item("Pinned fallback", start_at=pinned)

        result = run_scheduler(horizon_days=0)

        self.assertEqual(result.placed, 1)
        self.assertEqual(result.pinned, 0)
        alloc = ScheduledAllocation.objects.get(execution_item=item)
        self.assertNotEqual(alloc.start_at, pinned)
        self.assertTrue(any("Pinned start infeasible" in w for w in result.warnings))

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_cmd_schedule_replan_forces_replan(self, mock_now):
        mock_now.return_value = self.now
        placed_item = self._item("Already placed")
        ScheduledAllocation.objects.create(
            execution_item=placed_item,
            start_at=self.now.replace(hour=15),
            end_at=self.now.replace(hour=15, minute=30),
            source=SystemEnums.AllocationSource.SOLVER,
        )
        self._item("Needs slot")

        preview = preview_command("schedule replan")
        self.assertEqual(preview.mode, "do")
        result = commit_command("schedule replan")
        self.assertTrue(result.ok)
        self.assertIn("Scheduled", result.message)

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_schedule_run_view_replan_post(self, mock_now):
        mock_now.return_value = self.now
        placed_item = self._item("Solver slot")
        ScheduledAllocation.objects.create(
            execution_item=placed_item,
            start_at=self.now.replace(hour=13),
            end_at=self.now.replace(hour=13, minute=30),
            source=SystemEnums.AllocationSource.SOLVER,
        )
        self._item("New work")

        response = self.client.post(
            reverse("schedule-run"),
            {"replan": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scheduled")
        self.assertContains(response, "Cleared")
