# ==============================================================================
# File: phronesis_app/management/commands/migrate.py
# Description: Wrap Django migrate with VN-H01 lifeos_app → phronesis_app adopt
# Component: Management Commands
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Ensure legacy app-label artifacts are renamed before Django plans migrations.

``pre_migrate`` is too late — the migration plan is built first. Existing
installs with ``lifeos_app_*`` tables must adopt **before** the executor runs,
or Django will try to re-apply ``phronesis_app`` history from 0001.
"""

from django.core.management.commands.migrate import Command as MigrateCommand

from phronesis_app.services.app_label_rename import (
    adopt_phronesis_app_label,
    legacy_artifacts_present,
)


class Command(MigrateCommand):
    """Django migrate + VN-H01 in-place label adopt when needed."""

    def handle(self, *args, **options):
        if legacy_artifacts_present():
            if options.get("verbosity", 1):
                self.stdout.write(
                    self.style.WARNING(
                        "VN-H01: adopting lifeos_app → phronesis_app "
                        "(tables, contenttypes, django_migrations)…"
                    )
                )
            result = adopt_phronesis_app_label()
            if options.get("verbosity", 1):
                for note in result.notes:
                    self.stdout.write(f"  {note}")
        super().handle(*args, **options)
