# ==============================================================================
# File: phronesis_app/views/plan.py
# Description: Planner surface and P3 time endpoints (+ VX-16 Truncated Today)
# Component: Surfaces / Plan
# Version: 1.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-30
# ==============================================================================
"""Planner / Agenda — allocations, calendar overlay, schedule & today actions."""

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_POST

from phronesis_app.models import SystemEnums
from phronesis_app.services.plan import planner_context
from phronesis_app.services.scheduler import run_scheduler
from phronesis_app.services.today import (
    SESSION_SHOW_ALL_KEY,
    clear_today,
    plan_today,
    set_today_visible_limit,
)
from phronesis_app.views.htmx import set_cockpit_refresh, set_hx_trigger


def _today_panel_response(request, **extra):
    """Render #today panel with session-aware truncation."""
    ctx = planner_context(request=request)
    ctx.update(extra)
    return render(request, "partials/plan_today_panel.html", ctx)


@login_required
def plan_view(request):
    """Day timeline planner with #today sidebar."""
    day_str = request.GET.get("day")
    day = None
    if day_str:
        try:
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
        except ValueError:
            day = None
    ctx = planner_context(day, request=request)
    calendar_provider = request.GET.get(
        "calendar_provider",
        SystemEnums.CalendarProvider.GOOGLE,
    )
    calendar_label = (
        "Outlook / Microsoft 365"
        if calendar_provider == SystemEnums.CalendarProvider.MICROSOFT
        else "Google Calendar"
    )
    if request.GET.get("calendar_connected") == "1":
        ctx["calendar_message"] = f"{calendar_label} connected. Click Sync now to pull events."
        ctx["calendar_ok"] = True
    elif request.GET.get("calendar_error") == "oauth_not_configured":
        ctx["calendar_message"] = ctx.get("oauth_setup_message", "Google OAuth is not configured.")
        ctx["calendar_ok"] = False
    elif request.GET.get("calendar_error") == "oauth_invalid":
        detail = request.GET.get("calendar_error_detail", "")
        ctx["calendar_message"] = detail or ctx.get(
            "oauth_setup_message", "Invalid OAuth client configuration."
        )
        ctx["calendar_ok"] = False
    elif request.GET.get("calendar_error") == "oauth_exchange":
        detail = request.GET.get("calendar_error_detail", "")
        ctx["calendar_message"] = f"{calendar_label} authorization failed: {detail}"
        ctx["calendar_ok"] = False
    return render(request, "surfaces/plan.html", ctx)


@login_required
@require_POST
def schedule_run_view(request):
    """Run deterministic scheduler; refresh planner fragment."""
    result = run_scheduler()
    ctx = planner_context(request=request)
    msg = result.message
    if result.warnings:
        # Surface first few item-level placement failures (VX-11 overbooking / tag miss).
        detail = " ".join(result.warnings[:3])
        if len(result.warnings) > 3:
            detail += f" (+{len(result.warnings) - 3} more)"
        msg = f"{msg} {detail}"
    ctx["schedule_message"] = msg
    ctx["schedule_ok"] = result.ok and result.skipped_no_slot == 0
    response = render(request, "partials/plan_timeline.html", ctx)
    if result.ok:
        set_hx_trigger(response, "plan-reload")
    return response


@login_required
@require_POST
def today_plan_view(request):
    """Multi-home items onto #today (optional item_ids CSV)."""
    raw_ids = request.POST.get("item_ids", "")
    item_ids = [int(x) for x in raw_ids.split(",") if x.strip().isdigit()] or None
    query = request.POST.get("query", "")
    result = plan_today(item_ids=item_ids, query=query)
    response = _today_panel_response(request, today_message=result.message)
    set_cockpit_refresh(response)
    return response


@login_required
@require_POST
def today_clear_view(request):
    """Remove non-primary #today links."""
    result = clear_today()
    response = _today_panel_response(request, today_message=result.message)
    set_cockpit_refresh(response)
    return response


@login_required
@require_POST
def today_expand_view(request):
    """VX-16 — toggle Show all vs Focus next N for #today panel."""
    show_all = request.POST.get("show_all", "1") in ("1", "true", "on", "yes")
    request.session[SESSION_SHOW_ALL_KEY] = show_all
    return _today_panel_response(request)


@login_required
@require_POST
def today_visible_limit_view(request):
    """VX-16 — persist Truncated Today N (1–20)."""
    raw = request.POST.get("limit", "")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 5
    set_today_visible_limit(n)
    request.session[SESSION_SHOW_ALL_KEY] = False
    return _today_panel_response(request)
