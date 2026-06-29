# ==============================================================================
# File: lifeos_app/context_processors.py
# Description: Custom context processors providing global template objects
# Component: Core / Context Processor
# Version: 1.0 (Gold Master)
# Created: 2026-06-29
# Last Update: 2026-06-29
# ==============================================================================

from .models import AppSettings

def global_settings(request):
    try:
        settings_obj = AppSettings.get_solo()
    except Exception:
        settings_obj = None
    return {
        'app_settings': settings_obj
    }
