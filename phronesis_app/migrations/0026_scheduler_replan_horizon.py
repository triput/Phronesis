# ==============================================================================
# File: phronesis_app/migrations/0026_scheduler_replan_horizon.py
# Description: VX-01 — scheduler horizon days + re-plan toggle on AppSettings
# Component: Migrations
# Version: 1.0 (Gold Master)
# Created: 2026-07-31
# Last Update: 2026-07-31
# ==============================================================================

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("phronesis_app", "0025_timetarget"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="scheduler_horizon_days",
            field=models.PositiveSmallIntegerField(
                default=7,
                help_text="VX-01: multi-day greedy re-plan window (1–14 days).",
            ),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="scheduler_replan_enabled",
            field=models.BooleanField(
                default=False,
                help_text="VX-01: clear solver placements in horizon before each auto-schedule run.",
            ),
        ),
    ]
