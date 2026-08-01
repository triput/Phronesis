# ==============================================================================
# File: phronesis_app/services/time_targets.py
# Description: VX-17 weekly time-target progress math and row builders
# Component: Services / Time Targets
# Version: 1.0 (Gold Master)
# Created: 2026-07-30
# Last Update: 2026-07-30
# ==============================================================================
"""Informational weekly minutes goals per domain and/or tag.

**Progress rule (VX-17):** for the current local week (Mon 00:00 → next Mon),

1. Sum FocusSession seconds for matching items — closed sessions whose
   ``ended_at`` falls in the week use ``duration_seconds``; an open session
   started before week end contributes elapsed seconds clipped to the week
   (plus any accumulated ``duration_seconds`` on that row).
2. Plus allocation span minutes (clipped to the week) for matching items that
   have **zero** focus seconds in that week.

Matching: domain via primary container domain; tag via item tags; both set →
item must satisfy domain **and** tag. Never a hard schedule block.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db.models import Sum
from django.utils import timezone

from phronesis_app.models import (
    AppSettings,
    ExecutionItem,
    FocusSession,
    ScheduledAllocation,
    TimeTarget,
)
from phronesis_app.services.stability import local_day_bounds, owner_tz, today_local


@dataclass
class TimeTargetProgress:
    """One target plus current-week progress for UI bars."""

    target: TimeTarget
    week_start: date
    week_end: date  # exclusive local date (next Monday)
    focus_seconds: int
    allocation_minutes: int
    progress_minutes: int
    target_minutes: int
    pct: int

    @property
    def label(self) -> str:
        return self.target.label


def local_week_bounds(
    settings: AppSettings | None = None,
    *,
    as_of: date | None = None,
) -> tuple[datetime, datetime]:
    """Owner-local ISO week [Monday 00:00, next Monday 00:00)."""
    day = as_of or today_local(settings)
    monday = day - timedelta(days=day.weekday())
    start, _ = local_day_bounds(monday, settings)
    end = start + timedelta(days=7)
    return start, end


def matching_item_ids(target: TimeTarget) -> set[int]:
    """ExecutionItem PKs that count toward this target."""
    qs = ExecutionItem.objects.filter(is_deleted=False)
    if target.domain_id and target.tag_id:
        qs = qs.filter(
            container_links__is_primary=True,
            container_links__container__domain_id=target.domain_id,
            tags=target.tag_id,
        )
    elif target.domain_id:
        qs = qs.filter(
            container_links__is_primary=True,
            container_links__container__domain_id=target.domain_id,
        )
    elif target.tag_id:
        qs = qs.filter(tags=target.tag_id)
    else:
        return set()
    return set(qs.values_list("pk", flat=True).distinct())


def _focus_seconds_for_items(
    item_ids: set[int],
    week_start: datetime,
    week_end: datetime,
) -> dict[int, int]:
    """Per-item focus seconds attributed to the week."""
    if not item_ids:
        return {}
    by_item: dict[int, int] = {iid: 0 for iid in item_ids}
    now = timezone.now()

    closed = FocusSession.objects.filter(
        execution_item_id__in=item_ids,
        ended_at__isnull=False,
        ended_at__gte=week_start,
        ended_at__lt=week_end,
    ).values("execution_item_id").annotate(total=Sum("duration_seconds"))
    for row in closed:
        by_item[row["execution_item_id"]] = by_item.get(row["execution_item_id"], 0) + int(
            row["total"] or 0
        )

    for session in FocusSession.objects.filter(
        execution_item_id__in=item_ids,
        ended_at__isnull=True,
        started_at__lt=week_end,
    ):
        # Clip open session to week window; ignore if entirely before week.
        clip_start = max(session.started_at, week_start)
        if clip_start >= week_end:
            continue
        clip_end = min(now, week_end)
        if clip_end <= clip_start:
            continue
        elapsed = max(0, int((clip_end - clip_start).total_seconds()))
        elapsed += int(session.duration_seconds or 0)
        by_item[session.execution_item_id] = by_item.get(session.execution_item_id, 0) + elapsed

    return by_item


def _allocation_minutes_for_items_without_focus(
    item_ids: set[int],
    focus_by_item: dict[int, int],
    week_start: datetime,
    week_end: datetime,
) -> int:
    """Sum clipped allocation spans for matching items with zero focus this week."""
    zero_focus = {iid for iid in item_ids if focus_by_item.get(iid, 0) <= 0}
    if not zero_focus:
        return 0
    total_seconds = 0
    for alloc in ScheduledAllocation.objects.filter(
        execution_item_id__in=zero_focus,
        start_at__lt=week_end,
        end_at__gt=week_start,
    ):
        clip_start = max(alloc.start_at, week_start)
        clip_end = min(alloc.end_at, week_end)
        if clip_end > clip_start:
            total_seconds += int((clip_end - clip_start).total_seconds())
    return total_seconds // 60


def compute_target_progress(
    target: TimeTarget,
    *,
    settings: AppSettings | None = None,
    as_of: date | None = None,
) -> TimeTargetProgress:
    """Progress minutes and capped percent for one target in the current local week."""
    settings = settings or AppSettings.get_solo()
    week_start, week_end = local_week_bounds(settings, as_of=as_of)
    item_ids = matching_item_ids(target)
    focus_by_item = _focus_seconds_for_items(item_ids, week_start, week_end)
    focus_seconds = sum(focus_by_item.values())
    allocation_minutes = _allocation_minutes_for_items_without_focus(
        item_ids, focus_by_item, week_start, week_end
    )
    progress_minutes = (focus_seconds // 60) + allocation_minutes
    target_minutes = max(1, int(target.minutes_per_week or 1))
    pct = max(0, min(100, int(round(100.0 * progress_minutes / target_minutes))))
    tz = owner_tz(settings)
    return TimeTargetProgress(
        target=target,
        week_start=week_start.astimezone(tz).date(),
        week_end=week_end.astimezone(tz).date(),
        focus_seconds=focus_seconds,
        allocation_minutes=allocation_minutes,
        progress_minutes=progress_minutes,
        target_minutes=target_minutes,
        pct=pct,
    )


def build_time_target_rows(
    *,
    settings: AppSettings | None = None,
    as_of: date | None = None,
) -> list[TimeTargetProgress]:
    """All targets with progress for Settings / Plan strip."""
    settings = settings or AppSettings.get_solo()
    targets = (
        TimeTarget.objects.select_related("domain", "tag").order_by(
            "domain__name", "tag__name", "id"
        )
    )
    return [compute_target_progress(t, settings=settings, as_of=as_of) for t in targets]
