# ==============================================================================
# File: phronesis_app/tests/test_vx04_doable_now.py
# Description: VX-04 doable-now lens — availability, tags, deps, module gate
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-31
# Last Update: 2026-07-31
# ==============================================================================
"""Doable now (`mod.doable_now`) — fits-this-moment ranking and surfaces."""

from datetime import datetime, time, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone as django_timezone

from phronesis_app.models import (
    AppSettings,
    ExecutionItem,
    ItemDependencyLink,
    ScheduledAllocation,
    SystemEnums,
    Tag,
    TimeAvailabilityBlock,
    WorkspaceContainer,
)
from phronesis_app.services.cmd import commit_command, preview_command
from phronesis_app.services.doable_now import doable_now_items
from phronesis_app.services.modules import apply_preset, is_enabled, set_modules
from phronesis_app.services.today import plan_today


class Vx04DoableNowServiceTests(TestCase):
    """Core doable-now availability math and filters."""

    def setUp(self):
        self.now = datetime(2026, 7, 20, 10, 0, tzinfo=dt_timezone.utc)  # Monday 10:00
        django_timezone.activate(dt_timezone.utc)
        settings = AppSettings.get_solo()
        settings.scheduler_buffer_minutes = 0
        settings.save()
        self.meal = Tag.objects.create(name="meal")
        self.focus = Tag.objects.create(name="focus")
        self.home = Tag.objects.create(name="home")

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

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_tagged_item_in_matching_window_is_doable(self, mock_now):
        mock_now.return_value = self.now
        self._monday_block("Morning", time(9, 0), time(12, 0), self.focus)
        item = self._item("Deep work", tags=[self.focus])

        rows = doable_now_items()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].item.pk, item.pk)
        self.assertEqual(rows[0].slot_start, self.now)

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_untagged_item_excluded_from_restricted_block(self, mock_now):
        mock_now.return_value = self.now
        self._monday_block("Meal only", time(9, 0), time(17, 0), self.meal)
        self._item("Untagged work")

        rows = doable_now_items()

        self.assertEqual(rows, [])

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_duration_too_long_excluded(self, mock_now):
        mock_now.return_value = self.now
        self._monday_block("Short window", time(10, 0), time(10, 30))
        self._item("Too long", minutes=60)

        rows = doable_now_items()

        self.assertEqual(rows, [])

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_later_today_window_not_doable_yet(self, mock_now):
        """Future open windows today are scheduler territory, not doable-now."""
        mock_now.return_value = self.now  # 10:00
        self._monday_block("Afternoon", time(14, 0), time(17, 0))
        self._item("Later chore", minutes=30)

        rows = doable_now_items()

        self.assertEqual(rows, [])

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_before_window_start_not_doable(self, mock_now):
        mock_now.return_value = self.now.replace(hour=8, minute=0)
        self._monday_block("Morning", time(9, 0), time(12, 0))
        self._item("Not yet", minutes=30)

        rows = doable_now_items()

        self.assertEqual(rows, [])

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_overnight_window_covering_now_is_doable(self, mock_now):
        """VX-14 overnight block from prior evening still covering post-midnight now."""
        tuesday_0130 = datetime(2026, 7, 21, 1, 30, tzinfo=dt_timezone.utc)
        mock_now.return_value = tuesday_0130
        # Monday overnight 22:00 → 02:00 Tuesday
        TimeAvailabilityBlock.objects.create(
            name="Night",
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
        item = self._item("Night task", minutes=30)

        rows = doable_now_items(now=tuesday_0130)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].item.pk, item.pk)
        self.assertEqual(rows[0].slot_start, tuesday_0130)

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_busy_interval_blocks_doable(self, mock_now):
        mock_now.return_value = self.now
        self._monday_block("Open", time(9, 0), time(12, 0))
        item = self._item("Blocked task", minutes=30)
        ScheduledAllocation.objects.create(
            execution_item=ExecutionItem.objects.create(
                title="Other",
                status=SystemEnums.ItemStatus.PLANNED,
                estimated_minutes=30,
            ),
            start_at=self.now,
            end_at=self.now.replace(hour=12),
            source=SystemEnums.AllocationSource.MANUAL,
        )

        rows = doable_now_items()

        ids = {r.item.pk for r in rows}
        self.assertNotIn(item.pk, ids)

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_blocked_dependency_excluded(self, mock_now):
        mock_now.return_value = self.now
        self._monday_block("Open", time(9, 0), time(17, 0))
        blocker = self._item("Blocker", minutes=15)
        blocked = self._item("Blocked", minutes=15)
        ItemDependencyLink.objects.create(
            from_item=blocked,
            to_item=blocker,
            link_type=SystemEnums.DependencyLinkType.BLOCKS,
        )

        rows = doable_now_items()

        self.assertEqual([r.item.pk for r in rows], [blocker.pk])

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_context_tag_filter(self, mock_now):
        mock_now.return_value = self.now
        self._monday_block("Open", time(9, 0), time(17, 0))
        home_item = self._item("Home chore", tags=[self.home])
        self._item("Office work", tags=[self.focus])

        rows = doable_now_items(context_tag_ids=[self.home.pk])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].item.pk, home_item.pk)

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_prefer_today_ranking(self, mock_now):
        mock_now.return_value = self.now
        self._monday_block("Open", time(9, 0), time(17, 0))
        WorkspaceContainer.objects.create(
            title="Today",
            slug="today",
            container_type=SystemEnums.ContainerType.LIST,
        )
        high = self._item("High priority", minutes=15)
        high.priority = 1
        high.save()
        today_item = self._item("Today item", minutes=15)
        plan_today(item_ids=[today_item.pk])

        rows = doable_now_items(prefer_today=True)

        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0].item.pk, today_item.pk)
        self.assertTrue(rows[0].is_today)

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_inbox_item_excluded(self, mock_now):
        mock_now.return_value = self.now
        self._monday_block("Open", time(9, 0), time(17, 0))
        ExecutionItem.objects.create(
            title="Inbox capture",
            status=SystemEnums.ItemStatus.INBOX,
            estimated_minutes=15,
        )

        rows = doable_now_items()

        self.assertEqual(rows, [])


