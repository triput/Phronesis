# ==============================================================================
# File: phronesis_app/apps.py
# Description: Django app config for phronesis_app (V2)
# Component: Core
# Version: 2.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
from django.apps import AppConfig


class PhronesisAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "phronesis_app"
    label = "lifeos_app"  # preserve Django app label / migrations / DB tables
    verbose_name = "Phronesis"
