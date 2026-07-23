# ==============================================================================
# File: phronesis_app/views/trash.py
# Description: VN-A07 Trash surface — list and restore soft-deleted / archived
# Component: Surfaces / Trash
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-21
# ==============================================================================
"""Trash canvas — Simple spine restore path (no Admin required)."""

from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from phronesis_app.services.trash import (
    TrashResult,
    archived_containers,
    deleted_items,
    empty_trash_items,
    restore_container,
    restore_item,
    trash_counts,
)


def _trash_redirect(result: TrashResult):
    qs = urlencode({"ok": "1" if result.ok else "0", "msg": result.message})
    return redirect(f"{reverse('canvas-trash')}?{qs}")


@login_required
def trash_view(request):
    """Render Trash surface with deleted items and archived containers."""
    counts = trash_counts()
    return render(
        request,
        "surfaces/trash.html",
        {
            "surface": "trash",
            "deleted_items": deleted_items(),
            "archived_containers": archived_containers(),
            "trash_counts": counts,
            "settings_message": request.GET.get("msg", ""),
            "settings_ok": request.GET.get("ok", "1") != "0",
        },
    )


@login_required
@require_POST
def trash_restore_item_view(request, item_id: int):
    """Restore a soft-deleted item."""
    result = restore_item(item_id)
    if request.htmx:
        return render(
            request,
            "partials/trash_toast.html",
            {"result": result},
            status=200 if result.ok else 422,
        )
    return _trash_redirect(result)


@login_required
@require_POST
def trash_restore_container_view(request, container_id: int):
    """Restore an archived container."""
    result = restore_container(container_id)
    if request.htmx:
        return render(
            request,
            "partials/trash_toast.html",
            {"result": result},
            status=200 if result.ok else 422,
        )
    return _trash_redirect(result)


@login_required
@require_POST
def trash_empty_view(request):
    """Permanently delete all soft-deleted items after confirm."""
    if (request.POST.get("confirm_text") or "").strip().upper() != "EMPTY":
        result = TrashResult(ok=False, message="Type EMPTY to permanently delete items.")
        if request.htmx:
            return render(request, "partials/trash_toast.html", {"result": result}, status=422)
        return _trash_redirect(result)
    result = empty_trash_items()
    if request.htmx:
        return render(
            request,
            "partials/trash_toast.html",
            {"result": result},
            status=200 if result.ok else 422,
        )
    return _trash_redirect(result)
