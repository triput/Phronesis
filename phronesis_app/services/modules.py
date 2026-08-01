# ==============================================================================
# File: phronesis_app/services/modules.py
# Description: VN-A03 Simple/Full cockpit module flags and gating helpers
# Component: Services / Modules
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-30
# ==============================================================================
"""Optional surface modules for Todoist+ Simple vs Full cockpit presets.

Core spine (home, capture, inbox, matrix, today/plan, focus, search, settings,
alerts) is always on. Optional ``mod.*`` flags hide rail links, Cmd go-targets,
Home chrome, and soft-redirect direct URLs when disabled. Turning a module off
never deletes data.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

# Spec: docs/PHRONESIS_V3_MODULES.md
OPTIONAL_MODULES: tuple[str, ...] = (
    "mod.academy",
    "mod.boards",
    "mod.habits",
    "mod.overview",
    "mod.analytics",
    "mod.telemetry",
    "mod.stability",
    "mod.bulk",
    "mod.templates",
    "mod.calendar_grid",
    "mod.saved_views",
    "mod.availability",
)

MODULE_LABELS: dict[str, str] = {
    "mod.academy": "Academy",
    "mod.boards": "Boards",
    "mod.habits": "Habits",
    "mod.overview": "Overview",
    "mod.analytics": "Analytics",
    "mod.telemetry": "Telemetry HUD",
    "mod.stability": "Stability",
    "mod.bulk": "Bulk Add",
    "mod.templates": "Workspace templates",
    "mod.calendar_grid": "Calendar grid",
    "mod.saved_views": "Saved views",
    "mod.availability": "Availability editor",
}

SIMPLE_DEFAULTS: dict[str, bool] = {mid: False for mid in OPTIONAL_MODULES}
FULL_DEFAULTS: dict[str, bool] = {mid: True for mid in OPTIONAL_MODULES}

PRESET_SIMPLE = "simple"
PRESET_FULL = "full"
PRESET_CUSTOM = "custom"
VALID_PRESETS = frozenset({PRESET_SIMPLE, PRESET_FULL, PRESET_CUSTOM})

# Django url_name → required optional module (None = always allowed)
URL_MODULE_GATES: dict[str, str | None] = {
    "home": None,
    "canvas-inbox": None,
    "canvas-matrix": None,
    "canvas-plan": None,
    "canvas-trash": None,
    "canvas-settings": None,
    "canvas-bulk": "mod.bulk",
    "canvas-overview": "mod.overview",
    "canvas-board": "mod.boards",
    "canvas-academy": "mod.academy",
    "canvas-habits": "mod.habits",
    "canvas-analytics": "mod.analytics",
    "canvas-plan-calendar": "mod.calendar_grid",
    "telemetry-hud": "mod.telemetry",
    "stability-hud": "mod.stability",
}

RAIL_LINKS: tuple[dict[str, Any], ...] = (
    {"label": "Home", "url_name": "home", "surface": "home", "module": None},
    {"label": "Inbox", "url_name": "canvas-inbox", "surface": "inbox", "module": None},
    {"label": "Matrix", "url_name": "canvas-matrix", "surface": "matrix", "module": None},
    {"label": "Bulk Add", "url_name": "canvas-bulk", "surface": "bulk", "module": "mod.bulk"},
    {"label": "Overview", "url_name": "canvas-overview", "surface": "overview", "module": "mod.overview"},
    {"label": "Planner", "url_name": "canvas-plan", "surface": "plan", "module": None},
    {"label": "Trash", "url_name": "canvas-trash", "surface": "trash", "module": None},
    {"label": "Boards", "url_name": "canvas-board", "surface": "board", "module": "mod.boards"},
    {"label": "Habits", "url_name": "canvas-habits", "surface": "habits", "module": "mod.habits"},
    {"label": "Academy", "url_name": "canvas-academy", "surface": "academy", "module": "mod.academy"},
    {"label": "Analytics", "url_name": "canvas-analytics", "surface": "analytics", "module": "mod.analytics"},
    {"label": "Settings", "url_name": "canvas-settings", "surface": "settings", "module": None},
)


def _solo_settings():
    from phronesis_app.models import AppSettings

    return AppSettings.get_solo()


def simple_defaults() -> dict[str, bool]:
    """Return a fresh Simple preset map."""
    return dict(SIMPLE_DEFAULTS)


def full_defaults() -> dict[str, bool]:
    """Return a fresh Full cockpit map."""
    return dict(FULL_DEFAULTS)


def resolve_modules(settings_obj=None) -> dict[str, bool]:
    """Merge stored JSON with Simple defaults for any missing keys."""
    if settings_obj is None:
        try:
            settings_obj = _solo_settings()
        except Exception:
            return simple_defaults()
    stored = getattr(settings_obj, "modules_enabled", None) or {}
    if not isinstance(stored, dict):
        stored = {}
    out = simple_defaults()
    for mid in OPTIONAL_MODULES:
        if mid in stored:
            out[mid] = bool(stored[mid])
    return out


def is_enabled(module_id: str, settings_obj=None) -> bool:
    """Return True if an optional module is on (core modules always True)."""
    if not module_id or module_id.startswith("core."):
        return True
    if module_id not in OPTIONAL_MODULES:
        return True
    return bool(resolve_modules(settings_obj).get(module_id, False))


def template_modules_map(settings_obj=None) -> dict[str, bool]:
    """Template-friendly keys: mod_academy instead of mod.academy."""
    resolved = resolve_modules(settings_obj)
    return {mid.replace(".", "_"): enabled for mid, enabled in resolved.items()}


def rail_links_for(settings_obj=None) -> list[dict[str, Any]]:
    """Rail entries visible under current module flags."""
    resolved = resolve_modules(settings_obj)
    links: list[dict[str, Any]] = []
    for spec in RAIL_LINKS:
        mod = spec["module"]
        if mod is None or resolved.get(mod, False):
            links.append(
                {
                    "label": spec["label"],
                    "url_name": spec["url_name"],
                    "surface": spec["surface"],
                    "module": mod,
                }
            )
    return links


def apply_preset(preset: str, settings_obj=None):
    """Write Simple or Full module map and preset; returns AppSettings."""
    settings_obj = settings_obj or _solo_settings()
    preset = (preset or PRESET_SIMPLE).strip().lower()
    if preset == PRESET_FULL:
        settings_obj.ui_preset = PRESET_FULL
        settings_obj.modules_enabled = full_defaults()
    else:
        settings_obj.ui_preset = PRESET_SIMPLE
        settings_obj.modules_enabled = simple_defaults()
    settings_obj.save()
    return settings_obj


def set_modules(modules: dict[str, bool], settings_obj=None, *, mark_custom: bool = True):
    """Persist a full or partial module map; mark custom when diverging from presets."""
    settings_obj = settings_obj or _solo_settings()
    current = resolve_modules(settings_obj)
    for mid, enabled in (modules or {}).items():
        if mid in OPTIONAL_MODULES:
            current[mid] = bool(enabled)
    settings_obj.modules_enabled = current
    if mark_custom:
        if current == FULL_DEFAULTS:
            settings_obj.ui_preset = PRESET_FULL
        elif current == SIMPLE_DEFAULTS:
            settings_obj.ui_preset = PRESET_SIMPLE
        else:
            settings_obj.ui_preset = PRESET_CUSTOM
    settings_obj.save()
    return settings_obj


def go_target_allowed(url_name: str, settings_obj=None) -> bool:
    """Whether a Cmd go / rail URL name is allowed under current modules."""
    gate = URL_MODULE_GATES.get(url_name)
    if gate is None and url_name not in URL_MODULE_GATES:
        # Unknown targets: allow (focus, drawers, etc.)
        return True
    if gate is None:
        return True
    return is_enabled(gate, settings_obj)


def module_disabled_message(module_id: str) -> str:
    """Quiet enable hint for soft redirects."""
    label = MODULE_LABELS.get(module_id, module_id)
    return f"{label} is off. Enable it in Settings → Modules."


def require_module(module_id: str) -> Callable:
    """View decorator: soft-redirect to Home when the module is disabled."""

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if not is_enabled(module_id):
                messages.info(request, module_disabled_message(module_id))
                return redirect(reverse("home"))
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
