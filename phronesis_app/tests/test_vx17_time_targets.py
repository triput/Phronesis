# ==============================================================================
# File: phronesis_app/tests/test_vx17_time_targets.py
# Description: VX-17 weekly time targets — progress math + Settings CRUD
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-30
# Last Update: 2026-07-30
# ==============================================================================
"""Weekly TimeTarget progress rule and Settings Targets CRUD."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from phronesis_app.models import (
    DomainCategory,
    ExecutionItem,
    FocusSession,
    ItemContainerLink,
    ScheduledAllocation,
    SystemEnums,
    Tag,
    TimeTarget,
    WorkspaceContainer,
)
from phronesis_app.services.settings_surface import (
    create_time_target,
    delete_time_target,
    update_time_target,
)
from phronesis_app.services.time_targets import compute_target_progress, local_week_bounds


class TimeTargetProgressTests(TestCase):
    """Progress = focus seconds + allocation minutes only when focus is zero."""

    def setUp(self):
        self.domain = DomainCategory.objects.create(name="Tech", slug="tech")
        self.other = DomainCategory.objects.create(name="Home", slug="home")
        self.tag = Tag.objects.create(name="deep-work")
        self.container = WorkspaceContainer.objects.create(
            title="Tech Epic",
            slug="tech-epic",
            domain=self.domain,
        )
        self.item = ExecutionItem.objects.create(title="Ship VX-17")
        ItemContainerLink.objects.create(
            item=self.item, container=self.container, is_primary=True
        )
        self.item.tags.add(self.tag)
        self.target = TimeTarget.objects.create(
            domain=self.domain, minutes_per_week=120
        )
        self.week_start, self.week_end = local_week_bounds()

    def test_focus_only_counts_toward_progress(self):
        FocusSession.objects.create(
            execution_item=self.item,
            started_at=self.week_start + timedelta(hours=1),
            ended_at=self.week_start + timedelta(hours=1, minutes=30),
            duration_seconds=1800,
            end_reason=SystemEnums.FocusEndReason.COMPLETE,
        )
        # Allocation on same item must NOT double-count when focus > 0
        ScheduledAllocation.objects.create(
            execution_item=self.item,
            start_at=self.week_start + timedelta(hours=3),
            end_at=self.week_start + timedelta(hours=4),
            source=SystemEnums.AllocationSource.MANUAL,
        )
        progress = compute_target_progress(self.target)
        self.assertEqual(progress.focus_seconds, 1800)
        self.assertEqual(progress.allocation_minutes, 0)
        self.assertEqual(progress.progress_minutes, 30)

    def test_allocation_counts_when_zero_focus(self):
        ScheduledAllocation.objects.create(
            execution_item=self.item,
            start_at=self.week_start + timedelta(hours=2),
            end_at=self.week_start + timedelta(hours=3),
            source=SystemEnums.AllocationSource.MANUAL,
        )
        progress = compute_target_progress(self.target)
        self.assertEqual(progress.focus_seconds, 0)
        self.assertEqual(progress.allocation_minutes, 60)
        self.assertEqual(progress.progress_minutes, 60)

    def test_tag_target_matches_tagged_items(self):
        tag_target = TimeTarget.objects.create(tag=self.tag, minutes_per_week=60)
        FocusSession.objects.create(
            execution_item=self.item,
            started_at=self.week_start + timedelta(hours=1),
            ended_at=self.week_start + timedelta(hours=1, minutes=45),
            duration_seconds=2700,
            end_reason=SystemEnums.FocusEndReason.COMPLETE,
        )
        progress = compute_target_progress(tag_target)
        self.assertEqual(progress.progress_minutes, 45)

    def test_domain_and_tag_requires_both(self):
        combo = TimeTarget.objects.create(
            domain=self.domain, tag=self.tag, minutes_per_week=60
        )
        # Item matches both → counts
        FocusSession.objects.create(
            execution_item=self.item,
            started_at=self.week_start + timedelta(hours=1),
            ended_at=self.week_start + timedelta(hours=1, minutes=10),
            duration_seconds=600,
            end_reason=SystemEnums.FocusEndReason.COMPLETE,
        )
        self.assertEqual(compute_target_progress(combo).progress_minutes, 10)

        # Untagged item in same domain does not count
        bare = ExecutionItem.objects.create(title="No tags")
        ItemContainerLink.objects.create(
            item=bare, container=self.container, is_primary=True
        )
        FocusSession.objects.create(
            execution_item=bare,
            started_at=self.week_start + timedelta(hours=2),
            ended_at=self.week_start + timedelta(hours=2, minutes=20),
            duration_seconds=1200,
            end_reason=SystemEnums.FocusEndReason.COMPLETE,
        )
        self.assertEqual(compute_target_progress(combo).progress_minutes, 10)

    def test_other_domain_excluded(self):
        home_box = WorkspaceContainer.objects.create(
            title="Home", slug="home-box", domain=self.other
        )
        other_item = ExecutionItem.objects.create(title="Laundry")
        ItemContainerLink.objects.create(
            item=other_item, container=home_box, is_primary=True
        )
        FocusSession.objects.create(
            execution_item=other_item,
            started_at=self.week_start + timedelta(hours=1),
            ended_at=self.week_start + timedelta(hours=2),
            duration_seconds=3600,
            end_reason=SystemEnums.FocusEndReason.COMPLETE,
        )
        self.assertEqual(compute_target_progress(self.target).progress_minutes, 0)


class TimeTargetCrudTests(TestCase):
    """Settings Targets tab CRUD via service + HTTP."""

    def setUp(self):
        self.User = get_user_model()
        self.owner = self.User.objects.create_superuser(
            "owner",
            "owner@example.com",
            "OwnerPass123!",
        )
        self.client = Client()
        self.client.login(username="owner", password="OwnerPass123!")
        self.domain = DomainCategory.objects.create(name="Academy", slug="academy")
        self.tag = Tag.objects.create(name="study")

    def test_create_requires_domain_or_tag(self):
        result = create_time_target(minutes_per_week=60)
        self.assertFalse(result.ok)

    def test_create_update_delete(self):
        result = create_time_target(minutes_per_week=90, domain_id=self.domain.pk)
        self.assertTrue(result.ok)
        target = TimeTarget.objects.get()
        self.assertEqual(target.minutes_per_week, 90)

        result = update_time_target(
            target.pk, minutes_per_week=180, domain_id=self.domain.pk
        )
        self.assertTrue(result.ok)
        target.refresh_from_db()
        self.assertEqual(target.minutes_per_week, 180)

        result = delete_time_target(target.pk)
        self.assertTrue(result.ok)
        self.assertEqual(TimeTarget.objects.count(), 0)

    def test_unique_domain_only(self):
        create_time_target(minutes_per_week=60, domain_id=self.domain.pk)
        dup = create_time_target(minutes_per_week=30, domain_id=self.domain.pk)
        self.assertFalse(dup.ok)

    def test_settings_targets_tab_crud_http(self):
        response = self.client.get(reverse("canvas-settings") + "?tab=targets")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Weekly time targets")

        response = self.client.post(
            reverse("settings-target-create"),
            {
                "settings_tab": "targets",
                "domain_id": str(self.domain.pk),
                "tag_id": "",
                "minutes_per_week": "150",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TimeTarget.objects.count(), 1)
        target = TimeTarget.objects.get()
        self.assertEqual(target.minutes_per_week, 150)

        response = self.client.post(
            reverse("settings-target-delete", args=[target.pk]),
            {"settings_tab": "targets"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TimeTarget.objects.count(), 0)

    def test_plan_strip_when_targets_exist(self):
        TimeTarget.objects.create(domain=self.domain, minutes_per_week=60)
        response = self.client.get(reverse("canvas-plan"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="plan-time-targets-strip"')
        self.assertContains(response, "Academy")
