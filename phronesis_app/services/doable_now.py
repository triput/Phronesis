# ==============================================================================
# File: phronesis_app/services/doable_now.py
# Description: VX-04 read-only “fits this moment” lens — doable-now ranking
# Component: Services / Doable Now
# Version: 1.0 (Gold Master)
# Created: 2026-07-31
# Last Update: 2026-07-31
# ==============================================================================
"""Read-only “doable now” lens reusing VX-11/14 scheduler availability math.

An item is *doable now* when a tag-eligible availability window overlaps ``now``,
busy intervals leave enough contiguous free time for ``estimated_minutes`` (+ buffer),
the item is active/non-inbox/unscheduled, and it is not blocked by dependencies.

Optional session context tags further narrow candidates to items sharing ≥1 tag.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.db.models import Prefetch
from django.utils import timezone

from phronesis_app.models import AppSettings, ExecutionItem, Tag, TimeAvailabilityBlock
from phronesis_app.services.scheduler import (
    _aware,
    _busy_intervals,
    _free_slots_for_item,
    _rank_item,
    schedulable_candidates,
)
from phronesis_app.services.today import today_item_ids

SESSION_CONTEXT_TAG_IDS_KEY = "doable_now_context_tag_ids"


@dataclass
class DoableNowRow:
    """One ranked item that fits the current moment."""

    item: ExecutionItem
    slot_start: datetime
    minutes: int
    is_today: bool = False


def get_session_context_tag_ids(session) -> list[int] | None:
    """Return selected context tag ids from session, or ``None`` for Any."""
    raw = session.get(SESSION_CONTEXT_TAG_IDS_KEY)
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        return None
    ids: list[int] = []
    for value in raw:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids if ids else None


def set_session_context_tag_ids(session, tag_ids: list[int] | None) -> None:
    """Persist context tag filter; ``None`` or empty clears to Any."""
    if not tag_ids:
        session.pop(SESSION_CONTEXT_TAG_IDS_KEY, None)
    else:
        session[SESSION_CONTEXT_TAG_IDS_KEY] = [int(t) for t in tag_ids]
    session.modified = True


def _item_fits_now(
    item: ExecutionItem,
    *,
    now: datetime,
    blocks: list[TimeAvailabilityBlock],
    busy: list[tuple[datetime, datetime]],
    buffer: timedelta,
    start_day,
) -> tuple[bool, datetime | None]:
    """True when a free fragment contains ``now`` and fits duration (+ buffer).

    Unlike the scheduler (earliest-fit later in the horizon), doable-now rejects
    slots that only open later today. Prior calendar day is included so VX-14
    overnight windows that still cover ``now`` after midnight remain visible.
    """
    duration = timedelta(minutes=max(item.estimated_minutes or 30, 5))
    free = _free_slots_for_item(
        item,
        blocks=blocks,
        start_day=start_day - timedelta(days=1),
        end_day=start_day,
        busy=busy,
    )
    for slot_start, slot_end in free:
        # Window must overlap this instant — not merely admit a later start.
        if not (slot_start <= now < slot_end):
            continue
        if now + duration + buffer <= slot_end:
            return True, now
    return False, None


def _rank_doable(row: DoableNowRow, *, prefer_today: bool) -> tuple:
    """Sort key: #today boost, then scheduler priority/urgency/due/title."""
    today_boost = 0 if prefer_today and row.is_today else 1
    base = _rank_item(row.item)
    return (today_boost, *base)


def doable_now_items(
    *,
    now: datetime | None = None,
    context_tag_ids: list[int] | None = None,
    limit: int = 5,
    prefer_today: bool = True,
) -> list[DoableNowRow]:
    """
    Rank items that fit the current moment.

    Parameters
    ----------
    now:
        Reference instant (defaults to ``timezone.now()``).
    context_tag_ids:
        When set, only items with ≥1 matching tag id (still pass block gates).
        ``None`` means no context filter (Any).
    limit:
        Maximum rows returned after ranking.
    prefer_today:
        When True, items on #today sort before others at equal priority.
    """
    now = now or timezone.now()
    settings = AppSettings.get_solo()
    buffer = timedelta(minutes=settings.scheduler_buffer_minutes or 0)
    start_day = now.date()
    horizon_end = _aware(datetime.combine(start_day, time.max))

    blocks = list(
        TimeAvailabilityBlock.objects.prefetch_related(
            Prefetch("tags", queryset=Tag.objects.only("id"))
        ).all()
    )
    if not blocks:
        return []

    busy = _busy_intervals(now, horizon_end)
    today_ids = today_item_ids() if prefer_today else set()
    context_filter = set(context_tag_ids) if context_tag_ids else None

    scored: list[tuple[tuple, DoableNowRow]] = []
    for item in schedulable_candidates():
        if context_filter is not None:
            item_tag_ids = {t.pk for t in item.tags.all()}
            if not (item_tag_ids & context_filter):
                continue

        fits, slot_start = _item_fits_now(
            item,
            now=now,
            blocks=blocks,
            busy=busy,
            buffer=buffer,
            start_day=start_day,
        )
        if not fits or slot_start is None:
            continue

        minutes = max(item.estimated_minutes or 30, 5)
        row = DoableNowRow(
            item=item,
            slot_start=slot_start,
            minutes=minutes,
            is_today=item.pk in today_ids,
        )
        scored.append((_rank_doable(row, prefer_today=prefer_today), row))

    scored.sort(key=lambda pair: pair[0])
    return [row for _, row in scored[: max(limit, 0)]]


def doable_now_id_set(**kwargs) -> set[int]:
    """Item ids currently doable — handy for plan badges."""
    return {row.item.pk for row in doable_now_items(**kwargs)}


def build_doable_now_context(*, request=None, limit: int = 5) -> dict:
    """Template context for Home strip and Plan sidebar."""
    context_tag_ids = get_session_context_tag_ids(request.session) if request else None
    rows = doable_now_items(context_tag_ids=context_tag_ids, limit=limit)
    context_tags = list(Tag.objects.order_by("name"))
    selected = context_tag_ids or []
    return {
        "doable_now_rows": rows,
        "doable_context_tags": context_tags,
        "doable_context_selected": selected,
        "doable_context_any": context_tag_ids is None,
        "doable_now_ids": {row.item.pk for row in rows},
    }
