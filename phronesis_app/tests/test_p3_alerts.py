# ==============================================================================
# File: phronesis_app/tests/test_p3_alerts.py
# Description: P3 alert sheet, snooze, acknowledgement, and re-eligibility tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-21
# ==============================================================================
"""Alert lifecycle tests for durable in-app and webhook reminder dispatches."""

from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from phronesis_app.models import AppSettings, ExecutionItem, ReminderDispatch, SystemEnums
from phronesis_app.services.notify import pending_alert_count, sweep_reminders


class AlertLifecycleTests(TestCase):
    """Exercise alert visibility and state transitions through real views."""

    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")
        # Seed reminders would make lifecycle counts non-deterministic and the
        # safety-net sweep may recreate them from seeded due items/allocations.
        ExecutionItem.objects.all().delete()
        self.item = ExecutionItem.objects.create(
            title="Alert lifecycle task",
            status=SystemEnums.ItemStatus.PLANNED,
            priority=SystemEnums.PriorityLevel.HIGH,
        )

    def _dispatch(self, *, status=SystemEnums.ReminderDispatchStatus.PENDING):
        """Create a due dispatch with a test-unique durable key."""
        return ReminderDispatch.objects.create(
            execution_item=self.item,
            kind=SystemEnums.ReminderKind.DUE_APPROACHING,
            status=status,
            fire_at=timezone.now() - timedelta(minutes=1),
            dedupe_key=f"alert-lifecycle-{status}-{ReminderDispatch.objects.count()}",
        )

    def test_alert_sheet_shows_open_dispatches_only(self):
        """Pending and failed rows are actionable; sent history is not."""
        pending = self._dispatch()
        failed = self._dispatch(status=SystemEnums.ReminderDispatchStatus.FAILED)
        sent = self._dispatch(status=SystemEnums.ReminderDispatchStatus.SENT)

        response = self.client.get(reverse("alerts-sheet"), HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("alerts-ack", args=[pending.pk]))
        self.assertContains(response, reverse("alerts-ack", args=[failed.pk]))
        self.assertNotContains(response, reverse("alerts-ack", args=[sent.pk]))

    def test_snooze_sets_future_delay_and_hides_from_due_count(self):
        dispatch = self._dispatch()

        before = timezone.now()
        response = self.client.post(
            reverse("alerts-snooze", args=[dispatch.pk]),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, SystemEnums.ReminderDispatchStatus.SNOOZED)
        self.assertGreaterEqual(dispatch.snooze_until, before + timedelta(minutes=29))
        self.assertEqual(pending_alert_count(), 0)

    @patch("phronesis_app.services.notify.deliver_webhook")
    def test_expired_snooze_becomes_eligible_again(self, mock_deliver):
        """Regression: SNOOZED rows must re-enter the sweep after snooze_until."""
        settings = AppSettings.get_solo()
        settings.notifications_enabled = True
        settings.notification_webhook_url = "https://ntfy.example/phronesis"
        settings.quiet_hours_start = None
        settings.quiet_hours_end = None
        settings.save()
        dispatch = self._dispatch(status=SystemEnums.ReminderDispatchStatus.SNOOZED)
        dispatch.snooze_until = timezone.now() - timedelta(seconds=1)
        dispatch.save(update_fields=["snooze_until", "updated_at"])

        self.assertEqual(pending_alert_count(), 1)
        result = sweep_reminders()

        dispatch.refresh_from_db()
        self.assertEqual(result.sent, 1)
        self.assertEqual(dispatch.status, SystemEnums.ReminderDispatchStatus.SENT)
        mock_deliver.assert_called_once()

    def test_acknowledge_marks_sent_and_requests_glyph_refresh(self):
        dispatch = self._dispatch()

        response = self.client.post(
            reverse("alerts-ack", args=[dispatch.pk]),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Trigger"], "alerts-refresh")
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, SystemEnums.ReminderDispatchStatus.SENT)
        self.assertIsNotNone(dispatch.sent_at)

    def test_alert_mutations_reject_get(self):
        dispatch = self._dispatch()

        snooze = self.client.get(reverse("alerts-snooze", args=[dispatch.pk]))
        acknowledge = self.client.get(reverse("alerts-ack", args=[dispatch.pk]))

        self.assertEqual(snooze.status_code, 405)
        self.assertEqual(acknowledge.status_code, 405)
