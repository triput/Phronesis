# ==============================================================================
# File: phronesis_app/migrations/0025_timetarget.py
# Description: VX-17 — TimeTarget weekly minutes goals per domain and/or tag
# Component: Migrations
# Version: 1.0 (Gold Master)
# Created: 2026-07-30
# Last Update: 2026-07-30
# ==============================================================================

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("phronesis_app", "0024_timeavailabilityblock_tags"),
    ]

    operations = [
        migrations.CreateModel(
            name="TimeTarget",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("minutes_per_week", models.PositiveIntegerField(default=60)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "domain",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="time_targets",
                        to="phronesis_app.domaincategory",
                    ),
                ),
                (
                    "tag",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="time_targets",
                        to="phronesis_app.tag",
                    ),
                ),
            ],
            options={
                "ordering": ["domain__name", "tag__name", "id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("domain__isnull", False))
                        | models.Q(("tag__isnull", False)),
                        name="time_target_requires_domain_or_tag",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(
                            ("domain__isnull", False), ("tag__isnull", True)
                        ),
                        fields=("domain",),
                        name="uniq_time_target_domain_only",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(
                            ("tag__isnull", False), ("domain__isnull", True)
                        ),
                        fields=("tag",),
                        name="uniq_time_target_tag_only",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(
                            ("domain__isnull", False), ("tag__isnull", False)
                        ),
                        fields=("domain", "tag"),
                        name="uniq_time_target_domain_and_tag",
                    ),
                ],
            },
        ),
    ]
