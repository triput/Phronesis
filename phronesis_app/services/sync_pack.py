# ==============================================================================
# File: phronesis_app/services/sync_pack.py
# Description: VN-D02/D03 phronesis.sync_pack v0 export / LWW import (Win side)
# Component: Services / Sync
# Version: 1.1 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Cable sync-pack: build and apply ``phronesis.sync_pack`` version 0.

Never includes OAuth secrets, API keys, or calendar credentials. Conflict
default is last-write-wins per ``sync_id`` + ``updated_at`` (UTC).
VN-D03 adds titled conflict reports and optional force-accept of remote rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from phronesis_app import models as app_models
from phronesis_app.models import SystemEnums, new_sync_id

SYNC_PACK_FORMAT = "phronesis.sync_pack"
SYNC_PACK_VERSION = 0
LAST_IMPORT_FILENAME = "last_imported_pack.json"

# Android Simple spine ↔ Django enum bridges
_STATUS_FROM_PACK = {
    "inbox": SystemEnums.ItemStatus.INBOX,
    "INBOX": SystemEnums.ItemStatus.INBOX,
    "active": SystemEnums.ItemStatus.IN_PROGRESS,
    "IN_PROGRESS": SystemEnums.ItemStatus.IN_PROGRESS,
    "PLANNED": SystemEnums.ItemStatus.PLANNED,
    "BACKLOG": SystemEnums.ItemStatus.BACKLOG,
    "BLOCKED": SystemEnums.ItemStatus.BLOCKED,
    "done": SystemEnums.ItemStatus.COMPLETED,
    "COMPLETED": SystemEnums.ItemStatus.COMPLETED,
}

_URGENCY_FROM_PACK = {
    "IMMEDIATE": SystemEnums.UrgencyLevel.IMMEDIATE,
    "HIGH": SystemEnums.UrgencyLevel.HIGH,
    "NORMAL": SystemEnums.UrgencyLevel.NORMAL,
    "LOW": SystemEnums.UrgencyLevel.LOW,
    0: SystemEnums.UrgencyLevel.NORMAL,
    1: SystemEnums.UrgencyLevel.LOW,
    2: SystemEnums.UrgencyLevel.NORMAL,
    3: SystemEnums.UrgencyLevel.HIGH,
    4: SystemEnums.UrgencyLevel.IMMEDIATE,
    "0": SystemEnums.UrgencyLevel.NORMAL,
    "1": SystemEnums.UrgencyLevel.LOW,
    "2": SystemEnums.UrgencyLevel.NORMAL,
    "3": SystemEnums.UrgencyLevel.HIGH,
    "4": SystemEnums.UrgencyLevel.IMMEDIATE,
}

_PARA_FROM_PACK = {
    "projects": SystemEnums.PARACategory.PROJECT,
    "PROJECT": SystemEnums.PARACategory.PROJECT,
    "project": SystemEnums.PARACategory.PROJECT,
    "areas": SystemEnums.PARACategory.AREA,
    "AREA": SystemEnums.PARACategory.AREA,
    "area": SystemEnums.PARACategory.AREA,
    "resources": SystemEnums.PARACategory.RESOURCE,
    "RESOURCE": SystemEnums.PARACategory.RESOURCE,
    "resource": SystemEnums.PARACategory.RESOURCE,
    "archive": SystemEnums.PARACategory.ARCHIVE,
    "ARCHIVE": SystemEnums.PARACategory.ARCHIVE,
}

_CONTAINER_TYPE_FROM_PACK = {
    "list": SystemEnums.ContainerType.LIST,
    "LIST": SystemEnums.ContainerType.LIST,
    "inbox": SystemEnums.ContainerType.INBOX,
    "INBOX": SystemEnums.ContainerType.INBOX,
    "project": SystemEnums.ContainerType.PROJECT,
    "PROJECT": SystemEnums.ContainerType.PROJECT,
    "epic": SystemEnums.ContainerType.EPIC,
    "EPIC": SystemEnums.ContainerType.EPIC,
    "sprint": SystemEnums.ContainerType.SPRINT,
    "SPRINT": SystemEnums.ContainerType.SPRINT,
    "course": SystemEnums.ContainerType.COURSE,
    "COURSE": SystemEnums.ContainerType.COURSE,
    "module": SystemEnums.ContainerType.MODULE,
    "MODULE": SystemEnums.ContainerType.MODULE,
    "specialization": SystemEnums.ContainerType.SPECIALIZATION,
    "SPECIALIZATION": SystemEnums.ContainerType.SPECIALIZATION,
}

_ITEM_TYPE_FROM_PACK = {
    "task": SystemEnums.ItemType.TASK,
    "TASK": SystemEnums.ItemType.TASK,
    "subtask": SystemEnums.ItemType.SUBTASK,
    "SUBTASK": SystemEnums.ItemType.SUBTASK,
    "learning_task": SystemEnums.ItemType.LEARNING_TASK,
    "LEARNING_TASK": SystemEnums.ItemType.LEARNING_TASK,
    "life_activity": SystemEnums.ItemType.LIFE_ACTIVITY,
    "LIFE_ACTIVITY": SystemEnums.ItemType.LIFE_ACTIVITY,
}


