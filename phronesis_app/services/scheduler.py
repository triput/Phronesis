# ==============================================================================
# File: phronesis_app/services/scheduler.py
# Description: Deterministic scheduling engine (ENG-SCHED)
# Component: Services / Scheduler
# Version: 1.2 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-31
# ==============================================================================
"""Greedy earliest-fit scheduler — tag-gated availability, busy subtraction, deps.

VX-01 horizon is an inclusive calendar-day count (1 = today only; 7 = today..+6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch
from django.utils import timezone

from phronesis_app.models import (
    AppSettings,
    CalendarEvent,
    ExecutionItem,
    ItemDependencyLink,
    ScheduledAllocation,
    SystemEnums,
    Tag,
    TimeAvailabilityBlock,
)

URGENCY_RANK = {
    SystemEnums.UrgencyLevel.IMMEDIATE: 0,
    SystemEnums.UrgencyLevel.HIGH: 1,
    SystemEnums.UrgencyLevel.NORMAL: 2,
    SystemEnums.UrgencyLevel.LOW: 3,
}

_WEEKDAY_FIELDS = (
    "day_monday",
    "day_tuesday",
    "day_wednesday",
    "day_thursday",
    "day_friday",
    "day_saturday",
    "day_sunday",
)


@dataclass
class ScheduleRunResult:
    """Summary of a scheduler pass."""

    ok: bool
    placed: int = 0
    cleared: int = 0
    pinned: int = 0
    skipped_blocked: int = 0
    skipped_no_slot: int = 0
    skipped_past_due: int = 0
    message: str = ""
    warnings: list[str] = field(default_factory=list)


def _clamp_settings_horizon(days: int) -> int:
    """Clamp AppSettings horizon to 1–14 days."""
    return max(1, min(int(days or 7), 14))


def _blocked_item_ids() -> set[int]:
    """Items with unmet BLOCKS dependencies."""
    open_block = ItemDependencyLink.objects.filter(
        from_item=OuterRef("pk"),
        link_type=SystemEnums.DependencyLinkType.BLOCKS,
        to_item__is_deleted=False,
    ).exclude(to_item__status=SystemEnums.ItemStatus.COMPLETED)
    return set(
        ExecutionItem.objects.filter(is_deleted=False)
        .annotate(blocked=Exists(open_block))
        .filter(blocked=True)
        .values_list("pk", flat=True)
    )


def schedulable_candidates():
    """Active items without allocation, excluding dependency-blocked."""
    blocked = _blocked_item_ids()
    return (
        ExecutionItem.objects.filter(is_deleted=False)
        .exclude(status=SystemEnums.ItemStatus.COMPLETED)
        .exclude(status=SystemEnums.ItemStatus.INBOX)
        .filter(allocation__isnull=True)
        .exclude(pk__in=blocked)
        .prefetch_related("tags")
        .order_by("priority", "due_at", "title")
    )


def _day_enabled(block: TimeAvailabilityBlock, weekday: int) -> bool:
    return getattr(block, _WEEKDAY_FIELDS[weekday])


def _aware(dt: datetime) -> datetime:
    if timezone.is_aware(dt):
        return dt
    return timezone.make_aware(dt, timezone.get_current_timezone())


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    sorted_iv = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_iv[0]]
    for start, end in sorted_iv[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _subtract_intervals(
    free: list[tuple[datetime, datetime]],
    busy: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    if not busy:
        return free
    result: list[tuple[datetime, datetime]] = []
    busy_m = _merge_intervals(busy)
    for f_start, f_end in free:
        cursor = f_start
        for b_start, b_end in busy_m:
            if b_end <= cursor or b_start >= f_end:
                continue
            if b_start > cursor:
                result.append((cursor, min(b_start, f_end)))
            cursor = max(cursor, b_end)
            if cursor >= f_end:
                break
        if cursor < f_end:
            result.append((cursor, f_end))
    return [(s, e) for s, e in result if e > s]


def _block_tag_ids(block: TimeAvailabilityBlock) -> set[int]:
    """Tag ids on a block (uses prefetch cache when present)."""
    return {t.pk for t in block.tags.all()}


def _block_open_to_item(block: TimeAvailabilityBlock, item_tag_ids: set[int]) -> bool:
    """VX-11 hard gate: open blocks accept anyone; restricted need ≥1 shared tag."""
    block_tags = _block_tag_ids(block)
    if not block_tags:
        return True
    if not item_tag_ids:
        return False
    return bool(block_tags & item_tag_ids)


def _item_domain_id(item: ExecutionItem) -> int | None:
    """Domain via primary container, if any (soft preference only)."""
    primary = item.primary_container()
    if primary is None:
        return None
    return primary.domain_id


def _availability_windows(
    start_day: date,
    end_day: date,
    blocks: list[TimeAvailabilityBlock],
) -> list[tuple[datetime, datetime]]:
    """Materialize weekly blocks into concrete intervals (overnight end ≤ start → next day)."""
    windows: list[tuple[datetime, datetime]] = []
    day = start_day
    while day <= end_day:
        for block in blocks:
            if _day_enabled(block, day.weekday()):
                start_dt = _aware(datetime.combine(day, block.start_time))
                end_dt = _aware(datetime.combine(day, block.end_time))
                # VX-14 thin: overnight windows span midnight as one free interval.
                if end_dt <= start_dt:
                    end_dt = end_dt + timedelta(days=1)
                if end_dt > start_dt:
                    windows.append((start_dt, end_dt))
        day += timedelta(days=1)
    return windows


def _busy_intervals(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    busy: list[tuple[datetime, datetime]] = []
    for ev in CalendarEvent.objects.filter(
        is_blocking=True,
        start_at__lt=end,
        end_at__gt=start,
    ):
        busy.append((ev.start_at, ev.end_at))
    for alloc in ScheduledAllocation.objects.filter(start_at__lt=end, end_at__gt=start):
        busy.append((alloc.start_at, alloc.end_at))
    return busy


def _rank_item(item: ExecutionItem) -> tuple:
    return (
        item.priority,
        URGENCY_RANK.get(item.urgency, 9),
        item.due_at or timezone.make_aware(datetime.max.replace(tzinfo=None)),
        item.title,
    )


def _free_slots_for_item(
    item: ExecutionItem,
    *,
    blocks: list[TimeAvailabilityBlock],
    start_day: date,
    end_day: date,
    busy: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """
    Build free intervals for one item from tag-eligible blocks.

    Soft preference: when the item has a domain and some eligible blocks share that
    domain, try those windows first (then remaining open/matching windows).
    """
    item_tag_ids = {t.pk for t in item.tags.all()}
    eligible = [b for b in blocks if _block_open_to_item(b, item_tag_ids)]
    if not eligible:
        return []

    item_domain = _item_domain_id(item)
    preferred = [b for b in eligible if item_domain and b.domain_id == item_domain]
    other = [b for b in eligible if b not in preferred] if preferred else eligible

    ordered: list[tuple[datetime, datetime]] = []
    for group in (preferred, other) if preferred else (eligible,):
        windows = _merge_intervals(_availability_windows(start_day, end_day, group))
        ordered.extend(_subtract_intervals(windows, busy))
    return ordered


def _overlaps_busy(
    start: datetime,
    occupied_end: datetime,
    busy: list[tuple[datetime, datetime]],
) -> bool:
    for b_start, b_end in busy:
        if b_start < occupied_end and b_end > start:
            return True
    return False


def _fits_in_free_slot(
    start: datetime,
    duration: timedelta,
    buffer: timedelta,
    free: list[tuple[datetime, datetime]],
    *,
    now: datetime,
) -> bool:
    end_with_buffer = start + duration + buffer
    for slot_start, slot_end in free:
        effective_start = max(slot_start, now)
        if start >= effective_start and end_with_buffer <= slot_end:
            return True
    return False


def _due_allows_end(end: datetime, due_at: datetime | None) -> bool:
    return due_at is None or end <= due_at


def _clear_solver_allocations_in_horizon(now: datetime, horizon_end: datetime) -> int:
    """Delete SOLVER placements whose start falls in [now, horizon_end); preserve MANUAL."""
    deleted, _ = ScheduledAllocation.objects.filter(
        source=SystemEnums.AllocationSource.SOLVER,
        start_at__gte=now,
        start_at__lt=horizon_end,
    ).delete()
    return deleted


def _place_item(
    item: ExecutionItem,
    *,
    start: datetime,
    duration: timedelta,
    buffer: timedelta,
    busy: list[tuple[datetime, datetime]],
) -> ScheduledAllocation:
    alloc = ScheduledAllocation.objects.create(
        execution_item=item,
        start_at=start,
        end_at=start + duration,
        score=float(100 - item.priority * 10),
        source=SystemEnums.AllocationSource.SOLVER,
    )
    from phronesis_app.services.reminders import rearm_allocation_reminders

    rearm_allocation_reminders(alloc)
    # ``end`` already includes the policy buffer used for fit; it is the next legal start.
    busy.append((start, start + duration + buffer))
    return alloc


def _try_pinned_placement(
    item: ExecutionItem,
    *,
    pinned_start: datetime,
    duration: timedelta,
    buffer: timedelta,
    free: list[tuple[datetime, datetime]],
    busy: list[tuple[datetime, datetime]],
    now: datetime,
) -> datetime | None:
    """Return pinned start when exact placement is feasible, else None."""
    if pinned_start < now:
        return None
    end = pinned_start + duration
    if not _due_allows_end(end, item.due_at):
        return None
    occupied_end = end + buffer
    if _overlaps_busy(pinned_start, occupied_end, busy):
        return None
    if not _fits_in_free_slot(pinned_start, duration, buffer, free, now=now):
        return None
    return pinned_start


def _try_greedy_placement(
    item: ExecutionItem,
    *,
    duration: timedelta,
    buffer: timedelta,
    free: list[tuple[datetime, datetime]],
    busy: list[tuple[datetime, datetime]],
    now: datetime,
) -> datetime | None:
    """Earliest-fit slot respecting due_at ceiling."""
    for slot_start, slot_end in free:
        start = max(slot_start, now)
        end = start + duration
        if not _due_allows_end(end, item.due_at):
            continue
        occupied_end = end + buffer
        if occupied_end <= slot_end and not _overlaps_busy(start, occupied_end, busy):
            return start
    return None


@transaction.atomic
def run_scheduler(horizon_days: int | None = None, replan: bool | None = None) -> ScheduleRunResult:
    """
    Greedy earliest-fit placement into tag-eligible availability minus busy time.

    VX-01: optional multi-day re-plan clears ``SOLVER`` allocations whose start
    falls in the horizon before placement; ``MANUAL`` (and other sources) are kept.
    When ``horizon_days`` / ``replan`` are ``None``, values come from ``AppSettings``
    (horizon clamped 1–14). Explicit ``horizon_days=0`` remains valid for same-day
    runs (tests / legacy).

    ``due_at`` acts as a hard ceiling: placements whose end would exceed ``due_at``
    are skipped (``skipped_past_due``). Items with ``start_at`` try that instant
    first (tag gates + busy + duration + buffer); infeasible pins fall back to
    greedy with a warning.

    Calendar push (P5-03): when enabled, newly placed rows are pushed best-effort;
    cleared solver rows may leave stale external events until the next push cycle.
    """
    settings = AppSettings.get_solo()
    if horizon_days is None:
        horizon_days = _clamp_settings_horizon(settings.scheduler_horizon_days)
    if replan is None:
        replan = bool(settings.scheduler_replan_enabled)

    buffer = timedelta(minutes=settings.scheduler_buffer_minutes or 0)
    now = timezone.now()
    start_day = now.date()
    # Inclusive calendar span: horizon=1 → today only; horizon=7 → today..today+6.
    # Explicit horizon_days=0 (tests/legacy) also collapses to today.
    end_day = start_day + timedelta(days=max(int(horizon_days) - 1, 0))
    horizon_end = _aware(datetime.combine(end_day, time.max))

    blocks = list(
        TimeAvailabilityBlock.objects.prefetch_related(
            Prefetch("tags", queryset=Tag.objects.only("id"))
        ).all()
    )
    if not blocks:
        return ScheduleRunResult(
            ok=False,
            message="No availability blocks configured.",
            warnings=["Add availability in Settings or seed_data."],
        )

    cleared = 0
    if replan:
        cleared = _clear_solver_allocations_in_horizon(now, horizon_end)

    busy = _busy_intervals(now, horizon_end)

    blocked_ids = _blocked_item_ids()
    candidates = list(schedulable_candidates())
    skipped_blocked = len(
        ExecutionItem.objects.filter(
            pk__in=blocked_ids,
            is_deleted=False,
            allocation__isnull=True,
        ).exclude(status=SystemEnums.ItemStatus.COMPLETED)
    )

    candidates.sort(key=_rank_item)
    placed = 0
    pinned_count = 0
    skipped_no_slot = 0
    skipped_past_due = 0
    warnings: list[str] = []

    for item in candidates:
        duration = timedelta(minutes=max(item.estimated_minutes or 30, 5))

        if item.due_at and item.due_at < now:
            skipped_past_due += 1
            warnings.append(f"Skipped “{item.title}” — due date already passed.")
            continue

        free = _free_slots_for_item(
            item,
            blocks=blocks,
            start_day=start_day,
            end_day=end_day,
            busy=busy,
        )
        if not free:
            skipped_no_slot += 1
            warnings.append(
                f"Could not place “{item.title}” — no free slot "
                f"(estimate {int(duration.total_seconds() // 60)}m; "
                f"check tag↔availability windows and capacity)."
            )
            continue

        start: datetime | None = None
        used_pin = False
        if item.start_at:
            pinned = _aware(item.start_at)
            start = _try_pinned_placement(
                item,
                pinned_start=pinned,
                duration=duration,
                buffer=buffer,
                free=free,
                busy=busy,
                now=now,
            )
            if start is not None:
                used_pin = True
            else:
                warnings.append(
                    f"Pinned start infeasible for “{item.title}” — falling back to earliest fit."
                )

        if start is None:
            start = _try_greedy_placement(
                item,
                duration=duration,
                buffer=buffer,
                free=free,
                busy=busy,
                now=now,
            )

        if start is None:
            if item.due_at and not any(
                _due_allows_end(max(slot_start, now) + duration, item.due_at)
                for slot_start, _slot_end in free
            ):
                skipped_past_due += 1
                warnings.append(
                    f"Skipped “{item.title}” — no slot before due "
                    f"({item.due_at.strftime('%Y-%m-%d %H:%M')})."
                )
            else:
                skipped_no_slot += 1
                warnings.append(
                    f"Could not place “{item.title}” — no free slot "
                    f"(estimate {int(duration.total_seconds() // 60)}m; "
                    f"check tag↔availability windows and capacity)."
                )
            continue

        _place_item(item, start=start, duration=duration, buffer=buffer, busy=busy)
        placed += 1
        if used_pin:
            pinned_count += 1

    msg = f"Scheduled {placed} item(s) over {horizon_days} day(s)."
    if cleared:
        msg += f" Cleared {cleared} solver placement(s)."
    if pinned_count:
        msg += f" {pinned_count} at pinned start."
    if skipped_blocked:
        msg += f" Skipped {skipped_blocked} blocked by dependencies."
    if skipped_past_due:
        msg += f" {skipped_past_due} past due / no slot before due."
    if skipped_no_slot:
        msg += f" {skipped_no_slot} had no free slot."

    # P5-03: optional Google push after placement (feature-flagged).
    from phronesis_app.services.calendar_push import push_pending_allocations

    push = push_pending_allocations()
    if push.message:
        msg += f" {push.message}"

    return ScheduleRunResult(
        ok=True,
        placed=placed,
        cleared=cleared,
        pinned=pinned_count,
        skipped_blocked=skipped_blocked,
        skipped_no_slot=skipped_no_slot,
        skipped_past_due=skipped_past_due,
        message=msg,
        warnings=warnings,
    )