class Vx04DoableNowSurfaceTests(TestCase):
    """Module gate and Home/Plan smoke."""

    def setUp(self):
        self.User = get_user_model()
        self.owner = self.User.objects.create_superuser(
            "owner",
            "owner@example.com",
            "OwnerPass123!",
        )
        self.client = Client()
        self.client.login(username="owner", password="OwnerPass123!")
        apply_preset("simple")
        django_timezone.activate(dt_timezone.utc)
        settings = AppSettings.get_solo()
        # Middleware activates AppSettings.timezone on each request; keep it UTC so
        # mocked ``now`` stays inside the 08:00–18:00 availability window.
        settings.timezone = "UTC"
        settings.scheduler_buffer_minutes = 0
        settings.save()
        TimeAvailabilityBlock.objects.create(
            name="Weekday",
            start_time=time(8, 0),
            end_time=time(18, 0),
            day_monday=True,
            day_tuesday=True,
            day_wednesday=True,
            day_thursday=True,
            day_friday=True,
            day_saturday=True,
            day_sunday=True,
        )
        self.now = datetime(2026, 7, 20, 10, 0, tzinfo=dt_timezone.utc)

    def tearDown(self):
        django_timezone.deactivate()
        super().tearDown()

    def test_simple_hides_doable_now_strip(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(is_enabled("mod.doable_now"))
        self.assertNotContains(response, 'data-testid="doable-now-home-strip"')

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_full_shows_doable_now_on_home(self, mock_now):
        mock_now.return_value = self.now
        apply_preset("full")
        ExecutionItem.objects.create(
            title="Quick win",
            status=SystemEnums.ItemStatus.PLANNED,
            estimated_minutes=20,
        )
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="doable-now-home-strip"')
        self.assertContains(response, "Quick win")

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_plan_shows_doable_badge_on_today_item(self, mock_now):
        mock_now.return_value = self.now
        set_modules({"mod.doable_now": True})
        WorkspaceContainer.objects.create(
            title="Today",
            slug="today",
            container_type=SystemEnums.ContainerType.LIST,
        )
        item = ExecutionItem.objects.create(
            title="Plan fit",
            status=SystemEnums.ItemStatus.PLANNED,
            estimated_minutes=25,
        )
        plan_today(item_ids=[item.pk])
        response = self.client.get(reverse("canvas-plan"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="plan-doable-now-panel"')
        self.assertContains(response, 'data-testid="doable-now-badge"')
        self.assertContains(response, "Plan fit")

    def test_cmd_doable_now_preview_when_off(self):
        preview = preview_command("doable now")
        self.assertEqual(preview.mode, "do")
        self.assertIn("off", preview.summary.lower())

    @patch("phronesis_app.services.doable_now.timezone.now")
    def test_cmd_doable_now_when_on(self, mock_now):
        mock_now.return_value = self.now
        set_modules({"mod.doable_now": True})
        ExecutionItem.objects.create(
            title="Palette fit",
            status=SystemEnums.ItemStatus.PLANNED,
            estimated_minutes=15,
        )
        preview = preview_command("doable now")
        self.assertIn("Palette fit", preview.summary)
        result = commit_command("doable now")
        self.assertTrue(result.ok)
        self.assertIn("Palette fit", result.message)
