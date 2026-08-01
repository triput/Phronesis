# ==============================================================================
# File: phronesis_app/services/settings_surface.py
# Description: Settings surface save helpers (SURF-SETTINGS)
# Component: Services / Settings
# Version: 1.2 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-31
# ==============================================================================
"""Load and persist owner settings from the Settings canvas."""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError

from phronesis_app.models import (
    AppSettings,
    DomainCategory,
    SystemEnums,
    Tag,
    TimeAvailabilityBlock,
    TimeTarget,
)
from phronesis_app.services.calendar_config import clean_secret
from phronesis_app.services.lan_pair import lan_pair_status
from phronesis_app.services.sync_pack import shape_conflict_report
from phronesis_app.services.time_targets import build_time_target_rows

# BL-UI-004 — Settings tab ids and labels (order = nav order)
SETTINGS_TABS: tuple[tuple[str, str], ...] = (
    ("general", "General"),
    ("modules", "Modules"),
    ("notifications", "Notifications"),
    ("calendars", "Calendars"),
    ("availability", "Availability"),
    ("targets", "Targets"),
    ("appearance", "Appearance"),
    ("templates", "Templates"),
    ("backup", "Backup"),
    ("sync", "Sync"),
)
SETTINGS_TAB_IDS = {tab_id for tab_id, _ in SETTINGS_TABS}
DEFAULT_SETTINGS_TAB = "general"

# Tabs gated by optional modules (VN-A03)
TAB_MODULE_GATES: dict[str, str] = {
    "availability": "mod.availability",
    "templates": "mod.templates",
}


@dataclass
class SaveResult:
    """Outcome of a settings form save."""

    ok: bool
    message: str = ""


def resolve_settings_tab(raw: str | None, *, settings_obj=None) -> str:
    """Normalize a tab id; unknown or disabled module tabs fall back to General."""
    from phronesis_app.services.modules import is_enabled

    tab = (raw or "").strip().lower()
    if tab not in SETTINGS_TAB_IDS:
        return DEFAULT_SETTINGS_TAB
    gate = TAB_MODULE_GATES.get(tab)
    if gate and not is_enabled(gate, settings_obj):
        return DEFAULT_SETTINGS_TAB
    return tab


def visible_settings_tabs(settings_obj=None) -> list[tuple[str, str]]:
    """Settings nav entries respecting optional module gates."""
    from phronesis_app.services.modules import is_enabled

    out: list[tuple[str, str]] = []
    for tab_id, label in SETTINGS_TABS:
        gate = TAB_MODULE_GATES.get(tab_id)
        if gate and not is_enabled(gate, settings_obj):
            continue
        out.append((tab_id, label))
    return out


def save_modules_settings(*, preset: str = "", module_flags: dict[str, bool] | None = None) -> SaveResult:
    """Apply Simple/Full preset or a custom module checkbox map."""
    from phronesis_app.services.modules import (
        OPTIONAL_MODULES,
        PRESET_FULL,
        PRESET_SIMPLE,
        apply_preset,
        set_modules,
    )

    preset_norm = (preset or "").strip().lower()
    if preset_norm in (PRESET_SIMPLE, PRESET_FULL):
        apply_preset(preset_norm)
        label = "Simple" if preset_norm == PRESET_SIMPLE else "Full cockpit"
        return SaveResult(ok=True, message=f"Preset applied: {label}.")

    flags = {mid: bool((module_flags or {}).get(mid, False)) for mid in OPTIONAL_MODULES}
    set_modules(flags)
    return SaveResult(ok=True, message="Module selection saved.")


