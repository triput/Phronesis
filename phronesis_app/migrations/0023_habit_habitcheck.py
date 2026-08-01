# ==============================================================================
# File: phronesis_app/migrations/0023_habit_habitcheck.py
# Description: VX-05 Habit + HabitCheck models for optional mod.habits
# Component: Migrations
# Version: 1.0 (Gold Master)
# Created: 2026-07-30
# Last Update: 2026-07-30
# ==============================================================================

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("phronesis_app", "0022_today_visible_limit"),
    ]

    operations = [
        migrations.CreateModel(
            name="Habit",
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
                ("title", models.CharField(max_length=255)),
                (
                    "cadence",
                    models.CharField(
                        choices=[("daily", "Daily"), ("weekly", "Weekly")],
                        default="daily",
                        max_length=16,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "domain",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="habits",
                        to="phronesis_app.domaincategory",
                    ),
                ),
            ],
            options={
                "ordering": ["title", "id"],
            },
        ),
        migrations.CreateModel(
            name="HabitCheck",
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
                ("local_date", models.DateField()),
                (
                    "status",
                    models.CharField(
                        choices=[("done", "Done"), ("skipped", "Skipped")],
                        default="done",
                        max_length=16,
                    ),
                ),
                ("note", models.CharField(blank=True, default="", max_length=255)),
                (
                    "habit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="checks",
                        to="phronesis_app.habit",
                    ),
                ),
            ],
            options={
                "ordering": ["-local_date", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="habitcheck",
            constraint=models.UniqueConstraint(
                fields=("habit", "local_date"),
                name="uniq_habit_check_per_day",
            ),
        ),
    ]
