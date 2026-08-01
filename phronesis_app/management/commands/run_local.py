# ==============================================================================
# File: phronesis_app/management/commands/run_local.py
# Description: VN-B01 local Waitress server for Windows standalone launcher
# Component: Core / Management
# Version: 1.1 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-31
# ==============================================================================
"""Serve Phronesis with Waitress on loopback (production-ish local run)."""

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run Phronesis locally with Waitress (VN-B01). Default http://127.0.0.1:8765/"

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1", help="Bind host")
        parser.add_argument("--port", type=int, default=8765, help="Bind port")
        parser.add_argument(
            "--threads",
            type=int,
            default=4,
            help="Waitress worker threads",
        )
        parser.add_argument(
            "--skip-migrate",
            action="store_true",
            help="Skip migrate before serve (default applies pending migrations).",
        )

    def handle(self, *args, **options):
        try:
            from waitress import serve
        except ImportError as exc:
            raise SystemExit(
                "waitress is required. Install with: pip install waitress"
            ) from exc

        # Keep local SQLite current — missing axes tables crash every login
        # (VN-E04). Never auto-migrate Postgres/Neon (geek/Railway DATABASE_URL).
        if not options["skip_migrate"]:
            from django.conf import settings

            engine = (settings.DATABASES.get("default") or {}).get("ENGINE") or ""
            if "sqlite" in engine:
                self.stdout.write("Applying pending SQLite migrations before serve…")
                call_command("migrate", interactive=False, verbosity=1)
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping auto-migrate (non-SQLite engine={engine}). "
                        "Run migrate explicitly if needed."
                    )
                )

        from phronesis_django.wsgi import application

        host = options["host"]
        port = options["port"]
        self.stdout.write(self.style.SUCCESS(f"Serving Phronesis on http://{host}:{port}/"))
        serve(application, host=host, port=port, threads=options["threads"])