@dataclass
class SyncApplyResult:
    """Outcome of applying a sync pack (session report for Settings / VN-D03)."""

    ok: bool
    message: str = ""
    applied: dict[str, int] = field(default_factory=dict)
    skipped_conflicts: list[dict[str, str]] = field(default_factory=list)
    tombstones_applied: int = 0
    source_device_id: str = ""
    # When set, listed sync_ids always take the pack row (force-accept remote).
    force_sync_ids: set[str] = field(default_factory=set)


def _utc_now_iso() -> str:
    return datetime.now(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dt_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)
    return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        # Android may send date-only for due_at
        try:
            dt = datetime.fromisoformat(text + "T12:00:00+00:00")
        except ValueError:
            return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return dt


def _as_uuid(raw: Any) -> UUID | None:
    if raw is None or raw == "":
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def _sid(obj) -> str:
    return str(obj.sync_id)


def ensure_device_id() -> UUID:
    """Return (and persist) this install's device_id."""
    solo = app_models.AppSettings.get_solo()
    if not solo.device_id:
        solo.device_id = new_sync_id()
        solo.save(update_fields=["device_id"])
    return solo.device_id


def default_export_path() -> str:
    """Suggested export path under PHRONESIS_DATA_DIR or cwd."""
    from phronesis_django.data_paths import get_phronesis_data_dir

    stamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    device = str(ensure_device_id())[:8]
    name = f"phronesis-sync-{device}-{stamp}.json"
    data_dir = get_phronesis_data_dir()
    if data_dir is not None:
        sync_dir = data_dir / "sync"
        sync_dir.mkdir(parents=True, exist_ok=True)
        return str(sync_dir / name)
    return name


def build_sync_pack_dict() -> dict[str, Any]:
    """Serialize local productivity graph + settings subset into pack v0."""
    device_id = ensure_device_id()
    domains = list(app_models.DomainCategory.objects.all())
    tags = list(app_models.Tag.objects.select_related("domain").all())
    containers = list(
        app_models.WorkspaceContainer.objects.select_related("domain", "parent").all()
    )
    items = list(app_models.ExecutionItem.objects.select_related("parent_item").all())
    links = list(
        app_models.ItemContainerLink.objects.select_related("item", "container").all()
    )
    deps = list(
        app_models.ItemDependencyLink.objects.select_related("from_item", "to_item").all()
    )
    sessions = list(
        app_models.FocusSession.objects.select_related("execution_item").all()
    )
    solo = app_models.AppSettings.get_solo()

    tombstones: list[dict[str, str]] = []
    live_items: list[dict[str, Any]] = []
    for item in items:
        if item.is_deleted:
            tombstones.append(
                {
                    "entity": "items",
                    "sync_id": _sid(item),
                    "deleted_at": _dt_to_iso(item.updated_at) or _utc_now_iso(),
                }
            )
        else:
            live_items.append(_serialize_item(item))

    for container in containers:
        if container.is_archived:
            tombstones.append(
                {
                    "entity": "containers",
                    "sync_id": _sid(container),
                    "deleted_at": _dt_to_iso(container.updated_at) or _utc_now_iso(),
                }
            )

    return {
        "format": SYNC_PACK_FORMAT,
        "version": SYNC_PACK_VERSION,
        "exported_at": _utc_now_iso(),
        "source_device_id": str(device_id),
        "entities": {
            "domains": [_serialize_domain(d) for d in domains],
            "tags": [_serialize_tag(t) for t in tags],
            "containers": [_serialize_container(c) for c in containers],
            "items": live_items,
            "item_container_links": [_serialize_link(lnk) for lnk in links],
            "item_dependencies": [_serialize_dep(d) for d in deps],
            "focus_sessions": [_serialize_focus(s) for s in sessions],
            "settings": _serialize_settings(solo),
        },
        "tombstones": tombstones,
    }


def export_sync_pack_bytes() -> bytes:
    """UTF-8 JSON bytes for download / file write."""
    return json.dumps(build_sync_pack_dict(), indent=2, ensure_ascii=False).encode("utf-8")


def parse_sync_pack_bytes(raw: bytes | str) -> dict[str, Any]:
    """Parse and validate pack envelope; raise ValueError on bad format."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8")
    else:
        text = raw
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    return validate_sync_pack(payload)


def validate_sync_pack(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept only ``phronesis.sync_pack`` version 0."""
    if not isinstance(payload, dict):
        raise ValueError("Sync pack must be a JSON object.")
    if payload.get("format") != SYNC_PACK_FORMAT:
        raise ValueError(
            f"Unsupported format {payload.get('format')!r}; expected {SYNC_PACK_FORMAT!r}."
        )
    version = payload.get("version")
    if version != SYNC_PACK_VERSION:
        raise ValueError(f"Unsupported sync pack version {version!r}; v0 clients accept 0 only.")
    if "entities" not in payload or not isinstance(payload["entities"], dict):
        raise ValueError("Sync pack missing entities object.")
    return payload


