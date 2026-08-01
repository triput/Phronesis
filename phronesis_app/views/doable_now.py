# ==============================================================================
# File: phronesis_app/views/doable_now.py
# Description: VX-04 Doable now HTMX fragments and context-tag session POST
# Component: Surfaces / Doable Now
# Version: 1.0 (Gold Master)
# Created: 2026-07-31
# Last Update: 2026-07-31
# ==============================================================================
"""HTMX partials and session context-tag toggles for the doable-now lens."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_POST

from phronesis_app.services.doable_now import (
    build_doable_now_context,
    set_session_context_tag_ids,
)
from phronesis_app.services.modules import is_enabled


def _strip_context(request) -> dict:
    """Shared context for doable-now partials."""
    ctx = build_doable_now_context(request=request)
    ctx["show_doable_now"] = is_enabled("mod.doable_now")
    return ctx


@login_required
def fragment_doable_now_strip(request):
    """HTMX partial for Home doable-now strip."""
    return render(request, "partials/doable_now_strip.html", _strip_context(request))


@login_required
@require_POST
def doable_now_context_view(request):
    """Set or clear session context tag filter; refresh doable-now partial."""
    raw = request.POST.getlist("tag_ids")
    if request.POST.get("clear") == "1" or not raw:
        set_session_context_tag_ids(request.session, None)
    else:
        tag_ids = [int(x) for x in raw if str(x).strip().isdigit()]
        set_session_context_tag_ids(request.session, tag_ids or None)

    target = request.POST.get("target", "home")
    if target == "plan":
        from phronesis_app.services.plan import planner_context

        ctx = planner_context(request=request)
        ctx["show_doable_now"] = is_enabled("mod.doable_now")
        return render(request, "partials/plan_doable_now_panel.html", ctx)

    return render(request, "partials/doable_now_strip.html", _strip_context(request))
