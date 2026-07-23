# ==============================================================================
# File: phronesis_app/services/backup.py
# Description: VN-A05 secrets-safe JSON backup export and scoped restore/clear
# Component: Services / Backup
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-21
# ==============================================================================
"""Owner-data backup: full JSON export (S-41 scrubbed) and Full / Productivity restore.

Export always dumps config + productivity models. Restore/clear honor ``full``
(wipe all owner models) or ``productivity`` (keep Settings, taxonomy, calendar
connection, templates; wipe work graph only). Never touches Django auth users.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from typing import Any, Iterable, Literal

from django.core import serializers
from django.db import connection, transaction

from phronesis_app import models as app_models

BACKUP_FORMAT = "phronesis_backup"
BACKUP_VERSION = 1

Scope = Literal["full", "productivity"]
VALID_SCOPES = frozenset({"full", "productivity"})

# Parents-first create order (FK-safe). Delete uses reverse.
CONFIG_MODELS: tuple[type, ...] = (
    app_models.AppSettings,
    app_models.DomainCategory,
    app_models.Tag,
    app_models.Certification,
    app_models.TimeAvailabilityBlock,
    app_models.CalendarIntegration,
    app_models.SyncedCalendar,
    app_models.SavedView,
    app_models.WorkspaceTemplate,
    app_models.WorkspaceTemplateNode,
)

PRODUCTIVITY_MODELS: tuple[type, ...] = (
    app_models.WorkspaceContainer,
    app_models.ExecutionItem,
    app_models.ItemContainerLink,
    app_models.ItemDependencyLink,
    app_models.FocusSession,
    app_models.ScheduledAllocation,
    app_models.RecurrenceRule,
    app_models.ReminderDispatch,
    app_models.CalendarEvent,
    app_models.StabilitySnapshot,
)

OWNER_MODELS: tuple[type, ...] = CONFIG_MODELS + PRODUCTIVITY_MODELS


def _label(model: type) -> str:
    return model._meta.label_lower


# model label → fields to redact / force empty on export (and full import)
SECRET_FIELDS: dict[str, tuple[str, ...]] = {
    _label(app_models.AppSettings): (
        "google_oauth_client_secret",
        "microsoft_oauth_client_secret",
        "openweather_api_key",
        "notification_webhook_token",
    ),
    _label(app_models.CalendarIntegration): ("credentials_json",),
}


@dataclass
class BackupResult:
    """Outcome of restore or clear."""

    ok: bool
    message: str = ""
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _models_for_scope(scope: Scope) -> tuple[type, ...]:
    if scope == "productivity":
        return PRODUCTIVITY_MODELS
    return OWNER_MODELS


def normalize_scope(raw: str | None) -> Scope:
    """Return a valid scope or raise ValueError."""
    value = (raw or "full").strip().lower()
    if value not in VALID_SCOPES:
        raise ValueError(f"Invalid scope {raw!r}; use full or productivity.")
    return value  # type: ignore[return-value]


def scrub_fields(model_label: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Strip OAuth/API secrets for S-41. Mutates a copy."""
    out = dict(fields)
    secrets = SECRET_FIELDS.get(model_label, ())
    for name in secrets:
        if name == "credentials_json":
            out[name] = {}
        elif name in out:
            out[name] = ""
    return out


def _serialize_model(model: type) -> list[dict[str, Any]]:
    qs = model.objects.all().order_by("pk")
    rows = serializers.serialize("python", qs)
    cleaned: list[dict[str, Any]] = []
    label = _label(model)
    for row in rows:
        cleaned.append(
            {
                "model": row["model"],
                "pk": row["pk"],
                "fields": scrub_fields(label, row["fields"]),
            }
        )
    return cleaned


def build_backup_dict() -> dict[str, Any]:
    """Build a full owner-data backup payload (secrets already scrubbed)."""
    tables: dict[str, list[dict[str, Any]]] = {}
    for model in OWNER_MODELS:
        tables[_label(model)] = _serialize_model(model)
    return {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "exported_at": datetime.now(dt_timezone.utc).isoformat(),
        "tables": tables,
    }


def export_backup_bytes() -> bytes:
    """Pretty-printed UTF-8 JSON backup."""
    return json.dumps(build_backup_dict(), indent=2, default=str).encode("utf-8")


def validate_backup_payload(payload: Any) -> dict[str, Any]:
    """Validate top-level backup shape; return the dict or raise ValueError."""
    if not isinstance(payload, dict):
        raise ValueError("Backup must be a JSON object.")
    if payload.get("format") != BACKUP_FORMAT:
        raise ValueError(f"Unsupported backup format {payload.get('format')!r}.")
    version = payload.get("version")
    if version != BACKUP_VERSION:
        raise ValueError(f"Unsupported backup version {version!r}.")
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("Backup missing tables object.")
    return payload


def parse_backup_bytes(raw: bytes | str) -> dict[str, Any]:
    """Parse and validate backup JSON bytes/text."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8")
    else:
        text = raw
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    return validate_backup_payload(payload)


def clear_owner_data(scope: Scope = "full") -> BackupResult:
    """Delete owner models for the given scope (auth users untouched)."""
    models = _models_for_scope(scope)
    counts: dict[str, int] = {}
    with transaction.atomic():
        for model in reversed(models):
            label = _label(model)
            counts[label] = model.objects.count()
            model.objects.all().delete()
    kind = "productivity data" if scope == "productivity" else "all owner data"
    return BackupResult(
        ok=True,
        message=f"Cleared {kind}.",
        counts=counts,
    )


def _rows_for_models(
    tables: dict[str, Any],
    models: Iterable[type],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect django-serializer rows in create order; scrub on the way in."""
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    known = {_label(m) for m in OWNER_MODELS}
    for key in tables:
        if key not in known:
            warnings.append(f"Skipped unknown table {key!r}.")
    for model in models:
        label = _label(model)
        chunk = tables.get(label)
        if chunk is None:
            continue
        if not isinstance(chunk, list):
            warnings.append(f"Skipped malformed table {label!r}.")
            continue
        for item in chunk:
            if not isinstance(item, dict):
                continue
            fields = item.get("fields")
            if not isinstance(fields, dict):
                continue
            fields = scrub_fields(label, fields)
            # Full import: never accept OAuth tokens even if file lied past scrub
            if label == _label(app_models.CalendarIntegration):
                fields["credentials_json"] = {}
            rows.append(
                {
                    "model": item.get("model") or label,
                    "pk": item.get("pk"),
                    "fields": fields,
                }
            )
    return rows, warnings


def restore_backup(payload: Any, scope: Scope = "full") -> BackupResult:
    """Replace owner data from a validated backup for the given scope."""
    data = validate_backup_payload(payload)
    tables = data["tables"]
    models = _models_for_scope(scope)
    rows, warnings = _rows_for_models(tables, models)
    counts: dict[str, int] = {}

    with transaction.atomic():
        clear_owner_data(scope)
        # Self-FK containers/items may arrive before parents; relax checks briefly.
        with connection.constraint_checks_disabled():
            for obj in serializers.deserialize("json", json.dumps(rows, default=str)):
                obj.save()
                label = obj.object._meta.label_lower
                counts[label] = counts.get(label, 0) + 1

    kind = "productivity" if scope == "productivity" else "full"
    return BackupResult(
        ok=True,
        message=f"Restored {kind} backup ({sum(counts.values())} rows).",
        counts=counts,
        warnings=warnings,
    )
