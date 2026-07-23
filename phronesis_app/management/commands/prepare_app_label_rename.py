# ==============================================================================
# File: phronesis_app/management/commands/prepare_app_label_rename.py
# Description: VN-H01 — run before migrate on DBs that still use lifeos_app
# Component: Management Commands
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Adopt lifeos_app → phronesis_app DB artifacts in place (no wipe)."""

from django.core.management.base import BaseCommand, CommandError

from phronesis_app.services.app_label_rename import (
    adopt_phronesis_app_label,
    legacy_artifacts_present,
)


class Command(BaseCommand):
    help = (
        "VN-H01: rename lifeos_app_* tables and django_migrations/contenttypes "
        "to phronesis_app in place. Run before `migrate` on existing installs."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without executing DDL.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit 0 if already adopted, 1 if legacy artifacts remain.",
        )

    def handle(self, *args, **options):
        if options["check"]:
            if legacy_artifacts_present():
                self.stderr.write(self.style.WARNING("Legacy lifeos_app artifacts present."))
                raise SystemExit(1)
            self.stdout.write(self.style.SUCCESS("Already on phronesis_app label."))
            return

        try:
            result = adopt_phronesis_app_label(dry_run=bool(options["dry_run"]))
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc

        if result.already_adopted:
            self.stdout.write(self.style.SUCCESS(result.notes[0]))
            return

        for line in result.tables_renamed:
            self.stdout.write(f"  table: {line}")
        for note in result.notes:
            self.stdout.write(note)
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes written."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Adopted phronesis_app label. Next: python manage.py migrate"
                )
            )
