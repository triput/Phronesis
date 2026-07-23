# ==============================================================================
# File: phronesis_app/services/trash.py
# Description: VN-A07 trash listing and restore for soft-deleted items / archived containers
# Component: Services / Trash
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-21
# ==============================================================================
"""Trash — restore soft-deleted leaves and un-archive containers (Simple spine)."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from phronesis_app.models import ExecutionItem, SystemEnums, WorkspaceContainer


@dataclass
class TrashResult:
    """Outcome of a trash mutation."""

    ok: bool
    message: str = ""


def deleted_items():
    """Soft-deleted execution items, newest first."""
    return (
        ExecutionItem.objects.filter(is_deleted=True)
        .prefetch_related("tags")
        .order_by("-updated_at", "title")
    )


def archived_containers():
    """Archived workspace containers (PARA archive / is_archived)."""
    return (
        WorkspaceContainer.objects.filter(is_archived=True)
        .select_related("domain")
        .order_by("title")
    )


def trash_counts() -> dict[str, int]:
    """Counts for dock / empty-state copy."""
    return {
        "items": deleted_items().count(),
        "containers": archived_containers().count(),
    }


@transaction.atomic
def restore_item(item_id: int) -> TrashResult:
    """Clear is_deleted on an item."""
    item = ExecutionItem.objects.filter(pk=item_id, is_deleted=True).first()
    if not item:
        return TrashResult(ok=False, message="Deleted item not found.")
    item.is_deleted = False
    item.save(update_fields=["is_deleted", "updated_at"])
    return TrashResult(ok=True, message=f"Restored “{item.title}”.")


@transaction.atomic
def restore_container(container_id: int) -> TrashResult:
    """Un-archive a container (PARA back to PROJECT unless it was an AREA list)."""
    container = WorkspaceContainer.objects.filter(pk=container_id, is_archived=True).first()
    if not container:
        return TrashResult(ok=False, message="Archived container not found.")
    # System lists and Areas: prefer AREA; everything else PROJECT.
    if container.container_type in (
        SystemEnums.ContainerType.INBOX,
        SystemEnums.ContainerType.LIST,
    ):
        container.para_state = SystemEnums.PARACategory.AREA
    else:
        container.para_state = SystemEnums.PARACategory.PROJECT
    # save() syncs is_archived from para_state
    container.save()
    return TrashResult(ok=True, message=f"Restored “{container.title}”.")


@transaction.atomic
def empty_trash_items() -> TrashResult:
    """Permanently delete soft-deleted items (not archived containers)."""
    qs = ExecutionItem.objects.filter(is_deleted=True)
    n = qs.count()
    if n == 0:
        return TrashResult(ok=True, message="Trash has no deleted items.")
    qs.delete()
    return TrashResult(ok=True, message=f"Permanently deleted {n} item(s).")
