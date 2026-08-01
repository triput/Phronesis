# ==============================================================================
# File: phronesis_app/tests/test_vx11_scheduling.py
# Description: VX-11 tag↔availability gates + VX-14 thin day-overlap display
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-30
# Last Update: 2026-07-30
# ==============================================================================
"""Scheduler tag constraints and cross-midnight plan timeline coverage."""

from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone as django_timezone

from phronesis_app.models import (
    AppSettings,
    ExecutionItem,
    ScheduledAllocation,
    SystemEnums,
    Tag,
    TimeAvailabilityBlock,
)
from phronesis_app.services.plan import plan_blocks_for_day
from phronesis_app.services.scheduler import run_scheduler


class Vx11TagAvailabilityTests(TestCase):
    """Tagged windows only accept matching items; open windows stay open."""

    def setUp(self):
        self.now = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)  # Monday
        django_timezone.activate(dt_timezone.utc)
        settings = AppSettings.get_solo()
        settings.scheduler_buffer_minutes = 0
        settings.calendar_push_enabled = False
        settings.save()
        self.meal = Tag.objects.create(name="meal")
        self.focus = Tag.objects.create(name="focus")

    def tearDown(self):
        django_timezone.deactivate()
        super().tearDown()

    def _monday_block(self, name: str, start: time, end: time, *tags: Tag):
        block = TimeAvailabilityBlock.objects.create(
            name=name,
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
        if tags:
            block.tags.set(tags)
        return block

    def _item(self, title: str, *, minutes: int = 30, tags: list[Tag] | None = None):
        item = ExecutionItem.objects.create(
            title=title,
            status=SystemEnums.ItemStatus.PLANNED,
            priority=2,
            urgency=SystemEnums.UrgencyLevel.NORMAL,
            estimated_minutes=minutes,
        )
        if tags:
            item.tags.set(tags)
        return item

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_tagged_item_uses_matching_restricted_window(self, mock_now):
        mock_now.return_value = self.now
        self._monday_block("Mealtime", time(12, 0), time(13, 0), self.meal)
        item = self._item("Lunch prep", tags=[self.meal])

        result = run_scheduler(horizon_days=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.placed, 1)
        alloc = ScheduledAllocation.objects.get(execution_item=item)
        self.assertEqual(alloc.start_at, self.now.replace(hour=12))

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_untagged_item_cannot_use_restricted_block(self, mock_now):
        mock_now.return_value = self.now
        self._monday_block("Mealtime only", time(9, 0), time(17, 0), self.meal)
        item = self._item("Untagged work")

        result = run_scheduler(horizon_days=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.placed, 0)
        self.assertEqual(result.skipped_no_slot, 1)
        self.assertFalse(ScheduledAllocation.objects.filter(execution_item=item).exists())
        self.assertTrue(any("Untagged work" in w for w in result.warnings))

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_mismatched_tag_cannot_use_restricted_block(self, mock_now):
        mock_now.return_value = self.now
        self._monday_block("Mealtime", time(9, 0), time(17, 0), self.meal)
        item = self._item("Deep work", tags=[self.focus])

        result = run_scheduler(horizon_days=0)

        self.assertEqual(result.placed, 0)
        self.assertEqual(result.skipped_no_slot, 1)
        self.assertFalse(ScheduledAllocation.objects.filter(execution_item=item).exists())

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_open_block_still_accepts_any_item(self, mock_now):
        mock_now.return_value = self.now
        self._monday_block("Open hours", time(9, 0), time(12, 0))
        untagged = self._item("General task")
        tagged = self._item("Tagged task", tags=[self.focus])

        result = run_scheduler(horizon_days=0)

        self.assertEqual(result.placed, 2)
        self.assertTrue(ScheduledAllocation.objects.filter(execution_item=untagged).exists())
        self.assertTrue(ScheduledAllocation.objects.filter(execution_item=tagged).exists())

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_restricted_and_open_blocks_coexist(self, mock_now):
        """When open capacity is full, tagged item still places in its restricted window."""
        mock_now.return_value = self.now
        self._monday_block("Open morning", time(9, 0), time(10, 0))
        self._monday_block("Mealtime", time(12, 0), time(13, 0), self.meal)
        # Fill the open hour so the meal-tagged item must use Mealtime.
        general = self._item("General", minutes=60)
        lunch = self._item("Lunch", minutes=30, tags=[self.meal])

        result = run_scheduler(horizon_days=0)

        self.assertEqual(result.placed, 2)
        self.assertEqual(
            ScheduledAllocation.objects.get(execution_item=general).start_at,
            self.now.replace(hour=9),
        )
        self.assertEqual(
            ScheduledAllocation.objects.get(execution_item=lunch).start_at,
            self.now.replace(hour=12),
        )

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_overbooking_still_blocked_across_tag_windows(self, mock_now):
        """Busy from an open-window placement blocks a later restricted placement."""
        mock_now.return_value = self.now
        # Overlapping clock time: open 9–12 and meal-tagged 9–12.
        self._monday_block("Open", time(9, 0), time(12, 0))
        self._monday_block("Meal", time(9, 0), time(12, 0), self.meal)
        first = self._item("Fills morning", minutes=180, tags=None)
        meal_item = self._item("Needs meal slot", minutes=30, tags=[self.meal])

        result = run_scheduler(horizon_days=0)

        self.assertEqual(result.placed, 1)
        self.assertTrue(ScheduledAllocation.objects.filter(execution_item=first).exists())
        self.assertFalse(ScheduledAllocation.objects.filter(execution_item=meal_item).exists())
        self.assertEqual(result.skipped_no_slot, 1)


class Vx14SpanningDisplayTests(TestCase):
    """Day timeline includes allocations that overlap the day across midnight."""

    def setUp(self):
        django_timezone.activate(dt_timezone.utc)

    def tearDown(self):
        django_timezone.deactivate()
        super().tearDown()

    def test_plan_blocks_include_cross_midnight_allocation(self):
        item = ExecutionItem.objects.create(
            title="Late focus",
            status=SystemEnums.ItemStatus.PLANNED,
            priority=2,
            urgency=SystemEnums.UrgencyLevel.NORMAL,
            estimated_minutes=180,
        )
        start = datetime(2026, 7, 20, 22, 0, tzinfo=dt_timezone.utc)
        end = datetime(2026, 7, 21, 1, 0, tzinfo=dt_timezone.utc)
        ScheduledAllocation.objects.create(
            execution_item=item,
            start_at=start,
            end_at=end,
            source=SystemEnums.AllocationSource.MANUAL,
        )

        day1 = plan_blocks_for_day(date(2026, 7, 20))
        day2 = plan_blocks_for_day(date(2026, 7, 21))

        titles1 = [b.title for b in day1 if b.kind == "allocation"]
        titles2 = [b.title for b in day2 if b.kind == "allocation"]
        self.assertIn("Late focus", titles1)
        self.assertIn("Late focus", titles2)
        # Clipped to local day bounds for display.
        alloc_d1 = next(b for b in day1 if b.title == "Late focus")
        alloc_d2 = next(b for b in day2 if b.title == "Late focus")
        self.assertEqual(alloc_d1.start_at, start)
        self.assertLessEqual(alloc_d1.end_at.date(), date(2026, 7, 20))
        self.assertGreaterEqual(alloc_d2.start_at.date(), date(2026, 7, 21))
        self.assertEqual(alloc_d2.end_at, end)

    @patch("phronesis_app.services.scheduler.timezone.now")
    def test_overnight_availability_places_cross_midnight_allocation(self, mock_now):
        """VX-14 thin: overnight block (end ≤ start) yields one spanning free interval."""
        now = datetime(2026, 7, 20, 20, 0, tzinfo=dt_timezone.utc)  # Monday evening
        mock_now.return_value = now
        settings = AppSettings.get_solo()
        settings.scheduler_buffer_minutes = 0
        settings.calendar_push_enabled = False
        settings.save()
        TimeAvailabilityBlock.objects.create(
            name="Night owl",
            start_time=time(22, 0),
            end_time=time(2, 0),
            day_monday=True,
            day_tuesday=False,
            day_wednesday=False,
            day_thursday=False,
            day_friday=False,
            day_saturday=False,
            day_sunday=False,
        )
        item = ExecutionItem.objects.create(
            title="Long night task",
            status=SystemEnums.ItemStatus.PLANNED,
            priority=1,
            urgency=SystemEnums.UrgencyLevel.NORMAL,
            estimated_minutes=180,
        )

        result = run_scheduler(horizon_days=1)

        self.assertEqual(result.placed, 1)
        alloc = ScheduledAllocation.objects.get(execution_item=item)
        self.assertEqual(alloc.start_at.date(), date(2026, 7, 20))
        self.assertEqual(alloc.end_at.date(), date(2026, 7, 21))
        self.assertGreater(alloc.end_at, alloc.start_at)
