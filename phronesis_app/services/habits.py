# ==============================================================================
# File: phronesis_app/services/habits.py
# Description: VX-05 Habits page context, check/skip, light day streak
# Component: Services / Habits
# Version: 1.0 (Gold Master)
# Created: 2026-07-30
# Last Update: 2026-07-30
# ==============================================================================
"""Optional Habits module helpers — cadence rituals with integer streaks only.

Streak = consecutive local calendar days with status ``done`` ending today.
``skipped`` or a missing day breaks the streak. No points or gamification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction

from phronesis_app.models import DomainCategory, Habit, HabitCheck, SystemEnums
from phronesis_app.services.stability import today_local


@dataclass
class HabitRow:
    """One habit plus today's check and light streak for UI."""

    habit: Habit
    today_check: HabitCheck | None
    streak: int


def compute_habit_streak(habit: Habit, *, as_of: date | None = None) -> int:
    """Consecutive days with ``done`` ending at ``as_of`` (default: owner today)."""
    cursor = as_of or today_local()
    streak = 0
    # Walk backward; stop on skip, missing day, or inactive history gap.
    while True:
        check = (
            HabitCheck.objects.filter(habit=habit, local_date=cursor)
            .only("status")
            .first()
        )
        if check is None or check.status != SystemEnums.HabitCheckStatus.DONE:
            break
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak


def _row_for(habit: Habit, today: date) -> HabitRow:
    today_check = HabitCheck.objects.filter(habit=habit, local_date=today).first()
    return HabitRow(
        habit=habit,
        today_check=today_check,
        streak=compute_habit_streak(habit, as_of=today),
    )


def active_habits_queryset():
    """Active habits with domain for list surfaces."""
    return (
        Habit.objects.filter(is_active=True)
        .select_related("domain")
        .order_by("title", "id")
    )


def build_habits_page(*, include_inactive: bool = False) -> dict:
    """Context for ``/canvas/habits/``."""
    today = today_local()
    qs = Habit.objects.select_related("domain").order_by("-is_active", "title", "id")
    if not include_inactive:
        qs = qs.filter(is_active=True)
    rows = [_row_for(h, today) for h in qs]
    return {
        "surface": "habits",
        "today": today,
        "habit_rows": rows,
        "domains": DomainCategory.objects.filter(is_active=True).order_by("name"),
        "cadence_choices": SystemEnums.HabitCadence.choices,
    }


def build_habits_home_strip(*, limit: int = 6) -> dict:
    """Compact Home strip when ``mod.habits`` is on."""
    today = today_local()
    habits = list(active_habits_queryset()[:limit])
    rows = [_row_for(h, today) for h in habits]
    pending = sum(
        1
        for r in rows
        if r.today_check is None
        or r.today_check.status != SystemEnums.HabitCheckStatus.DONE
    )
    return {
        "habit_rows": rows,
        "today": today,
        "habits_pending": pending,
        "habits_total": len(rows),
    }


@transaction.atomic
def create_habit(
    *,
    title: str,
    cadence: str = SystemEnums.HabitCadence.DAILY,
    domain_id: int | None = None,
) -> Habit:
    """Create an active habit; invalid cadence falls back to daily."""
    title = (title or "").strip()
    if not title:
        raise ValueError("Title is required.")
    valid = {c.value for c in SystemEnums.HabitCadence}
    if cadence not in valid:
        cadence = SystemEnums.HabitCadence.DAILY
    domain = None
    if domain_id:
        domain = DomainCategory.objects.filter(pk=domain_id, is_active=True).first()
    return Habit.objects.create(title=title, cadence=cadence, domain=domain)


@transaction.atomic
def set_habit_check(
    habit_id: int,
    *,
    status: str,
    local_date: date | None = None,
    note: str = "",
) -> HabitCheck:
    """Upsert today's (or given) check as done or skipped."""
    if status not in {
        SystemEnums.HabitCheckStatus.DONE,
        SystemEnums.HabitCheckStatus.SKIPPED,
    }:
        raise ValueError("Status must be done or skipped.")
    habit = Habit.objects.filter(pk=habit_id, is_active=True).first()
    if habit is None:
        raise Habit.DoesNotExist(f"Active habit {habit_id} not found.")
    day = local_date or today_local()
    check, _ = HabitCheck.objects.update_or_create(
        habit=habit,
        local_date=day,
        defaults={
            "status": status,
            "note": (note or "").strip()[:255],
        },
    )
    return check


@transaction.atomic
def clear_habit_check(habit_id: int, *, local_date: date | None = None) -> bool:
    """Remove a check for the day (undo done/skip). Returns True if deleted."""
    day = local_date or today_local()
    deleted, _ = HabitCheck.objects.filter(habit_id=habit_id, local_date=day).delete()
    return deleted > 0


@transaction.atomic
def set_habit_active(habit_id: int, *, is_active: bool) -> Habit:
    """Activate or deactivate a habit without deleting history."""
    habit = Habit.objects.get(pk=habit_id)
    habit.is_active = bool(is_active)
    habit.save(update_fields=["is_active"])
    return habit