def reset_telemetry_bands(*, kind: str = "all") -> SaveResult:
    """Restore weather and/or Kp color-band cutoffs to catalog defaults."""
    from phronesis_app.services.telemetry.bands import (
        apply_default_kp_bands,
        apply_default_telemetry_bands,
        apply_default_weather_bands,
    )

    kind = (kind or "all").strip().lower()
    if kind == "weather":
        apply_default_weather_bands()
        return SaveResult(ok=True, message="Weather band thresholds reset to defaults.")
    if kind == "kp":
        apply_default_kp_bands()
        return SaveResult(ok=True, message="Kp band thresholds reset to defaults.")
    if kind == "all":
        apply_default_telemetry_bands(weather=True, kp=True)
        return SaveResult(ok=True, message="Telemetry color bands reset to defaults.")
    return SaveResult(ok=False, message="Unknown band reset target.")


def settings_context(*, settings_tab: str | None = None) -> dict:
    """Template context for SURF-SETTINGS."""
    from phronesis_app.services.appearance import appearance_context
    from phronesis_app.services.time_locale import iana_timezone_choices

    from phronesis_app.services.telemetry.bands import (
        default_kp_bands,
        default_weather_bands_c,
        weather_bands_for_display,
    )

    solo = AppSettings.get_solo()
    tab = resolve_settings_tab(settings_tab, settings_obj=solo)
    from phronesis_app.services.templates_workspace import list_active_templates
    from phronesis_app.services.modules import (
        MODULE_LABELS,
        OPTIONAL_MODULES,
        resolve_modules,
    )

    cold_d, mod_d, warm_d = weather_bands_for_display(
        use_imperial=bool(solo.use_imperial),
        cold_c=solo.weather_band_cold_max,
        moderate_c=solo.weather_band_moderate_max,
        warm_c=solo.weather_band_warm_max,
    )
    def_cold_c, def_mod_c, def_warm_c = default_weather_bands_c()
    def_cold_d, def_mod_d, def_warm_d = weather_bands_for_display(
        use_imperial=bool(solo.use_imperial),
        cold_c=def_cold_c,
        moderate_c=def_mod_c,
        warm_c=def_warm_c,
    )
    def_kp_blue, def_kp_green, def_kp_yellow = default_kp_bands()
    modules_map = resolve_modules(solo)
    sync_summary = solo.last_sync_summary if isinstance(solo.last_sync_summary, dict) else {}
    conflicts = shape_conflict_report(sync_summary.get("conflicts") or [], enrich_titles=True)
    lan = lan_pair_status()
    ctx = {
        "surface": "settings",
        "settings_obj": solo,
        "availability_blocks": TimeAvailabilityBlock.objects.select_related("domain")
        .prefetch_related("tags")
        .order_by("name"),
        "time_target_rows": build_time_target_rows(settings=solo),
        "domains": DomainCategory.objects.filter(is_active=True).order_by("name"),
        "settings_tabs": visible_settings_tabs(solo),
        "settings_tab": tab,
        "ui_preset": getattr(solo, "ui_preset", "simple") or "simple",
        "device_id": str(solo.device_id) if solo.device_id else "",
        "last_sync_at": solo.last_sync_at,
        "last_sync_peer_device_id": (
            str(solo.last_sync_peer_device_id) if solo.last_sync_peer_device_id else ""
        ),
        "last_sync_summary": sync_summary,
        "sync_applied_rows": list((sync_summary.get("applied") or {}).items()),
        "sync_conflicts": conflicts,
        "sync_conflict_count": int(sync_summary.get("conflict_count") or len(conflicts)),
        "sync_has_cached_pack": bool(sync_summary.get("has_cached_pack")),
        "lan_pair": {
            "active": lan.active,
            "token": lan.token,
            "port": lan.port,
            "lan_ip": lan.lan_ip,
            "base_url": lan.base_url,
            "expires_at": lan.expires_at,
            "warning": lan.warning,
            "message": lan.message,
            "last_error": lan.last_error,
        },
        "module_choices": [
            {
                "id": mid,
                "name": mid.replace(".", "_"),
                "label": MODULE_LABELS.get(mid, mid),
                "enabled": modules_map.get(mid, False),
            }
            for mid in OPTIONAL_MODULES
        ],
        "workspace_templates": list_active_templates(),
        "timezone_choices": iana_timezone_choices(),
        # Display-unit weather band fields (canonical storage is °C).
        "weather_band_cold_display": cold_d,
        "weather_band_moderate_display": mod_d,
        "weather_band_warm_display": warm_d,
        "weather_band_default_display": (def_cold_d, def_mod_d, def_warm_d),
        "kp_band_defaults": (def_kp_blue, def_kp_green, def_kp_yellow),
    }
    ctx.update(appearance_context())
    ctx["weather_provider_choices"] = SystemEnums.WeatherProvider.choices
    return ctx


