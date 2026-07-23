# ==============================================================================
# File: phronesis_app/migrations/0019_appsettings_modules.py
# Description: VN-A03 ui_preset + modules_enabled; existing installs → Full
# Component: Migrations
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-21
# ==============================================================================

from django.db import migrations, models


def forwards_existing_to_full(apps, schema_editor):
    """Preserve author cockpit: existing AppSettings rows become Full preset."""
    AppSettings = apps.get_model("phronesis_app", "AppSettings")
    full = {
        "mod.academy": True,
        "mod.boards": True,
        "mod.overview": True,
        "mod.analytics": True,
        "mod.telemetry": True,
        "mod.stability": True,
        "mod.bulk": True,
        "mod.templates": True,
        "mod.calendar_grid": True,
        "mod.saved_views": True,
        "mod.availability": True,
    }
    for row in AppSettings.objects.all():
        row.ui_preset = "full"
        row.modules_enabled = full
        row.save(update_fields=["ui_preset", "modules_enabled"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("phronesis_app", "0018_polish_notes_calendar"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="ui_preset",
            field=models.CharField(
                default="simple",
                help_text="simple | full | custom — cockpit surface density preset.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="modules_enabled",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Optional module id → bool. Missing keys resolve as Simple (off).",
            ),
        ),
        migrations.RunPython(forwards_existing_to_full, noop_reverse),
    ]
