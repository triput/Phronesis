# ==============================================================================
# File: phronesis_app/context_processors.py
# Description: Global template context for AppSettings, modules, and shell chrome
# Component: Core / Context Processor
# Version: 2.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-21
# ==============================================================================
"""Template context helpers for the V2/V3 cockpit shell."""

from .models import AppSettings
from phronesis_app.services.modules import (
    PRESET_SIMPLE,
    rail_links_for,
    resolve_modules,
    template_modules_map,
)
from phronesis_app.services.themes import resolve_theme_slug
from phronesis_app.services.time_locale import clock_format


def global_settings(request):
    """Expose singleton AppSettings, module flags, and locale helpers to templates."""
    try:
        settings_obj = AppSettings.get_solo()
    except Exception:
        settings_obj = None
    theme_slug = resolve_theme_slug(settings_obj.theme_mode if settings_obj else "")
    use_24h = bool(settings_obj.use_24h_time) if settings_obj else False
    ui_preset = getattr(settings_obj, "ui_preset", PRESET_SIMPLE) if settings_obj else PRESET_SIMPLE
    return {
        "app_settings": settings_obj,
        "theme_slug": theme_slug,
        "clock_format": clock_format(use_24h=use_24h, short=False),
        "clock_format_short": clock_format(use_24h=use_24h, short=True),
        "use_imperial": bool(settings_obj.use_imperial) if settings_obj else True,
        "ui_preset": ui_preset or PRESET_SIMPLE,
        "modules": template_modules_map(settings_obj),
        "modules_resolved": resolve_modules(settings_obj),
        "rail_links": rail_links_for(settings_obj),
    }