def save_general_settings(
    *,
    timezone: str,
    scheduler_buffer_minutes: int,
    scheduler_horizon_days: int | None = None,
    scheduler_replan_enabled: bool = False,
    location_name: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    weather_provider: str = "",
    openweather_api_key: str = "",
    auto_detect_location: bool = False,
    use_24h_time: bool = False,
    use_imperial: bool = True,
    daily_completion_target: int | None = None,
    daily_focus_minutes_target: int | None = None,
    stability_streak_window_days: int | None = None,
    weather_band_cold_max: float | None = None,
    weather_band_moderate_max: float | None = None,
    weather_band_warm_max: float | None = None,
    kp_band_blue_max: float | None = None,
    kp_band_green_max: float | None = None,
    kp_band_yellow_max: float | None = None,
) -> SaveResult:
    """Persist general scheduling, locale, location, and weather preferences."""
    from django.utils import timezone as dj_tz
    from zoneinfo import ZoneInfo

    from phronesis_app.services.telemetry.bands import validate_band_cutoffs, weather_bands_from_display
    from phronesis_app.services.time_locale import is_valid_timezone, normalize_timezone

    solo = AppSettings.get_solo()
    prev_lat, prev_lon = solo.latitude, solo.longitude
    tz_raw = (timezone or solo.timezone).strip()[:64]
    if not is_valid_timezone(tz_raw):
        return SaveResult(
            ok=False,
            message=f"Unknown timezone “{tz_raw}”. Pick an IANA zone (e.g. America/Phoenix).",
        )
    solo.timezone = normalize_timezone(tz_raw, fallback=solo.timezone)
    solo.scheduler_buffer_minutes = max(0, min(scheduler_buffer_minutes, 120))
    if scheduler_horizon_days is not None:
        solo.scheduler_horizon_days = max(1, min(int(scheduler_horizon_days), 14))
    solo.scheduler_replan_enabled = bool(scheduler_replan_enabled)
    solo.location_name = (location_name or solo.location_name).strip()[:255]
    if latitude is not None:
        solo.latitude = max(-90.0, min(90.0, latitude))
    if longitude is not None:
        solo.longitude = max(-180.0, min(180.0, longitude))
    valid_providers = {c.value for c in SystemEnums.WeatherProvider}
    provider = (weather_provider or SystemEnums.WeatherProvider.AUTO).strip()
    solo.weather_provider = provider if provider in valid_providers else SystemEnums.WeatherProvider.AUTO
    secret = clean_secret(openweather_api_key or "")
    if secret:
        solo.openweather_api_key = secret
    solo.auto_detect_location = bool(auto_detect_location)
    solo.use_24h_time = bool(use_24h_time)
    solo.use_imperial = bool(use_imperial)
    if daily_completion_target is not None:
        solo.daily_completion_target = max(1, min(int(daily_completion_target), 100))
    if daily_focus_minutes_target is not None:
        solo.daily_focus_minutes_target = max(1, min(int(daily_focus_minutes_target), 24 * 60))
    if stability_streak_window_days is not None:
        solo.stability_streak_window_days = max(1, min(int(stability_streak_window_days), 90))

    # Form posts cutoffs in the owner's display unit; persist canonical °C.
    if None not in (weather_band_cold_max, weather_band_moderate_max, weather_band_warm_max):
        try:
            weather_cut = weather_bands_from_display(
                use_imperial=solo.use_imperial,
                cold=weather_band_cold_max,
                moderate=weather_band_moderate_max,
                warm=weather_band_warm_max,
            )
        except (TypeError, ValueError):
            weather_cut = None
        if weather_cut is None:
            return SaveResult(ok=False, message="Weather band thresholds must be numbers.")
        solo.weather_band_cold_max, solo.weather_band_moderate_max, solo.weather_band_warm_max = weather_cut

    if None not in (kp_band_blue_max, kp_band_green_max, kp_band_yellow_max):
        kp_cut = validate_band_cutoffs(kp_band_blue_max, kp_band_green_max, kp_band_yellow_max)
        if kp_cut is None:
            return SaveResult(ok=False, message="Kp band thresholds must be numbers.")
        solo.kp_band_blue_max, solo.kp_band_green_max, solo.kp_band_yellow_max = kp_cut

    solo.save(
        update_fields=[
            "timezone",
            "scheduler_buffer_minutes",
            "scheduler_horizon_days",
            "scheduler_replan_enabled",
            "location_name",
            "latitude",
            "longitude",
            "weather_provider",
            "openweather_api_key",
            "auto_detect_location",
            "use_24h_time",
            "use_imperial",
            "daily_completion_target",
            "daily_focus_minutes_target",
            "stability_streak_window_days",
            "weather_band_cold_max",
            "weather_band_moderate_max",
            "weather_band_warm_max",
            "kp_band_blue_max",
            "kp_band_green_max",
            "kp_band_yellow_max",
            "updated_at",
        ]
    )
    # Drop stale weather snapshots when coordinates change (BL-TELE-004).
    if (solo.latitude, solo.longitude) != (prev_lat, prev_lon):
        from phronesis_app.services.telemetry.weather import invalidate_weather_cache_for_coords

        invalidate_weather_cache_for_coords(prev_lat, prev_lon)
        invalidate_weather_cache_for_coords(solo.latitude, solo.longitude)
    # Activate immediately so the same request / next HTMX fragment uses the new TZ.
    try:
        dj_tz.activate(ZoneInfo(solo.timezone))
    except Exception:
        pass
    return SaveResult(ok=True, message="General settings saved.")