def _lww_wins(pack_updated: datetime | None, local_updated: datetime | None) -> bool:
    """True when pack should replace local (pack >= local)."""
    if pack_updated is None:
        return local_updated is None
    if local_updated is None:
        return True
    return pack_updated >= local_updated


def _pack_applies(
    result: SyncApplyResult,
    pack_updated: datetime | None,
    local_updated: datetime | None,
    sync_id: str,
) -> bool:
    """LWW unless sync_id is in the force-accept set (VN-D03)."""
    if sync_id and sync_id in result.force_sync_ids:
        return True
    return _lww_wins(pack_updated, local_updated)


def _force_updated_at(model, pk: int, when: datetime | None) -> None:
    """Bypass auto_now so LWW timestamps from the pack stick."""
    if when is None:
        return
    type(model).objects.filter(pk=pk).update(updated_at=when)


def last_imported_pack_path() -> Path:
    """Path for the most recently imported pack (force-accept cache)."""
    from phronesis_django.data_paths import get_phronesis_data_dir

    data_dir = get_phronesis_data_dir()
    base = (data_dir / "sync") if data_dir is not None else Path("sync")
    base.mkdir(parents=True, exist_ok=True)
    return base / LAST_IMPORT_FILENAME


def persist_imported_pack(payload: dict[str, Any]) -> None:
    """Cache last import so Settings can force-accept selected conflicts."""
    path = last_imported_pack_path()
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_last_imported_pack() -> dict[str, Any] | None:
    """Load cached last import; None if missing/invalid."""
    path = last_imported_pack_path()
    if not path.is_file():
        return None
    try:
        return validate_sync_pack(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def resolve_entity_title(entity: str, sync_id: str) -> str:
    """Best-effort local title/name for conflict UX."""
    sid = _as_uuid(sync_id)
    if not sid:
        return ""
    if entity == "items":
        row = app_models.ExecutionItem.objects.filter(sync_id=sid).first()
        return (row.title if row else "") or ""
    if entity == "containers":
        row = app_models.WorkspaceContainer.objects.filter(sync_id=sid).first()
        return (row.title if row else "") or ""
    if entity == "domains":
        row = app_models.DomainCategory.objects.filter(sync_id=sid).first()
        return (row.name if row else "") or ""
    if entity == "tags":
        row = app_models.Tag.objects.filter(sync_id=sid).first()
        return (row.name if row else "") or ""
    if entity == "settings":
        return "App settings"
    if entity == "focus_sessions":
        row = app_models.FocusSession.objects.filter(sync_id=sid).select_related(
            "execution_item"
        ).first()
        if row and row.execution_item_id:
            return row.execution_item.title or ""
        return "Focus session"
    if entity in ("item_container_links", "item_dependencies"):
        return ""
    return ""


def shape_conflict_report(
    conflicts: list[dict[str, Any]] | None,
    *,
    enrich_titles: bool = True,
) -> list[dict[str, str]]:
    """Normalize conflict dicts for Settings / session summary (VN-D03)."""
    shaped: list[dict[str, str]] = []
    for raw in conflicts or []:
        if not isinstance(raw, dict):
            continue
        entity = str(raw.get("entity") or "").strip()
        sync_id = str(raw.get("sync_id") or "").strip()
        reason = str(raw.get("reason") or "local_newer").strip() or "local_newer"
        title = str(raw.get("title") or "").strip()
        if enrich_titles and not title and entity and sync_id:
            title = resolve_entity_title(entity, sync_id)
        entry = {
            "entity": entity,
            "sync_id": sync_id,
            "reason": reason,
            "title": title,
        }
        shaped.append(entry)
    return shaped


def force_accept_remote(sync_ids: list[str] | set[str]) -> SyncApplyResult:
    """Re-apply cached last import forcing pack wins for the given sync_ids."""
    ids = {str(s).strip() for s in sync_ids if str(s).strip()}
    if not ids:
        return SyncApplyResult(ok=False, message="Select at least one conflict to accept.")
    pack = load_last_imported_pack()
    if pack is None:
        return SyncApplyResult(
            ok=False,
            message="No cached pack from the last import — re-import the file first.",
        )
    return apply_sync_pack(pack, force_sync_ids=ids)


@transaction.atomic
def apply_sync_pack(
    payload: dict[str, Any],
    *,
    force_sync_ids: set[str] | list[str] | None = None,
) -> SyncApplyResult:
    """Apply tombstones then upsert entities with LWW; two-pass FK linking."""
    payload = validate_sync_pack(payload)
    entities = payload.get("entities") or {}
    tombstones = payload.get("tombstones") or []
    source = str(payload.get("source_device_id") or "")
    forced = {str(s).strip() for s in (force_sync_ids or []) if str(s).strip()}

    result = SyncApplyResult(ok=True, source_device_id=source, force_sync_ids=forced)
    applied: dict[str, int] = {
        "domains": 0,
        "tags": 0,
        "containers": 0,
        "items": 0,
        "item_container_links": 0,
        "item_dependencies": 0,
        "focus_sessions": 0,
        "settings": 0,
    }

    # Apply order: tombstones first, then entity upserts. A stale upsert that
    # arrives with is_deleted=False must not revive a row when the tombstone
    # deleted_at is newer — mark deleted again if pack item is older than tombstone.
    for stone in tombstones:
        if not isinstance(stone, dict):
            continue
        if _apply_tombstone(stone):
            result.tombstones_applied += 1

    # Remember tombstone times so stale upserts cannot revive
    tombstone_times: dict[tuple[str, str], datetime] = {}
    for stone in tombstones:
        if not isinstance(stone, dict):
            continue
        sid = _as_uuid(stone.get("sync_id"))
        entity = (stone.get("entity") or "").strip()
        when = _parse_iso(stone.get("deleted_at"))
        if sid and entity and when:
            tombstone_times[(entity, str(sid))] = when

    # Pass 1b — upsert entities without FK resolution where possible
    pending_fk: list[tuple[str, Any, dict[str, Any]]] = []

    for row in entities.get("domains") or []:
        if _upsert_domain(row, result):
            applied["domains"] += 1

    for row in entities.get("tags") or []:
        obj, need_fk = _upsert_tag(row, result)
        if obj:
            applied["tags"] += 1
            if need_fk:
                pending_fk.append(("tag", obj, row))

    for row in entities.get("containers") or []:
        # Skip revive if tombstoned more recently
        sid = str(row.get("sync_id") or "")
        stone_ts = tombstone_times.get(("containers", sid))
        row_ts = _parse_iso(row.get("updated_at"))
        if stone_ts and (row_ts is None or row_ts <= stone_ts):
            continue
        obj, need_fk = _upsert_container(row, result)
        if obj:
            applied["containers"] += 1
            if need_fk:
                pending_fk.append(("container", obj, row))

    for row in entities.get("items") or []:
        sid = str(row.get("sync_id") or "")
        stone_ts = tombstone_times.get(("items", sid))
        row_ts = _parse_iso(row.get("updated_at"))
        if stone_ts and (row_ts is None or row_ts <= stone_ts):
            continue
        obj, need_fk = _upsert_item(row, result)
        if obj:
            applied["items"] += 1
            if need_fk:
                pending_fk.append(("item", obj, row))

    for row in entities.get("item_container_links") or []:
        if _upsert_link(row, result):
            applied["item_container_links"] += 1

    for row in entities.get("item_dependencies") or []:
        if _upsert_dep(row, result):
            applied["item_dependencies"] += 1

    for row in entities.get("focus_sessions") or []:
        if _upsert_focus(row, result):
            applied["focus_sessions"] += 1

    settings_row = entities.get("settings")
    if isinstance(settings_row, dict):
        if _upsert_settings(settings_row, result):
            applied["settings"] = 1

    # Pass 2 — FK linking via *_sync_id
    for kind, obj, row in pending_fk:
        if kind == "tag":
            _link_tag_domain(obj, row)
        elif kind == "container":
            _link_container_fks(obj, row)
        elif kind == "item":
            _link_item_parent(obj, row)

    result.applied = applied
    result.skipped_conflicts = shape_conflict_report(
        result.skipped_conflicts, enrich_titles=True
    )
    conflict_n = len(result.skipped_conflicts)
    forced_n = len(result.force_sync_ids)
    result.message = (
        f"Applied pack from {source or 'unknown'}: "
        f"{sum(applied.values())} upserts, {result.tombstones_applied} tombstones"
        + (f", {conflict_n} kept local (LWW)" if conflict_n else "")
        + (f", {forced_n} force-accepted" if forced_n else "")
        + "."
    )

    # Cache pack for force-accept UX (cleartext — same trust model as cable file).
    try:
        persist_imported_pack(payload)
    except OSError:
        pass

    # Persist session summary (never secrets)
    solo = app_models.AppSettings.get_solo()
    peer = _as_uuid(source)
    solo.last_sync_at = timezone.now()
    solo.last_sync_peer_device_id = peer
    solo.last_sync_summary = {
        "applied": applied,
        "tombstones_applied": result.tombstones_applied,
        "conflict_count": conflict_n,
        "conflicts": result.skipped_conflicts[:50],
        "force_accepted": sorted(result.force_sync_ids)[:50] if forced_n else [],
        "source_device_id": source,
        "message": result.message,
        "has_cached_pack": last_imported_pack_path().is_file(),
    }
    solo.save(
        update_fields=[
            "last_sync_at",
            "last_sync_peer_device_id",
            "last_sync_summary",
            "updated_at",
        ]
    )
    return result


def _note_conflict(
    result: SyncApplyResult,
    entity: str,
    sync_id: str,
    reason: str,
    title: str = "",
) -> None:
    result.skipped_conflicts.append(
        {
            "entity": entity,
            "sync_id": sync_id,
            "reason": reason,
            "title": (title or "").strip(),
        }
    )


def _apply_tombstone(stone: dict[str, Any]) -> bool:
    entity = (stone.get("entity") or "").strip()
    sid = _as_uuid(stone.get("sync_id"))
    if not sid:
        return False
    deleted_at = _parse_iso(stone.get("deleted_at")) or timezone.now()

    if entity == "items":
        item = app_models.ExecutionItem.objects.filter(sync_id=sid).first()
        if item is None:
            return False
        if item.updated_at and deleted_at < item.updated_at and not item.is_deleted:
            return False
        item.is_deleted = True
        item.save(update_fields=["is_deleted", "updated_at"])
        _force_updated_at(item, item.pk, deleted_at)
        return True

    if entity == "containers":
        container = app_models.WorkspaceContainer.objects.filter(sync_id=sid).first()
        if container is None:
            return False
        if container.updated_at and deleted_at < container.updated_at and not container.is_archived:
            return False
        container.is_archived = True
        container.para_state = SystemEnums.PARACategory.ARCHIVE
        container.save(update_fields=["is_archived", "para_state", "updated_at"])
        _force_updated_at(container, container.pk, deleted_at)
        return True

    if entity == "item_container_links":
        deleted, _ = app_models.ItemContainerLink.objects.filter(sync_id=sid).delete()
        return deleted > 0

    if entity == "item_dependencies":
        deleted, _ = app_models.ItemDependencyLink.objects.filter(sync_id=sid).delete()
        return deleted > 0

    if entity == "tags":
        deleted, _ = app_models.Tag.objects.filter(sync_id=sid).delete()
        return deleted > 0

    if entity == "domains":
        # Soft: deactivate rather than cascade-delete
        domain = app_models.DomainCategory.objects.filter(sync_id=sid).first()
        if domain is None:
            return False
        domain.is_active = False
        domain.save(update_fields=["is_active", "updated_at"])
        _force_updated_at(domain, domain.pk, deleted_at)
        return True

    if entity == "focus_sessions":
        deleted, _ = app_models.FocusSession.objects.filter(sync_id=sid).delete()
        return deleted > 0

    return False


def _upsert_domain(row: dict[str, Any], result: SyncApplyResult) -> bool:
    sid = _as_uuid(row.get("sync_id"))
    if not sid:
        return False
    pack_ts = _parse_iso(row.get("updated_at"))
    existing = app_models.DomainCategory.objects.filter(sync_id=sid).first()
    if existing and not _pack_applies(result, pack_ts, existing.updated_at, str(sid)):
        _note_conflict(result, "domains", str(sid), "local_newer", existing.name)
        return False

    slug = (row.get("slug") or slugify(row.get("name") or "domain") or "domain")[:100]
    name = (row.get("name") or slug)[:100]
    # Unique name/slug: reuse existing by sync_id only; tweak slug on insert clash
    if existing is None:
        base_slug = slug
        n = 2
        while app_models.DomainCategory.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{n}"[:100]
            n += 1
        while app_models.DomainCategory.objects.filter(name=name).exclude(sync_id=sid).exists():
            name = f"{name}-{n}"[:100]
            n += 1
        existing = app_models.DomainCategory(sync_id=sid)

    existing.name = name
    existing.slug = slug
    existing.color = (row.get("color") or existing.color or "#64748B")[:7]
    existing.is_active = bool(row.get("is_active", True))
    existing.is_academy = bool(row.get("is_academy", False))
    existing.save()
    _force_updated_at(existing, existing.pk, pack_ts)
    return True


def _upsert_tag(row: dict[str, Any], result: SyncApplyResult) -> tuple[Any, bool]:
    sid = _as_uuid(row.get("sync_id"))
    if not sid:
        return None, False
    pack_ts = _parse_iso(row.get("updated_at"))
    existing = app_models.Tag.objects.filter(sync_id=sid).first()
    if existing and not _pack_applies(result, pack_ts, existing.updated_at, str(sid)):
        _note_conflict(result, "tags", str(sid), "local_newer", existing.name)
        return None, False

    name = (row.get("name") or "tag")[:100]
    if existing is None:
        n = 2
        candidate = name
        while app_models.Tag.objects.filter(name=candidate).exists():
            candidate = f"{name}-{n}"[:100]
            n += 1
        name = candidate
        existing = app_models.Tag(sync_id=sid)

    existing.name = name
    existing.color = (row.get("color") or existing.color or "#A1A1AA")[:7]
    existing.save()
    _force_updated_at(existing, existing.pk, pack_ts)
    return existing, True


def _link_tag_domain(tag: app_models.Tag, row: dict[str, Any]) -> None:
    domain_sid = _as_uuid(row.get("domain_sync_id"))
    if domain_sid is None:
        tag.domain = None
    else:
        tag.domain = app_models.DomainCategory.objects.filter(sync_id=domain_sid).first()
    tag.save(update_fields=["domain", "updated_at"])


def _upsert_container(row: dict[str, Any], result: SyncApplyResult) -> tuple[Any, bool]:
    sid = _as_uuid(row.get("sync_id"))
    if not sid:
        return None, False
    pack_ts = _parse_iso(row.get("updated_at"))
    existing = app_models.WorkspaceContainer.objects.filter(sync_id=sid).first()
    if existing and not _pack_applies(result, pack_ts, existing.updated_at, str(sid)):
        _note_conflict(result, "containers", str(sid), "local_newer", existing.title)
        return None, False

    title = (row.get("title") or "container")[:255]
    slug = (row.get("slug") or slugify(title) or "container")[:255]
    if existing is None:
        base = slug
        n = 2
        while app_models.WorkspaceContainer.objects.filter(slug=slug).exists():
            slug = f"{base}-{n}"[:255]
            n += 1
        existing = app_models.WorkspaceContainer(sync_id=sid)

    ctype_raw = row.get("container_type") or "LIST"
    existing.title = title
    existing.slug = slug
    existing.container_type = _CONTAINER_TYPE_FROM_PACK.get(
        ctype_raw, SystemEnums.ContainerType.LIST
    )
    para_raw = row.get("para_state") or "PROJECT"
    existing.para_state = _PARA_FROM_PACK.get(para_raw, SystemEnums.PARACategory.PROJECT)
    existing.priority = int(row.get("priority") or SystemEnums.PriorityLevel.NORMAL)
    existing.is_archived = bool(row.get("is_archived", False))
    existing.order = int(row.get("order") or 0)
    if existing.is_archived:
        existing.para_state = SystemEnums.PARACategory.ARCHIVE
    existing.save()
    _force_updated_at(existing, existing.pk, pack_ts)
    return existing, True


def _link_container_fks(container: app_models.WorkspaceContainer, row: dict[str, Any]) -> None:
    domain_sid = _as_uuid(row.get("domain_sync_id"))
    parent_sid = _as_uuid(row.get("parent_sync_id"))
    container.domain = (
        app_models.DomainCategory.objects.filter(sync_id=domain_sid).first()
        if domain_sid
        else None
    )
    if parent_sid and parent_sid != container.sync_id:
        container.parent = app_models.WorkspaceContainer.objects.filter(sync_id=parent_sid).first()
    else:
        container.parent = None
    container.save(update_fields=["domain", "parent", "updated_at"])


def _upsert_item(row: dict[str, Any], result: SyncApplyResult) -> tuple[Any, bool]:
    sid = _as_uuid(row.get("sync_id"))
    if not sid:
        return None, False
    pack_ts = _parse_iso(row.get("updated_at"))
    existing = app_models.ExecutionItem.objects.filter(sync_id=sid).first()
    if existing and not _pack_applies(result, pack_ts, existing.updated_at, str(sid)):
        _note_conflict(result, "items", str(sid), "local_newer", existing.title)
        return None, False

    if existing is None:
        existing = app_models.ExecutionItem(sync_id=sid)

    status_raw = row.get("status") or "INBOX"
    type_raw = row.get("item_type") or "TASK"
    urgency_raw = row.get("urgency")
    existing.title = (row.get("title") or "item")[:255]
    existing.status = _STATUS_FROM_PACK.get(status_raw, SystemEnums.ItemStatus.INBOX)
    existing.item_type = _ITEM_TYPE_FROM_PACK.get(type_raw, SystemEnums.ItemType.TASK)
    existing.priority = int(row.get("priority") or SystemEnums.PriorityLevel.NORMAL)
    existing.urgency = _URGENCY_FROM_PACK.get(
        urgency_raw if urgency_raw is not None else "NORMAL",
        SystemEnums.UrgencyLevel.NORMAL,
    )
    existing.due_at = _parse_iso(row.get("due_at"))
    est = row.get("estimated_minutes")
    existing.estimated_minutes = int(est) if est is not None else 30
    fuzzy = row.get("fuzzy_timeframe") or SystemEnums.FuzzyTimeframe.NONE
    if isinstance(fuzzy, str) and fuzzy.upper() in SystemEnums.FuzzyTimeframe.values:
        existing.fuzzy_timeframe = fuzzy.upper()
    existing.is_deleted = bool(row.get("is_deleted", False))
    existing.notes = row.get("notes") or ""
    existing.save()
    _force_updated_at(existing, existing.pk, pack_ts)
    return existing, True


def _link_item_parent(item: app_models.ExecutionItem, row: dict[str, Any]) -> None:
    parent_sid = _as_uuid(row.get("parent_item_sync_id"))
    if parent_sid and parent_sid != item.sync_id:
        item.parent_item = app_models.ExecutionItem.objects.filter(sync_id=parent_sid).first()
    else:
        item.parent_item = None
    item.save(update_fields=["parent_item", "updated_at"])


def _upsert_link(row: dict[str, Any], result: SyncApplyResult) -> bool:
    sid = _as_uuid(row.get("sync_id"))
    item_sid = _as_uuid(row.get("item_sync_id"))
    container_sid = _as_uuid(row.get("container_sync_id"))
    if not sid or not item_sid or not container_sid:
        return False
    item = app_models.ExecutionItem.objects.filter(sync_id=item_sid).first()
    container = app_models.WorkspaceContainer.objects.filter(sync_id=container_sid).first()
    if item is None or container is None:
        return False

    pack_ts = _parse_iso(row.get("updated_at"))
    existing = app_models.ItemContainerLink.objects.filter(sync_id=sid).first()
    if existing is None:
        # Prefer match on item+container pair
        existing = app_models.ItemContainerLink.objects.filter(
            item=item, container=container
        ).first()
        if existing is None:
            existing = app_models.ItemContainerLink(sync_id=sid, item=item, container=container)
        else:
            existing.sync_id = sid

    if existing.pk and existing.updated_at and not _pack_applies(
        result, pack_ts, existing.updated_at, str(sid)
    ):
        _note_conflict(
            result,
            "item_container_links",
            str(sid),
            "local_newer",
            item.title if item else "",
        )
        return False

    is_primary = bool(row.get("is_primary", False))
    if is_primary:
        app_models.ItemContainerLink.objects.filter(item=item, is_primary=True).exclude(
            sync_id=sid
        ).update(is_primary=False)

    existing.item = item
    existing.container = container
    existing.is_primary = is_primary
    existing.save()
    _force_updated_at(existing, existing.pk, pack_ts)
    return True


def _upsert_dep(row: dict[str, Any], result: SyncApplyResult) -> bool:
    sid = _as_uuid(row.get("sync_id"))
    from_sid = _as_uuid(row.get("from_item_sync_id"))
    to_sid = _as_uuid(row.get("to_item_sync_id"))
    if not sid or not from_sid or not to_sid or from_sid == to_sid:
        return False
    from_item = app_models.ExecutionItem.objects.filter(sync_id=from_sid).first()
    to_item = app_models.ExecutionItem.objects.filter(sync_id=to_sid).first()
    if from_item is None or to_item is None:
        return False

    pack_ts = _parse_iso(row.get("updated_at"))
    existing = app_models.ItemDependencyLink.objects.filter(sync_id=sid).first()
    if existing is None:
        existing = app_models.ItemDependencyLink.objects.filter(
            from_item=from_item,
            to_item=to_item,
            link_type=SystemEnums.DependencyLinkType.BLOCKS,
        ).first()
        if existing is None:
            existing = app_models.ItemDependencyLink(
                sync_id=sid,
                from_item=from_item,
                to_item=to_item,
                link_type=SystemEnums.DependencyLinkType.BLOCKS,
            )
        else:
            existing.sync_id = sid

    if existing.pk and existing.updated_at and not _pack_applies(
        result, pack_ts, existing.updated_at, str(sid)
    ):
        _note_conflict(
            result,
            "item_dependencies",
            str(sid),
            "local_newer",
            from_item.title if from_item else "",
        )
        return False

    existing.from_item = from_item
    existing.to_item = to_item
    existing.save()
    _force_updated_at(existing, existing.pk, pack_ts)
    return True


def _upsert_focus(row: dict[str, Any], result: SyncApplyResult) -> bool:
    sid = _as_uuid(row.get("sync_id"))
    item_sid = _as_uuid(row.get("item_sync_id"))
    if not sid or not item_sid:
        return False
    item = app_models.ExecutionItem.objects.filter(sync_id=item_sid).first()
    if item is None:
        return False

    pack_ts = _parse_iso(row.get("updated_at"))
    existing = app_models.FocusSession.objects.filter(sync_id=sid).first()
    if existing and not _pack_applies(result, pack_ts, existing.updated_at, str(sid)):
        _note_conflict(result, "focus_sessions", str(sid), "local_newer", item.title)
        return False

    started = _parse_iso(row.get("started_at")) or timezone.now()
    ended = _parse_iso(row.get("ended_at"))
    accum = row.get("accumulated_seconds")
    if accum is None:
        accum = 0

    if existing is None:
        # Close conflicting open session on same item when importing an open one
        if ended is None:
            app_models.FocusSession.objects.filter(
                execution_item=item, ended_at__isnull=True
            ).exclude(sync_id=sid).update(ended_at=timezone.now(), end_reason="preempted")
        existing = app_models.FocusSession(sync_id=sid, execution_item=item)

    existing.execution_item = item
    existing.started_at = started
    existing.ended_at = ended
    existing.duration_seconds = int(accum)
    reason = row.get("end_reason") or ""
    existing.end_reason = str(reason)[:20]
    existing.save()
    _force_updated_at(existing, existing.pk, pack_ts)
    return True


def _upsert_settings(row: dict[str, Any], result: SyncApplyResult) -> bool:
    """Apply settings subset only — never secrets / OAuth fields."""
    # Strip any accidental secret keys from inbound pack
    forbidden = {
        "google_oauth_client_secret",
        "microsoft_oauth_client_secret",
        "openweather_api_key",
        "notification_webhook_token",
        "credentials_json",
        "google_oauth_client_id",
        "microsoft_oauth_client_id",
    }
    if any(k in row for k in forbidden):
        # Still apply safe fields; ignore secrets entirely
        pass

    pack_ts = _parse_iso(row.get("updated_at"))
    solo = app_models.AppSettings.get_solo()
    if not _pack_applies(result, pack_ts, solo.updated_at, str(solo.sync_id)):
        _note_conflict(result, "settings", str(solo.sync_id), "local_newer", "App settings")
        return False

    sid = _as_uuid(row.get("sync_id"))
    if sid and solo.sync_id != sid:
        # Keep local sync_id stable for singleton; still apply fields
        pass

    if "timezone" in row and row["timezone"]:
        solo.timezone = str(row["timezone"])[:64]
    theme = row.get("theme_slug") or row.get("theme_mode")
    if theme:
        solo.theme_mode = str(theme)[:32]
    if "ui_preset" in row and row["ui_preset"]:
        solo.ui_preset = str(row["ui_preset"])[:16]
    modules = row.get("modules_enabled")
    if isinstance(modules, dict):
        # Only bool map — drop anything else
        solo.modules_enabled = {str(k): bool(v) for k, v in modules.items()}
    solo.save()
    _force_updated_at(solo, solo.pk, pack_ts)
    return True


def _serialize_domain(d: app_models.DomainCategory) -> dict[str, Any]:
    return {
        "sync_id": _sid(d),
        "updated_at": _dt_to_iso(d.updated_at) or _utc_now_iso(),
        "name": d.name,
        "slug": d.slug,
        "color": d.color,
        "is_active": d.is_active,
        "is_academy": d.is_academy,
    }


def _serialize_tag(t: app_models.Tag) -> dict[str, Any]:
    return {
        "sync_id": _sid(t),
        "updated_at": _dt_to_iso(t.updated_at) or _utc_now_iso(),
        "name": t.name,
        "color": t.color,
        "domain_sync_id": str(t.domain.sync_id) if t.domain_id else None,
    }


def _serialize_container(c: app_models.WorkspaceContainer) -> dict[str, Any]:
    return {
        "sync_id": _sid(c),
        "updated_at": _dt_to_iso(c.updated_at) or _utc_now_iso(),
        "title": c.title,
        "slug": c.slug,
        "container_type": c.container_type,
        "para_state": c.para_state,
        "priority": c.priority,
        "parent_sync_id": str(c.parent.sync_id) if c.parent_id else None,
        "domain_sync_id": str(c.domain.sync_id) if c.domain_id else None,
        "is_archived": c.is_archived,
        "order": c.order,
    }


def _serialize_item(item: app_models.ExecutionItem) -> dict[str, Any]:
    return {
        "sync_id": _sid(item),
        "updated_at": _dt_to_iso(item.updated_at) or _utc_now_iso(),
        "title": item.title,
        "status": item.status,
        "priority": item.priority,
        "urgency": item.urgency,
        "item_type": item.item_type,
        "due_at": _dt_to_iso(item.due_at),
        "estimated_minutes": item.estimated_minutes,
        "fuzzy_timeframe": item.fuzzy_timeframe,
        "parent_item_sync_id": str(item.parent_item.sync_id) if item.parent_item_id else None,
        "is_deleted": item.is_deleted,
        "notes": item.notes or "",
    }


def _serialize_link(lnk: app_models.ItemContainerLink) -> dict[str, Any]:
    return {
        "sync_id": _sid(lnk),
        "updated_at": _dt_to_iso(lnk.updated_at) or _utc_now_iso(),
        "item_sync_id": str(lnk.item.sync_id),
        "container_sync_id": str(lnk.container.sync_id),
        "is_primary": lnk.is_primary,
    }


def _serialize_dep(dep: app_models.ItemDependencyLink) -> dict[str, Any]:
    return {
        "sync_id": _sid(dep),
        "updated_at": _dt_to_iso(dep.updated_at) or _utc_now_iso(),
        "from_item_sync_id": str(dep.from_item.sync_id),
        "to_item_sync_id": str(dep.to_item.sync_id),
    }


def _serialize_focus(session: app_models.FocusSession) -> dict[str, Any]:
    return {
        "sync_id": _sid(session),
        "updated_at": _dt_to_iso(session.updated_at) or _utc_now_iso(),
        "item_sync_id": str(session.execution_item.sync_id),
        "started_at": _dt_to_iso(session.started_at),
        "ended_at": _dt_to_iso(session.ended_at),
        "end_reason": session.end_reason or None,
        "accumulated_seconds": session.duration_seconds,
    }


def _serialize_settings(solo: app_models.AppSettings) -> dict[str, Any]:
    """Settings subset only — explicitly omit secrets."""
    return {
        "sync_id": _sid(solo),
        "updated_at": _dt_to_iso(solo.updated_at) or _utc_now_iso(),
        "timezone": solo.timezone,
        "theme_slug": solo.theme_mode,
        "ui_preset": solo.ui_preset,
        "modules_enabled": solo.modules_enabled or {},
    }
