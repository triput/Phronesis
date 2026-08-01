# ==============================================================================
# File: phronesis_app/migrations/0022_today_visible_limit.py
# Description: VX-16 Truncated Today — AppSettings.today_visible_limit
# Component: Migrations
# Version: 1.0 (Gold Master)
# Created: 2026-07-30
# Last Update: 2026-07-30
# ==============================================================================

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("phronesis_app", "0021_encrypted_credentials_json"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="today_visible_limit",
            field=models.PositiveSmallIntegerField(
                default=5,
                help_text="Max #today items shown before Show all (1–20).",
            ),
        ),
    ]
