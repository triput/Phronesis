# ==============================================================================
# File: phronesis_app/management/commands/import_sync_pack.py
# Description: VN-D02 apply phronesis.sync_pack JSON with LWW
# Component: Management Commands
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Import a cable sync-pack (Android → Win / Win → Win).

Usage:
  python manage.py import_sync_pack path\\to\\pack.json
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from phronesis_app.services.sync_pack import apply_sync_pack, parse_sync_pack_bytes


class Command(BaseCommand):
    help = "Import a phronesis.sync_pack v0 JSON file (LWW apply)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to sync-pack JSON.")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"File not found: {path}")
        try:
            payload = parse_sync_pack_bytes(path.read_bytes())
            result = apply_sync_pack(payload)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        style = self.style.SUCCESS if result.ok else self.style.ERROR
        self.stdout.write(style(result.message))
        if result.skipped_conflicts:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(result.skipped_conflicts)} conflict(s) kept local (LWW)."
                )
            )
