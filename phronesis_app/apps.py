# ==============================================================================
# File: phronesis_app/apps.py
# Description: Django app config for phronesis_app (V3)
# Component: Core
# Version: 2.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-22
# ==============================================================================
from django.apps import AppConfig


class PhronesisAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "phronesis_app"
    # VN-H01: label matches package. Existing DBs: `migrate` auto-adopts via
    # management/commands/migrate.py (renames lifeos_app_* in place — no wipe).
    label = "phronesis_app"
    verbose_name = "Phronesis"
