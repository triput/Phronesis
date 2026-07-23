# ==============================================================================
# File: phronesis_app/management/commands/export_sync_pack.py
# Description: VN-D02 write phronesis.sync_pack JSON to path / stdout
# Component: Management Commands
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Export a cable sync-pack (Win → Android / Win → Win).

Usage:
  python manage.py export_sync_pack
  python manage.py export_sync_pack --output path\\to\\pack.json
  python manage.py export_sync_pack --stdout
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand

from phronesis_app.services.sync_pack import default_export_path, export_sync_pack_bytes


class Command(BaseCommand):
    help = "Export a phronesis.sync_pack v0 JSON file for cable pair sync."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            "-o",
            default="",
            help="Destination path (default: PHRONESIS_DATA_DIR/sync/… or cwd).",
        )
        parser.add_argument(
            "--stdout",
            action="store_true",
            help="Write JSON to stdout instead of a file.",
        )

    def handle(self, *args, **options):
        payload = export_sync_pack_bytes()
        if options["stdout"]:
            self.stdout.write(payload.decode("utf-8"))
            return
        path = Path(options["output"] or default_export_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        self.stdout.write(self.style.SUCCESS(f"Wrote sync pack → {path.resolve()}"))
