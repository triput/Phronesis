# ==============================================================================
# File: phronesis_app/views/habits.py
# Description: VX-05 Habits surface — list, create, check/skip (mod.habits)
# Component: Surfaces / Habits
# Version: 1.0 (Gold Master)
# Created: 2026-07-30
# Last Update: 2026-07-30
# ==============================================================================
"""Habits page and POST actions gated by ``mod.habits``."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from phronesis_app.models import Habit, SystemEnums
from phronesis_app.services.habits import (
    build_habits_page,
    clear_habit_check,
    create_habit,
    set_habit_active,
    set_habit_check,
)
from phronesis_app.services.modules import require_module


@login_required
@require_module("mod.habits")
def habits_view(request):
    """Render Habits surface — active rituals + today's check/skip."""
    include_inactive = request.GET.get("show") == "all"
    return render(
        request,
        "surfaces/habits.html",
        build_habits_page(include_inactive=include_inactive),
    )


@login_required
@require_module("mod.habits")
@require_POST
def habit_create_view(request):
    """Create a habit from the Habits page form."""
    title = (request.POST.get("title") or "").strip()
    cadence = (request.POST.get("cadence") or SystemEnums.HabitCadence.DAILY).strip()
    raw_domain = (request.POST.get("domain_id") or "").strip()
    domain_id = int(raw_domain) if raw_domain.isdigit() else None
    try:
        create_habit(title=title, cadence=cadence, domain_id=domain_id)
        messages.success(request, "Habit added.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect(reverse("canvas-habits"))


@login_required
@require_module("mod.habits")
@require_POST
def habit_check_view(request, habit_id: int):
    """Mark habit done for today (optional note)."""
    note = (request.POST.get("note") or "").strip()
    try:
        set_habit_check(
            habit_id,
            status=SystemEnums.HabitCheckStatus.DONE,
            note=note,
        )
        messages.success(request, "Marked done.")
    except Habit.DoesNotExist:
        messages.error(request, "Habit not found.")
    except ValueError as exc:
        messages.error(request, str(exc))
    next_url = (request.POST.get("next") or "").strip() or reverse("canvas-habits")
    return redirect(next_url)


@login_required
@require_module("mod.habits")
@require_POST
def habit_skip_view(request, habit_id: int):
    """Mark habit skipped for today (breaks streak; no gamification)."""
    note = (request.POST.get("note") or "").strip()
    try:
        set_habit_check(
            habit_id,
            status=SystemEnums.HabitCheckStatus.SKIPPED,
            note=note,
        )
        messages.info(request, "Skipped for today.")
    except Habit.DoesNotExist:
        messages.error(request, "Habit not found.")
    except ValueError as exc:
        messages.error(request, str(exc))
    next_url = (request.POST.get("next") or "").strip() or reverse("canvas-habits")
    return redirect(next_url)


@login_required
@require_module("mod.habits")
@require_POST
def habit_clear_check_view(request, habit_id: int):
    """Undo today's done/skip mark."""
    clear_habit_check(habit_id)
    messages.info(request, "Cleared today's mark.")
    next_url = (request.POST.get("next") or "").strip() or reverse("canvas-habits")
    return redirect(next_url)


@login_required
@require_module("mod.habits")
@require_POST
def habit_deactivate_view(request, habit_id: int):
    """Deactivate habit; history preserved."""
    try:
        set_habit_active(habit_id, is_active=False)
        messages.info(request, "Habit deactivated.")
    except Habit.DoesNotExist:
        messages.error(request, "Habit not found.")
    return redirect(reverse("canvas-habits"))
