# ==============================================================================
# File: phronesis_app/services/app_label_rename.py
# Description: VN-H01 — adopt lifeos_app → phronesis_app tables/contenttypes in place
# Component: Services / Migrations
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""In-place Django app-label rename (no wipe).

Historical installs used ``AppConfig.label = "lifeos_app"`` (tables
``lifeos_app_*``, ``django_migrations.app = lifeos_app``). Code now uses
``phronesis_app``. Fresh databases migrate cleanly under the new label.

Existing databases must run :func:`adopt_phronesis_app_label` **before**
``migrate``, otherwise Django treats every ``phronesis_app`` migration as
unapplied and tries to recreate tables.

Idempotent: no-ops when legacy tables / migration rows are already gone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import connection, transaction

OLD_LABEL = "lifeos_app"
NEW_LABEL = "phronesis_app"


@dataclass
class AdoptResult:
    """Summary of rename work performed (or skipped)."""

    tables_renamed: list[str] = field(default_factory=list)
    contenttypes_updated: int = 0
    migrations_updated: int = 0
    already_adopted: bool = False
    notes: list[str] = field(default_factory=list)


def legacy_artifacts_present(conn=None) -> bool:
    """Return True if lifeos_app tables or django_migrations rows still exist."""
    conn = conn or connection
    with conn.cursor() as cursor:
        table_names = set(conn.introspection.table_names(cursor))
        if any(name.startswith(f"{OLD_LABEL}_") for name in table_names):
            return True
        if "django_migrations" not in table_names:
            return False
        cursor.execute(
            "SELECT COUNT(*) FROM django_migrations WHERE app = %s",
            [OLD_LABEL],
        )
        return int(cursor.fetchone()[0]) > 0


def adopt_phronesis_app_label(*, dry_run: bool = False) -> AdoptResult:
    """Rename legacy lifeos_app DB artifacts to phronesis_app in place.

    Steps:
    1. ``ALTER TABLE`` every ``lifeos_app_*`` → ``phronesis_app_*``
    2. Update ``django_content_type.app_label``
    3. Update ``django_migrations.app`` so applied history matches the new label
    """
    result = AdoptResult()
    if not legacy_artifacts_present():
        result.already_adopted = True
        result.notes.append("No lifeos_app tables or migration rows — nothing to do.")
        return result

    vendor = connection.vendor
    with connection.cursor() as cursor:
        table_names = sorted(connection.introspection.table_names(cursor))

    legacy_tables = [t for t in table_names if t.startswith(f"{OLD_LABEL}_")]
    for old_name in legacy_tables:
        new_name = f"{NEW_LABEL}_{old_name[len(OLD_LABEL) + 1 :]}"
        if new_name in table_names:
            raise RuntimeError(
                f"Cannot rename {old_name!r} → {new_name!r}: target already exists. "
                "Resolve manually (backup, then drop the duplicate)."
            )
        result.tables_renamed.append(f"{old_name} → {new_name}")

    if dry_run:
        result.notes.append("dry_run=True — no DDL executed.")
        # Still report intended contenttype / migration counts
        with connection.cursor() as cursor:
            if "django_content_type" in table_names:
                cursor.execute(
                    "SELECT COUNT(*) FROM django_content_type WHERE app_label = %s",
                    [OLD_LABEL],
                )
                result.contenttypes_updated = int(cursor.fetchone()[0])
            if "django_migrations" in table_names:
                cursor.execute(
                    "SELECT COUNT(*) FROM django_migrations WHERE app = %s",
                    [OLD_LABEL],
                )
                result.migrations_updated = int(cursor.fetchone()[0])
        return result

    with transaction.atomic():
        with connection.cursor() as cursor:
            for old_name in legacy_tables:
                new_name = f"{NEW_LABEL}_{old_name[len(OLD_LABEL) + 1 :]}"
                _rename_table(cursor, vendor, old_name, new_name)

            if "django_content_type" in table_names:
                cursor.execute(
                    "UPDATE django_content_type SET app_label = %s WHERE app_label = %s",
                    [NEW_LABEL, OLD_LABEL],
                )
                result.contenttypes_updated = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
                # Some backends return -1 for rowcount on UPDATE
                if result.contenttypes_updated < 0:
                    cursor.execute(
                        "SELECT COUNT(*) FROM django_content_type WHERE app_label = %s",
                        [NEW_LABEL],
                    )
                    result.contenttypes_updated = int(cursor.fetchone()[0])

            if "django_migrations" in table_names:
                cursor.execute(
                    "UPDATE django_migrations SET app = %s WHERE app = %s",
                    [NEW_LABEL, OLD_LABEL],
                )
                result.migrations_updated = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
                if result.migrations_updated < 0:
                    cursor.execute(
                        "SELECT COUNT(*) FROM django_migrations WHERE app = %s",
                        [NEW_LABEL],
                    )
                    result.migrations_updated = int(cursor.fetchone()[0])

    result.notes.append(
        f"Renamed {len(result.tables_renamed)} table(s); "
        f"contenttypes={result.contenttypes_updated}; "
        f"migrations={result.migrations_updated}."
    )
    return result


def _rename_table(cursor, vendor: str, old_name: str, new_name: str) -> None:
    """Issue vendor-appropriate ALTER TABLE … RENAME."""
    # Identifiers from our own prefixes only — not user input.
    if vendor == "sqlite":
        cursor.execute(f'ALTER TABLE "{old_name}" RENAME TO "{new_name}"')
    elif vendor == "postgresql":
        cursor.execute(f'ALTER TABLE "{old_name}" RENAME TO "{new_name}"')
    elif vendor == "mysql":
        cursor.execute(f"RENAME TABLE `{old_name}` TO `{new_name}`")
    else:
        cursor.execute(f'ALTER TABLE "{old_name}" RENAME TO "{new_name}"')
