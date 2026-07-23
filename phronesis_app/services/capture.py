# ==============================================================================
# File: phronesis_app/services/capture.py
# Description: Deterministic Lightning Capture parser (ENG-CMD Tier 1)
# Component: Services / Command Engine
# Version: 1.4 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-22
# ==============================================================================
"""Token-based capture parser for Cmd+K Lightning Capture.

Title protection
----------------
1. **Quoted title** (preferred when the title looks like a command)::

       "go grocery shopping" / #inbox p2
       'focus on breathing' tomorrow ~15m

   Leading ``'`` or ``"`` with a matching closer → title is verbatim (quotes
   stripped). Remainder is attributes only (optional `` / `` before attrs).
   Cmd mode detection also treats a leading quote as capture, so ``go`` /
   ``focus`` inside quotes never navigate or start a focus action.

2. **Spaced slash**::

       Do more silly stuff / #container p2 @tag due friday ~30m

   Everything before the first `` / `` is the title verbatim.

3. **Legacy mixed tokenizer** (no quote, no `` / ``): attribute tokens still
   interleave with title words, but bare chrono uses English-only dateparser
   plus a day/month/time allowlist so multilang dateparser cannot eat title
   words (DE ``Do`` = Thursday, etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from phronesis_app.models import SystemEnums, WorkspaceContainer
from phronesis_app.services.recurrence import RecurrencePreview, extract_recurrence
from phronesis_app.services.time_format import parse_duration_minutes

try:
    import dateparser
except ImportError:  # pragma: no cover - optional until requirements install
    dateparser = None  # type: ignore[assignment]

# Title | attributes — first spaced slash wins (see module docstring).
ATTR_DELIMITER_RE = re.compile(r"\s/\s")

# Order-independent token patterns
CONTAINER_RE = re.compile(r"^#([\w-]+)$", re.IGNORECASE)
TAG_RE = re.compile(r"^@([\w-]+)$", re.IGNORECASE)
PRIORITY_RE = re.compile(r"^p([1-4])$", re.IGNORECASE)
URGENCY_MAP = {
    "!urgent": SystemEnums.UrgencyLevel.HIGH,
    "!immediate": SystemEnums.UrgencyLevel.IMMEDIATE,
    "urgent": SystemEnums.UrgencyLevel.HIGH,
    "immediate": SystemEnums.UrgencyLevel.IMMEDIATE,
}
FUZZY_MAP = {
    "today": SystemEnums.FuzzyTimeframe.TODAY,
    "tomorrow": SystemEnums.FuzzyTimeframe.TOMORROW,
    "weekend": SystemEnums.FuzzyTimeframe.WEEKEND,
    "this-week": SystemEnums.FuzzyTimeframe.THIS_WEEK,
    "this_week": SystemEnums.FuzzyTimeframe.THIS_WEEK,
    "this-month": SystemEnums.FuzzyTimeframe.THIS_MONTH,
    "this_month": SystemEnums.FuzzyTimeframe.THIS_MONTH,
}
CHRONO_PREFIXES = ("due", "by", "at", "on")
ESTIMATE_PREFIXES = ("for", "est", "estimate")

# Bare-token chrono allowlist — dateparser is greedy across locales (e.g. DE "Do"
# = Thursday) and will eat title words like "Do" / "more" unless gated.
_DAY_NAMES = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "mon",
    "tue",
    "tues",
    "wed",
    "thu",
    "thur",
    "thurs",
    "fri",
    "sat",
    "sun",
}
_MONTH_NAMES = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
}
_PAIR_STARTERS = frozenset({"next", "this", "last", "coming"})
_TIME_TOKEN_RE = re.compile(
    r"^\d{1,2}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.)?$",
    re.IGNORECASE,
)
_NUMERIC_DATE_RE = re.compile(r"^\d{1,4}[-/.]\d{1,2}([-/]\d{1,4})?$")


@dataclass
class CapturePreview:
    """Structured preview of a capture-mode parse."""

    raw: str
    title: str = ""
    container_slug: str | None = None
    container_title: str | None = None
    container_found: bool = False
    tag_slugs: list[str] = field(default_factory=list)
    priority: int | None = None
    urgency: str | None = None
    due_at: datetime | None = None
    estimated_minutes: int | None = None
    fuzzy_timeframe: str = SystemEnums.FuzzyTimeframe.NONE
    status: str = SystemEnums.ItemStatus.INBOX
    recurrence: RecurrencePreview | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "title": self.title,
            "container_slug": self.container_slug,
            "container_title": self.container_title,
            "container_found": self.container_found,
            "tag_slugs": self.tag_slugs,
            "priority": self.priority,
            "urgency": self.urgency,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "estimated_minutes": self.estimated_minutes,
            "fuzzy_timeframe": self.fuzzy_timeframe,
            "status": self.status,
            "recurrence": self.recurrence.as_dict() if self.recurrence else None,
            "warnings": self.warnings,
        }


def _normalize_chrono_atom(tok: str) -> str:
    """Lowercase token with trailing punctuation stripped for chrono matching."""
    return tok.lower().rstrip(",.;:")


def _looks_like_chrono_token(tok: str) -> bool:
    """True when a bare token is safe to feed to dateparser as a due date."""
    lower = _normalize_chrono_atom(tok)
    if not lower:
        return False
    if lower in _DAY_NAMES or lower in _MONTH_NAMES:
        return True
    if _TIME_TOKEN_RE.match(lower) or _NUMERIC_DATE_RE.match(lower):
        return True
    return False


def _looks_like_chrono_pair(first: str, second: str) -> bool:
    """True when a two-token phrase is intentional chrono (next friday, July 4)."""
    f = _normalize_chrono_atom(first)
    s = _normalize_chrono_atom(second)
    if f in _PAIR_STARTERS and (s in _DAY_NAMES or s in _MONTH_NAMES):
        return True
    if f in _MONTH_NAMES and (s.isdigit() or _NUMERIC_DATE_RE.match(s)):
        return True
    if _looks_like_chrono_token(first) and _looks_like_chrono_token(second):
        return True
    return False


def _parse_chrono_phrase(phrase: str, tz_name: str) -> datetime | None:
    """Parse a chrono phrase with dateparser when available (English only)."""
    if not phrase.strip():
        return None
    if dateparser is None:
        return None
    # languages=['en'] — multilang dateparser maps DE "Do"→Thursday, etc.
    parsed = dateparser.parse(
        phrase,
        languages=["en"],
        settings={
            "TIMEZONE": tz_name,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
        },
    )
    return parsed


def _split_quoted_title(text: str) -> tuple[str, str] | None:
    """If text starts with a matching ' or \" pair, return (title, attr_remainder).

    Supports simple backslash escapes for the quote character and backslash.
    Leading ``/`` on the remainder (with or without spaces) is stripped so
    ``\"title\" / p2`` and ``\"title\" p2`` both treat ``p2`` as attributes.
    Unclosed quotes return None (caller falls through to slash/mixed parse).
    """
    text = text.strip()
    if len(text) < 2 or text[0] not in "'\"":
        return None
    quote = text[0]
    chars: list[str] = []
    i = 1
    closed = False
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            chars.append(text[i + 1])
            i += 2
            continue
        if ch == quote:
            closed = True
            i += 1
            break
        chars.append(ch)
        i += 1
    if not closed:
        return None
    title = "".join(chars)
    rest = text[i:].strip()
    if rest.startswith("/"):
        rest = rest[1:].strip()
    return title, rest


def _split_title_and_attrs(text: str) -> tuple[str | None, str]:
    """Split on first spaced slash. Returns (title_or_None, attrs_or_full)."""
    match = ATTR_DELIMITER_RE.search(text)
    if not match:
        return None, text
    title = text[: match.start()].strip()
    attrs = text[match.end() :].strip()
    return title, attrs


def _apply_attr_side(preview: CapturePreview, attr_side: str, tz_name: str) -> None:
    """Parse recurrence + attribute tokens from the attrs-only segment."""
    attr_working, recurrence = extract_recurrence(attr_side, tz_name=tz_name)
    preview.recurrence = recurrence
    if recurrence:
        if recurrence.ambiguous and recurrence.warning:
            preview.warnings.append(recurrence.warning)
        elif recurrence.next_occurrence_at and preview.due_at is None:
            preview.due_at = recurrence.next_occurrence_at
    if attr_working.strip():
        _consume_tokens(
            preview,
            attr_working.split(),
            tz_name,
            collect_title=False,
        )

def _consume_tokens(
    preview: CapturePreview,
    tokens: list[str],
    tz_name: str,
    *,
    collect_title: bool,
) -> None:
    """Apply attribute tokens; optionally collect unrecognized tokens as title."""
    title_parts: list[str] = []
    chrono_parts: list[str] = []
    ignored_attrs: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        lower = tok.lower()

        m = CONTAINER_RE.match(tok)
        if m:
            slug = m.group(1).lower()
            preview.container_slug = slug
            container = WorkspaceContainer.objects.filter(slug=slug).first()
            if container:
                preview.container_found = True
                preview.container_title = container.title
            else:
                preview.warnings.append(f"Unknown container #{slug} — will land in Inbox.")
            i += 1
            continue

        m = TAG_RE.match(tok)
        if m:
            preview.tag_slugs.append(m.group(1).lower())
            i += 1
            continue

        m = PRIORITY_RE.match(tok)
        if m:
            preview.priority = int(m.group(1))
            i += 1
            continue

        if lower in URGENCY_MAP:
            preview.urgency = URGENCY_MAP[lower]
            i += 1
            continue

        if lower in FUZZY_MAP:
            preview.fuzzy_timeframe = FUZZY_MAP[lower]
            i += 1
            continue

        # Estimate: ~2h · for 90m · est 1h
        if tok.startswith("~"):
            mins = parse_duration_minutes(tok[1:])
            if mins:
                preview.estimated_minutes = mins
                i += 1
                continue

        if lower in ESTIMATE_PREFIXES and i + 1 < len(tokens):
            mins = parse_duration_minutes(tokens[i + 1])
            if mins:
                preview.estimated_minutes = mins
                i += 2
                continue

        if lower in CHRONO_PREFIXES and i + 1 < len(tokens):
            # Bare "at 9am" without "every" is one-shot chrono; recurrence already stripped.
            chrono_parts.append(" ".join(tokens[i:]))
            break

        if lower in ("due", "by") and i + 1 < len(tokens):
            chrono_parts.append(" ".join(tokens[i + 1 :]))
            break

        # Inline chrono — only day/month/time-shaped tokens (never "Do"/"more").
        if dateparser is not None:
            if _looks_like_chrono_token(tok):
                trial = _parse_chrono_phrase(tok, tz_name)
                if trial and trial > timezone.now() - timedelta(hours=12):
                    preview.due_at = trial
                    i += 1
                    continue
            if i + 1 < len(tokens) and _looks_like_chrono_pair(tok, tokens[i + 1]):
                pair = f"{tok} {tokens[i + 1]}"
                trial_pair = _parse_chrono_phrase(pair, tz_name)
                if trial_pair:
                    preview.due_at = trial_pair
                    i += 2
                    continue

        if collect_title:
            title_parts.append(tok)
        else:
            ignored_attrs.append(tok)
        i += 1

    if ignored_attrs:
        preview.warnings.append(
            "Ignored in attributes (not tokens): " + " ".join(ignored_attrs)
        )

    if chrono_parts and preview.due_at is None:
        phrase = chrono_parts[0]
        if phrase.lower().startswith("due "):
            phrase = phrase[4:]
        parsed = _parse_chrono_phrase(phrase, tz_name)
        if parsed:
            preview.due_at = parsed
        else:
            preview.warnings.append(f"Could not parse date: {phrase!r}")

    if collect_title:
        preview.title = " ".join(title_parts).strip()


def _finalize_status(preview: CapturePreview) -> None:
    """Derive inbox/backlog/planned from container + due."""
    if preview.container_found:
        preview.status = SystemEnums.ItemStatus.BACKLOG
    else:
        preview.status = SystemEnums.ItemStatus.INBOX

    if preview.due_at and preview.status == SystemEnums.ItemStatus.BACKLOG:
        preview.status = SystemEnums.ItemStatus.PLANNED

    if (
        preview.recurrence
        and not preview.recurrence.ambiguous
        and preview.recurrence.next_occurrence_at
        and preview.due_at is None
    ):
        preview.due_at = preview.recurrence.next_occurrence_at
        if preview.status == SystemEnums.ItemStatus.BACKLOG:
            preview.status = SystemEnums.ItemStatus.PLANNED


def parse_capture(raw: str, tz_name: str = "UTC") -> CapturePreview:
    """Parse free-text capture input into structured preview fields."""
    preview = CapturePreview(raw=raw.strip())
    if not preview.raw:
        preview.warnings.append("Enter a title or tokens to capture.")
        return preview

    quoted = _split_quoted_title(preview.raw)
    if quoted is not None:
        preview.title, attr_side = quoted
        _apply_attr_side(preview, attr_side, tz_name)
        if not preview.title.strip():
            preview.warnings.append("Empty quoted title — add text inside the quotes.")
            preview.title = preview.raw
        _finalize_status(preview)
        return preview

    title_side, attr_side = _split_title_and_attrs(preview.raw)

    if title_side is not None:
        # Delimited mode: title verbatim; recurrence + tokens only after ` / `.
        preview.title = title_side
        _apply_attr_side(preview, attr_side, tz_name)
        if not preview.title:
            preview.warnings.append("Enter a title before ` / ` attributes.")
            preview.title = preview.raw
        _finalize_status(preview)
        return preview

    # Mixed mode — FR-CMD-005 strip recurrence, then gated token walk.
    working, recurrence = extract_recurrence(preview.raw, tz_name=tz_name)
    preview.recurrence = recurrence
    if recurrence:
        if recurrence.ambiguous and recurrence.warning:
            preview.warnings.append(recurrence.warning)
        elif recurrence.next_occurrence_at and preview.due_at is None:
            preview.due_at = recurrence.next_occurrence_at

    if not working.strip():
        preview.warnings.append("Enter a title or tokens to capture.")
        return preview

    _consume_tokens(preview, working.split(), tz_name, collect_title=True)

    if not preview.title:
        preview.title = working.strip() or preview.raw
        preview.warnings.append("No title tokens found — using full input as title.")

    _finalize_status(preview)
    return preview
