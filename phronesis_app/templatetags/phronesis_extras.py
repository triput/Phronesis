# ==============================================================================
# File: phronesis_app/templatetags/phronesis_extras.py
# Description: Template filters and tags for Phronesis V2 presentation helpers
# Component: Templates / Filters
# Version: 1.3 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-31
# ==============================================================================
"""Custom template filters — durations, due pulse, a11y labels, Heroicons (P5-06)."""

from __future__ import annotations

from django import template
from django.utils.html import format_html
from django.utils import timezone

from phronesis_app.services.due_pulse import classify_due_urgency, soon_window_minutes
from phronesis_app.services.heroicons import VIEWBOX, icon_path_data
from phronesis_app.services.time_format import format_duration_minutes, format_duration_seconds

register = template.Library()

_SIZE_CLASSES = {
    "xs": "w-3 h-3",
    "sm": "w-3.5 h-3.5",
    "md": "w-4 h-4",
    "lg": "w-5 h-5",
}


@register.filter
def duration_h(minutes):
    """Format minutes as human-readable duration for templates."""
    if minutes is None:
        return "—"
    try:
        return format_duration_minutes(int(minutes))
    except (TypeError, ValueError):
        return "—"


@register.filter
def duration_s(seconds):
    """Format seconds as human-readable duration (Analytics / focus totals)."""
    if seconds is None:
        return "—"
    try:
        return format_duration_seconds(int(seconds))
    except (TypeError, ValueError):
        return "—"


@register.simple_tag(takes_context=True)
def due_urgency(context, item):
    """Classify item due urgency once per render (caches window + now on context)."""
    bucket = context.setdefault("_phronesis_due_pulse", {})
    if "soon_minutes" not in bucket:
        bucket["soon_minutes"] = soon_window_minutes()
        bucket["now"] = timezone.now()
    return classify_due_urgency(
        item,
        now=bucket["now"],
        soon_minutes=bucket["soon_minutes"],
    )


@register.simple_tag(takes_context=True)
def due_urgency_label(context, item):
    """Human label for due urgency — screen readers (P5-06)."""
    code = due_urgency(context, item)
    if code == "overdue":
        return "Overdue"
    if code == "soon":
        return "Due soon"
    return ""


@register.simple_tag
def heroicon(name=None, icon=None, css_class="", size="sm", **kwargs):
    """Render a vendored Heroicons outline SVG for domain and UI accents.

    Usage::

        {% heroicon "terminal" %}
        {% heroicon name=domain.icon css_class="phronesis-domain-icon" %}
    """
    # Accept ``class=`` as an alias for ``css_class=`` in templates.
    css_class = kwargs.get("class", css_class) or ""
    raw_name = icon if icon is not None else name
    _, path_d = icon_path_data(raw_name)
    size_class = _SIZE_CLASSES.get(size, _SIZE_CLASSES["sm"])
    extra = f" {css_class}" if css_class else ""
    return format_html(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}" fill="none" '
        'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" '
        'class="phronesis-heroicon {size_class}{extra} shrink-0" aria-hidden="true" '
        'data-testid="domain-icon">'
        '<path d="{path_d}"/>'
        "</svg>",
        viewbox=VIEWBOX,
        size_class=size_class,
        extra=extra,
        path_d=path_d,
    )
