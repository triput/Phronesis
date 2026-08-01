# ==============================================================================
# File: phronesis_app/tests/test_vx05_habits.py
# Description: VX-05 optional Habits module — gate, check/skip, Simple rail
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-30
# Last Update: 2026-07-30
# ==============================================================================
"""Habits (`mod.habits`) — module gate, done/skip/streak, Simple hides rail."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from phronesis_app.models import Habit, HabitCheck, SystemEnums
from phronesis_app.services.habits import compute_habit_streak, create_habit, set_habit_check
from phronesis_app.services.modules import apply_preset, is_enabled, set_modules
from phronesis_app.services.stability import today_local


class HabitsModuleTests(TestCase):
    """Exercise VX-05 Habits gating and check/skip behavior."""

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

    def test_simple_disables_habits_module(self):
        self.assertFalse(is_enabled("mod.habits"))

    def test_simple_hides_habits_from_rail(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "canvas-habits")
        body = response.content.decode("utf-8")
        self.assertNotIn('data-testid="habits-home-strip"', body)

    def test_full_shows_habits_on_rail(self):
        apply_preset("full")
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("canvas-habits"))

    def test_direct_habits_url_redirects_when_off(self):
        response = self.client.get(reverse("canvas-habits"))
        self.assertRedirects(response, reverse("home"))

    def test_direct_habits_url_ok_when_on(self):
        apply_preset("full")
        response = self.client.get(reverse("canvas-habits"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Habits")

    def test_check_and_skip_and_streak(self):
        set_modules({"mod.habits": True})
        habit = create_habit(title="Water plants", cadence=SystemEnums.HabitCadence.DAILY)
        today = today_local()

        # Two prior done days + today → streak 3
        HabitCheck.objects.create(
            habit=habit,
            local_date=today - timedelta(days=2),
            status=SystemEnums.HabitCheckStatus.DONE,
        )
        HabitCheck.objects.create(
            habit=habit,
            local_date=today - timedelta(days=1),
            status=SystemEnums.HabitCheckStatus.DONE,
        )
        response = self.client.post(reverse("habit-check", args=[habit.pk]))
        self.assertRedirects(response, reverse("canvas-habits"))
        check = HabitCheck.objects.get(habit=habit, local_date=today)
        self.assertEqual(check.status, SystemEnums.HabitCheckStatus.DONE)
        self.assertEqual(compute_habit_streak(habit, as_of=today), 3)

        # Skip today breaks streak (skip ≠ done)
        response = self.client.post(reverse("habit-skip", args=[habit.pk]))
        self.assertRedirects(response, reverse("canvas-habits"))
        check.refresh_from_db()
        self.assertEqual(check.status, SystemEnums.HabitCheckStatus.SKIPPED)
        self.assertEqual(compute_habit_streak(habit, as_of=today), 0)

    def test_home_strip_when_habits_on(self):
        set_modules({"mod.habits": True})
        create_habit(title="Floss")
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="habits-home-strip"')
        self.assertContains(response, "Floss")

    def test_set_habit_check_service_rejects_inactive(self):
        habit = create_habit(title="Meditate")
        habit.is_active = False
        habit.save(update_fields=["is_active"])
        with self.assertRaises(Habit.DoesNotExist):
            set_habit_check(habit.pk, status=SystemEnums.HabitCheckStatus.DONE)
