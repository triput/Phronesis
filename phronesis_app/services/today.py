# ==============================================================================
# File: phronesis_app/services/today.py
# Description: Plan Today ritual — multi-home onto #today (ENG-TODAY) + VX-16 truncate
# Component: Services / Today
# Version: 1.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-30
# ==============================================================================
"""Plan Today / clear today without changing primary container homes."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from phronesis_app.models import AppSettings, ExecutionItem, ItemContainerLink, SystemEnums, WorkspaceContainer

TODAY_VISIBLE_MIN = 1
TODAY_VISIBLE_MAX = 20
TODAY_VISIBLE_DEFAULT = 5
SESSION_SHOW_ALL_KEY = "today_show_all"


@dataclass
class TodayResult:
    """Outcome of plan/clear today operations."""

    ok: bool
    count: int = 0
    message: str = ""


def get_today_container() -> WorkspaceContainer | None:
    """Return the system #today list container."""
    return WorkspaceContainer.objects.filter(slug="today").first()


def today_item_ids() -> set[int]:
    """Item IDs currently linked to #today."""
    container = get_today_container()
    if not container:
        return set()
    return set(
        ItemContainerLink.objects.filter(container=container).values_list("item_id", flat=True)
    )


def _active_items_qs():
    return ExecutionItem.objects.filter(is_deleted=False).exclude(
        status=SystemEnums.ItemStatus.COMPLETED
    )


def clamp_today_visible_limit(value: int | None) -> int:
    """Clamp Truncated Today N into the allowed band."""
    if value is None:
        return TODAY_VISIBLE_DEFAULT
    try:
        n = int(value)
    except (TypeError, ValueError):
        return TODAY_VISIBLE_DEFAULT
    return max(TODAY_VISIBLE_MIN, min(TODAY_VISIBLE_MAX, n))


def get_today_visible_limit(settings: AppSettings | None = None) -> int:
    """Owner preference for how many #today rows show before Expand."""
    solo = settings or AppSettings.get_solo()
    return clamp_today_visible_limit(getattr(solo, "today_visible_limit", TODAY_VISIBLE_DEFAULT))


def set_today_visible_limit(value: int) -> int:
    """Persist Truncated Today N; returns clamped value."""
    n = clamp_today_visible_limit(value)
    solo = AppSettings.get_solo()
    solo.today_visible_limit = n
    solo.save(update_fields=["today_visible_limit"])
    return n


@transaction.atomic
def plan_today(
    item_ids: list[int] | None = None,
    query: str = "",
    limit: int = 12,
) -> TodayResult:
    """
    Multi-home items onto #today without changing primary links.

    When item_ids is omitted, selects active items by optional title query
    or top priority/urgency candidates not already on #today.
    """
    container = get_today_container()
    if not container:
        return TodayResult(ok=False, message="#today container missing.")

    if item_ids:
        items = list(_active_items_qs().filter(pk__in=item_ids))
    elif query.strip():
        items = list(
            _active_items_qs()
            .filter(title__icontains=query.strip())
            .order_by("priority", "due_at", "title")[:limit]
        )
    else:
        already = today_item_ids()
        items = list(
            _active_items_qs()
            .exclude(pk__in=already)
            .order_by("priority", "due_at", "title")[:limit]
        )

    added = 0
    for item in items:
        link, created = ItemContainerLink.objects.get_or_create(
            item=item,
            container=container,
            defaults={"is_primary": False, "pinned": False},
        )
        if created:
            added += 1
        elif link.is_primary:
            continue

    return TodayResult(
        ok=True,
        count=added,
        message=f"Added {added} item(s) to #today." if added else "No new items added to #today.",
    )


@transaction.atomic
def clear_today() -> TodayResult:
    """Remove all non-primary #today links only."""
    container = get_today_container()
    if not container:
        return TodayResult(ok=False, message="#today container missing.")

    deleted, _ = ItemContainerLink.objects.filter(
        container=container,
        is_primary=False,
    ).delete()
    return TodayResult(
        ok=True,
        count=deleted,
        message=f"Cleared {deleted} item(s) from #today.",
    )


def today_items():
    """Active items linked to #today for Planner/Horizon."""
    container = get_today_container()
    if not container:
        return ExecutionItem.objects.none()
    return (
        _active_items_qs()
        .filter(container_links__container=container)
        .prefetch_related("tags", "container_links__container", "allocation")
        .distinct()
        .order_by("priority", "due_at", "title")
    )


def today_panel_items(*, show_all: bool = False, settings: AppSettings | None = None):
    """
    VX-16: items for the #today panel — truncated unless show_all.

    Returns (visible_list, total_count, limit, truncated).
    """
    qs = today_items()
    total = qs.count()
    limit = get_today_visible_limit(settings)
    if show_all or total <= limit:
        return list(qs), total, limit, False
    return list(qs[:limit]), total, limit, True