def save_notification_settings(
    *,
    notifications_enabled: bool,
    notification_channel: str,
    notification_webhook_url: str,
    notification_webhook_token: str,
    reminder_lead_minutes: int,
) -> SaveResult:
    """Persist outbound webhook notification policy."""
    solo = AppSettings.get_solo()
    solo.notifications_enabled = notifications_enabled
    valid_channels = {c.value for c in SystemEnums.NotificationChannel}
    channel = (notification_channel or SystemEnums.NotificationChannel.NTFY).strip()
    solo.notification_channel = channel if channel in valid_channels else SystemEnums.NotificationChannel.NTFY
    solo.notification_webhook_url = (notification_webhook_url or "").strip()
    solo.notification_webhook_token = clean_secret(notification_webhook_token or "")
    solo.reminder_lead_minutes = max(1, min(reminder_lead_minutes, 10_080))
    solo.save(
        update_fields=[
            "notifications_enabled",
            "notification_channel",
            "notification_webhook_url",
            "notification_webhook_token",
            "reminder_lead_minutes",
            "updated_at",
        ]
    )
    return SaveResult(ok=True, message="Notification settings saved.")


def save_google_oauth_settings(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> SaveResult:
    """Persist Google OAuth client credentials (DB, not git)."""
    solo = AppSettings.get_solo()
    solo.google_oauth_client_id = clean_secret(client_id or "")
    secret = clean_secret(client_secret or "")
    if secret:
        solo.google_oauth_client_secret = secret
    solo.google_oauth_redirect_uri = (redirect_uri or "").strip()[:512]
    solo.save(
        update_fields=[
            "google_oauth_client_id",
            "google_oauth_client_secret",
            "google_oauth_redirect_uri",
            "updated_at",
        ]
    )
    return SaveResult(ok=True, message="Google Calendar OAuth client saved.")


def save_calendar_push_settings(*, enabled: bool) -> SaveResult:
    """Toggle P5-03 Google allocation push. Reconnect required for write scope."""
    solo = AppSettings.get_solo()
    solo.calendar_push_enabled = bool(enabled)
    solo.save(update_fields=["calendar_push_enabled", "updated_at"])
    if solo.calendar_push_enabled:
        return SaveResult(
            ok=True,
            message=(
                "Calendar push enabled — reconnect Google from Planner to grant write access."
            ),
        )
    return SaveResult(ok=True, message="Calendar push disabled.")


def save_microsoft_oauth_settings(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> SaveResult:
    """Persist Microsoft Graph OAuth client credentials (DB, not git)."""
    solo = AppSettings.get_solo()
    solo.microsoft_oauth_client_id = clean_secret(client_id or "")
    secret = clean_secret(client_secret or "")
    if secret:
        solo.microsoft_oauth_client_secret = secret
    solo.microsoft_oauth_redirect_uri = (redirect_uri or "").strip()[:512]
    solo.save(
        update_fields=[
            "microsoft_oauth_client_id",
            "microsoft_oauth_client_secret",
            "microsoft_oauth_redirect_uri",
            "updated_at",
        ]
    )
    return SaveResult(ok=True, message="Microsoft Calendar OAuth client saved.")


def _apply_availability_fields(
    block: TimeAvailabilityBlock,
    *,
    name: str,
    domain_id: int | None,
    start_time: str,
    end_time: str,
    days: set[str],
    tag_ids: list[int] | None = None,
) -> SaveResult:
    """Validate and apply shared availability block fields (including VX-11 tags)."""
    name = (name or "").strip()
    if not name:
        return SaveResult(ok=False, message="Availability block name is required.")
    domain = None
    if domain_id:
        domain = DomainCategory.objects.filter(pk=domain_id).first()
    block.name = name[:100]
    block.domain = domain
    block.start_time = start_time or "09:00"
    block.end_time = end_time or "17:00"
    block.day_monday = "mon" in days
    block.day_tuesday = "tue" in days
    block.day_wednesday = "wed" in days
    block.day_thursday = "thu" in days
    block.day_friday = "fri" in days
    block.day_saturday = "sat" in days
    block.day_sunday = "sun" in days
    block.save()
    # M2M requires a saved PK; empty selection clears the gate (open window).
    if tag_ids is not None:
        valid = list(Tag.objects.filter(pk__in=tag_ids).values_list("pk", flat=True))
        block.tags.set(valid)
    return SaveResult(ok=True, message="")


def create_availability_block(
    *,
    name: str,
    domain_id: int | None,
    start_time: str,
    end_time: str,
    days: set[str],
    tag_ids: list[int] | None = None,
) -> SaveResult:
    """Create a weekly availability window for the scheduler."""
    block = TimeAvailabilityBlock()
    result = _apply_availability_fields(
        block,
        name=name,
        domain_id=domain_id,
        start_time=start_time,
        end_time=end_time,
        days=days,
        tag_ids=tag_ids if tag_ids is not None else [],
    )
    if not result.ok:
        return result
    return SaveResult(ok=True, message=f"Added availability block “{block.name}”.")


def update_availability_block(
    block_id: int,
    *,
    name: str,
    domain_id: int | None,
    start_time: str,
    end_time: str,
    days: set[str],
    tag_ids: list[int] | None = None,
) -> SaveResult:
    """Update an existing weekly availability window."""
    block = TimeAvailabilityBlock.objects.filter(pk=block_id).first()
    if not block:
        return SaveResult(ok=False, message="Availability block not found.")
    result = _apply_availability_fields(
        block,
        name=name,
        domain_id=domain_id,
        start_time=start_time,
        end_time=end_time,
        days=days,
        tag_ids=tag_ids if tag_ids is not None else [],
    )
    if not result.ok:
        return result
    return SaveResult(ok=True, message=f"Updated availability block “{block.name}”.")


def delete_availability_block(block_id: int) -> SaveResult:
    """Remove an availability block."""
    deleted, _ = TimeAvailabilityBlock.objects.filter(pk=block_id).delete()
    if not deleted:
        return SaveResult(ok=False, message="Availability block not found.")
    return SaveResult(ok=True, message="Availability block removed.")


def _resolve_target_refs(
    *,
    domain_id: int | None,
    tag_id: int | None,
) -> tuple[DomainCategory | None, Tag | None, SaveResult | None]:
    """Validate domain/tag FKs; require at least one."""
    if not domain_id and not tag_id:
        return None, None, SaveResult(ok=False, message="Choose a domain, a tag, or both.")
    domain = None
    tag = None
    if domain_id:
        domain = DomainCategory.objects.filter(pk=domain_id, is_active=True).first()
        if domain is None:
            return None, None, SaveResult(ok=False, message="Domain not found.")
    if tag_id:
        tag = Tag.objects.filter(pk=tag_id).first()
        if tag is None:
            return None, None, SaveResult(ok=False, message="Tag not found.")
    return domain, tag, None


def create_time_target(
    *,
    minutes_per_week: int,
    domain_id: int | None = None,
    tag_id: int | None = None,
) -> SaveResult:
    """Create an informational weekly minutes goal (VX-17)."""
    try:
        minutes = int(minutes_per_week)
    except (TypeError, ValueError):
        return SaveResult(ok=False, message="Minutes per week must be a positive number.")
    if minutes < 1:
        return SaveResult(ok=False, message="Minutes per week must be at least 1.")
    domain, tag, err = _resolve_target_refs(domain_id=domain_id, tag_id=tag_id)
    if err:
        return err
    try:
        target = TimeTarget(domain=domain, tag=tag, minutes_per_week=minutes)
        target.save()
    except (ValidationError, IntegrityError) as exc:
        msg = "A target for that domain/tag already exists."
        if isinstance(exc, ValidationError):
            msg = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        return SaveResult(ok=False, message=msg)
    return SaveResult(ok=True, message=f"Added target “{target.label}”.")


def update_time_target(
    target_id: int,
    *,
    minutes_per_week: int,
    domain_id: int | None = None,
    tag_id: int | None = None,
) -> SaveResult:
    """Update an existing weekly time target."""
    target = TimeTarget.objects.filter(pk=target_id).first()
    if not target:
        return SaveResult(ok=False, message="Time target not found.")
    try:
        minutes = int(minutes_per_week)
    except (TypeError, ValueError):
        return SaveResult(ok=False, message="Minutes per week must be a positive number.")
    if minutes < 1:
        return SaveResult(ok=False, message="Minutes per week must be at least 1.")
    domain, tag, err = _resolve_target_refs(domain_id=domain_id, tag_id=tag_id)
    if err:
        return err
    target.domain = domain
    target.tag = tag
    target.minutes_per_week = minutes
    try:
        target.save()
    except (ValidationError, IntegrityError) as exc:
        msg = "A target for that domain/tag already exists."
        if isinstance(exc, ValidationError):
            msg = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        return SaveResult(ok=False, message=msg)
    return SaveResult(ok=True, message=f"Updated target “{target.label}”.")


def delete_time_target(target_id: int) -> SaveResult:
    """Remove a weekly time target."""
    deleted, _ = TimeTarget.objects.filter(pk=target_id).delete()
    if not deleted:
        return SaveResult(ok=False, message="Time target not found.")
    return SaveResult(ok=True, message="Time target removed.")
