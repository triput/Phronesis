# ==============================================================================
# File: phronesis_app/migrations/0024_timeavailabilityblock_tags.py
# Description: VX-11 — TimeAvailabilityBlock.tags M2M for restricted windows
# Component: Migrations
# Version: 1.0 (Gold Master)
# Created: 2026-07-30
# Last Update: 2026-07-30
# ==============================================================================

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("phronesis_app", "0023_habit_habitcheck"),
    ]

    operations = [
        migrations.AddField(
            model_name="timeavailabilityblock",
            name="tags",
            field=models.ManyToManyField(
                blank=True,
                related_name="availability_blocks",
                to="phronesis_app.tag",
            ),
        ),
    ]
