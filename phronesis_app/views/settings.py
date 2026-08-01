# ==============================================================================
# File: phronesis_app/views/settings.py
# Description: Settings surface — notifications, OAuth, availability, targets, backup, sync
# Component: Surfaces / Settings
# Version: 1.2 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-31
# ==============================================================================
"""Owner settings canvas — webhooks, calendar OAuth client, availability/targets CRUD, backup, sync."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from phronesis_app.models import TimeAvailabilityBlock, TimeTarget
from phronesis_app.services.appearance import reset_domain_colors, reset_tag_colors, save_appearance_settings
from phronesis_app.services.backup import (
    clear_owner_data,
    export_backup_bytes,
    normalize_scope,
    parse_backup_bytes,
    restore_backup,
)
from phronesis_app.services.sync_pack import (
    apply_sync_pack,
    ensure_device_id,
    export_sync_pack_bytes,
    force_accept_remote,
    parse_sync_pack_bytes,
)
from phronesis_app.services.lan_pair import (
    lan_pair_status,
    start_lan_pair,
    stop_lan_pair,
)
from phronesis_app.services.notify import send_test_webhook
from phronesis_app.services.settings_surface import (
    create_availability_block,
    create_time_target,
    delete_availability_block,
    delete_time_target,
    resolve_settings_tab,
    reset_telemetry_bands,
    save_general_settings,
    save_google_oauth_settings,
    save_calendar_push_settings,
    save_microsoft_oauth_settings,
    save_notification_settings,
    save_modules_settings,
    SaveResult,
    settings_context,
    update_availability_block,
    update_time_target,
)


def _request_settings_tab(request) -> str:
    """Active tab from POST (HTMX save), GET (?tab=), or default."""
    raw = request.POST.get("settings_tab") or request.GET.get("tab")
    return resolve_settings_tab(raw)


def _render_settings(request, **extra):
    """Full page on GET; HTMX fragment only on POST (avoids nested shell)."""
    if "settings_tab" not in extra:
        extra["settings_tab"] = _request_settings_tab(request)
    ctx = settings_context(settings_tab=extra.pop("settings_tab"))
    ctx.update(extra)
    template = "partials/settings_page.html" if request.htmx else "surfaces/settings.html"
    return render(request, template, ctx)


def _render_save_result(request, result: SaveResult, **extra):
    """Render settings with SaveResult message/ok flags."""
    return _render_settings(
        request,
        settings_message=result.message,
        settings_ok=result.ok,
        **extra,
    )


@login_required
@require_GET
def settings_view(request):
    """Settings canvas — general, modules, notifications, calendar OAuth, availability."""
    return _render_settings(request)


@login_required
@require_POST
def settings_modules_save_view(request):
    """Apply Simple/Full preset or custom module checkboxes (VN-A03)."""
    from phronesis_app.services.modules import OPTIONAL_MODULES

    preset = (request.POST.get("preset") or "").strip().lower()
    flags: dict[str, bool] = {}
    for mid in OPTIONAL_MODULES:
        # Checkbox name uses underscore form for HTML friendliness
        key = mid.replace(".", "_")
        flags[mid] = request.POST.get(key) in ("1", "true", "on", "yes")
    result = save_modules_settings(preset=preset, module_flags=flags if not preset else None)
    response = _render_save_result(request, result, settings_tab="modules")
    if result.ok:
        response["HX-Refresh"] = "true"
    return response


@login_required
@require_POST
def settings_appearance_save_view(request):
    """Save theme mode and domain/tag colors."""
    domain_colors: dict[int, str] = {}
    tag_colors: dict[int, str] = {}
    for key, value in request.POST.items():
        if key.startswith("domain_color_"):
            raw_id = key.removeprefix("domain_color_")
            if raw_id.isdigit():
                domain_colors[int(raw_id)] = value
        elif key.startswith("tag_color_"):
            raw_id = key.removeprefix("tag_color_")
            if raw_id.isdigit():
                tag_colors[int(raw_id)] = value
    result = save_appearance_settings(
        theme_mode=request.POST.get("theme_mode", ""),
        domain_colors=domain_colors,
        tag_colors=tag_colors,
    )
    response = _render_save_result(request, result)
    if result.ok:
        response["HX-Refresh"] = "true"
    return response


@login_required
@require_POST
def settings_appearance_reset_color_view(request):
    """Reset one or all domain/tag colors to seed catalog defaults."""
    kind = request.POST.get("kind", "")
    pk_raw = request.POST.get("pk", "").strip()
    pk = int(pk_raw) if pk_raw.isdigit() else None
    if kind == "domain":
        result = reset_domain_colors(domain_id=pk)
    elif kind == "domains":
        result = reset_domain_colors(domain_id=None)
    elif kind == "tag":
        result = reset_tag_colors(tag_id=pk)
    elif kind == "tags":
        result = reset_tag_colors(tag_id=None)
    else:
        result = SaveResult(ok=False, message="Unknown color reset target.")
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_general_save_view(request):
    """Save timezone, scheduler buffer, location, and weather provider."""
    try:
        buffer = int(request.POST.get("scheduler_buffer_minutes", "10"))
    except ValueError:
        buffer = 10
    try:
        horizon_days = int(request.POST.get("scheduler_horizon_days", "7"))
    except ValueError:
        horizon_days = 7

    def _optional_float(raw: str) -> float | None:
        raw = (raw or "").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _optional_int(raw: str) -> int | None:
        raw = (raw or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    result = save_general_settings(
        timezone=request.POST.get("timezone", ""),
        scheduler_buffer_minutes=buffer,
        scheduler_horizon_days=horizon_days,
        scheduler_replan_enabled=request.POST.get("scheduler_replan_enabled") == "on",
        location_name=request.POST.get("location_name", ""),
        latitude=_optional_float(request.POST.get("latitude", "")),
        longitude=_optional_float(request.POST.get("longitude", "")),
        weather_provider=request.POST.get("weather_provider", ""),
        openweather_api_key=request.POST.get("openweather_api_key", ""),
        auto_detect_location=request.POST.get("auto_detect_location") == "on",
        use_24h_time=request.POST.get("use_24h_time") == "on",
        use_imperial=request.POST.get("use_imperial") == "on",
        daily_completion_target=_optional_int(request.POST.get("daily_completion_target", "")),
        daily_focus_minutes_target=_optional_int(request.POST.get("daily_focus_minutes_target", "")),
        stability_streak_window_days=_optional_int(request.POST.get("stability_streak_window_days", "")),
        weather_band_cold_max=_optional_float(request.POST.get("weather_band_cold_max", "")),
        weather_band_moderate_max=_optional_float(request.POST.get("weather_band_moderate_max", "")),
        weather_band_warm_max=_optional_float(request.POST.get("weather_band_warm_max", "")),
        kp_band_blue_max=_optional_float(request.POST.get("kp_band_blue_max", "")),
        kp_band_green_max=_optional_float(request.POST.get("kp_band_green_max", "")),
        kp_band_yellow_max=_optional_float(request.POST.get("kp_band_yellow_max", "")),
    )
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_bands_reset_view(request):
    """Reset weather and/or Kp telemetry band thresholds to catalog defaults."""
    result = reset_telemetry_bands(kind=request.POST.get("kind", "all"))
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_geocode_view(request):
    """Forward-geocode location_name → lat/lon JSON (BL-TELE-005)."""
    from phronesis_app.services.telemetry.geocode import geocode_place

    raw = (request.POST.get("location_name") or "").strip()
    result = geocode_place(raw)
    payload: dict = {
        "ok": result.ok,
        "message": result.message,
    }
    if result.hit:
        payload["latitude"] = result.hit.latitude
        payload["longitude"] = result.hit.longitude
        payload["label"] = result.hit.label
    if result.candidates:
        payload["candidates"] = [
            {"label": c.label, "latitude": c.latitude, "longitude": c.longitude}
            for c in result.candidates
        ]
    status = 200 if result.ok else 400
    # Empty query is a client validation miss, not a server error
    if not raw:
        status = 400
    return JsonResponse(payload, status=status)


@login_required
@require_POST
def settings_notifications_save_view(request):
    """Save webhook notification policy."""
    try:
        lead = int(request.POST.get("reminder_lead_minutes", "15"))
    except ValueError:
        lead = 15
    result = save_notification_settings(
        notifications_enabled=request.POST.get("notifications_enabled") == "on",
        notification_channel=request.POST.get("notification_channel", "ntfy"),
        notification_webhook_url=request.POST.get("notification_webhook_url", ""),
        notification_webhook_token=request.POST.get("notification_webhook_token", ""),
        reminder_lead_minutes=lead,
    )
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_webhook_test_view(request):
    """POST a test payload to the configured webhook URL."""
    result = send_test_webhook()
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_google_oauth_save_view(request):
    """Save Google OAuth client credentials."""
    result = save_google_oauth_settings(
        client_id=request.POST.get("google_oauth_client_id", ""),
        client_secret=request.POST.get("google_oauth_client_secret", ""),
        redirect_uri=request.POST.get("google_oauth_redirect_uri", ""),
    )
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_calendar_push_save_view(request):
    """Toggle feature-flagged Google allocation push (P5-03)."""
    result = save_calendar_push_settings(
        enabled=request.POST.get("calendar_push_enabled") in ("1", "on", "true", "True"),
    )
    return _render_save_result(request, result)


@login_required
@require_GET
def settings_availability_edit_view(request, block_id: int):
    """Open inline edit form for an availability block."""
    if not TimeAvailabilityBlock.objects.filter(pk=block_id).exists():
        return _render_settings(
            request,
            settings_message="Availability block not found.",
            settings_ok=False,
            settings_tab="availability",
        )
    return _render_settings(request, editing_availability_id=block_id, settings_tab="availability")


@login_required
@require_POST
def settings_availability_update_view(request, block_id: int):
    """Save changes to an availability block."""
    days = set(request.POST.getlist("days"))
    domain_raw = request.POST.get("domain_id", "").strip()
    domain_id = int(domain_raw) if domain_raw.isdigit() else None
    tag_ids = [int(v) for v in request.POST.getlist("tag_ids") if str(v).isdigit()]
    result = update_availability_block(
        block_id,
        name=request.POST.get("name", ""),
        domain_id=domain_id,
        start_time=request.POST.get("start_time", "09:00"),
        end_time=request.POST.get("end_time", "17:00"),
        days=days,
        tag_ids=tag_ids,
    )
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_microsoft_oauth_save_view(request):
    """Save Microsoft Graph OAuth client credentials."""
    result = save_microsoft_oauth_settings(
        client_id=request.POST.get("microsoft_oauth_client_id", ""),
        client_secret=request.POST.get("microsoft_oauth_client_secret", ""),
        redirect_uri=request.POST.get("microsoft_oauth_redirect_uri", ""),
    )
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_availability_create_view(request):
    """Add a weekly availability block."""
    days = set(request.POST.getlist("days"))
    domain_raw = request.POST.get("domain_id", "").strip()
    domain_id = int(domain_raw) if domain_raw.isdigit() else None
    tag_ids = [int(v) for v in request.POST.getlist("tag_ids") if str(v).isdigit()]
    result = create_availability_block(
        name=request.POST.get("name", ""),
        domain_id=domain_id,
        start_time=request.POST.get("start_time", "09:00"),
        end_time=request.POST.get("end_time", "17:00"),
        days=days,
        tag_ids=tag_ids,
    )
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_availability_delete_view(request, block_id: int):
    """Delete an availability block."""
    result = delete_availability_block(block_id)
    return _render_save_result(request, result)


@login_required
@require_GET
def settings_target_edit_view(request, target_id: int):
    """Open inline edit form for a weekly time target."""
    if not TimeTarget.objects.filter(pk=target_id).exists():
        return _render_settings(
            request,
            settings_message="Time target not found.",
            settings_ok=False,
            settings_tab="targets",
        )
    return _render_settings(request, editing_target_id=target_id, settings_tab="targets")


@login_required
@require_POST
def settings_target_update_view(request, target_id: int):
    """Save changes to a weekly time target."""
    domain_raw = request.POST.get("domain_id", "").strip()
    tag_raw = request.POST.get("tag_id", "").strip()
    result = update_time_target(
        target_id,
        minutes_per_week=request.POST.get("minutes_per_week", "60"),
        domain_id=int(domain_raw) if domain_raw.isdigit() else None,
        tag_id=int(tag_raw) if tag_raw.isdigit() else None,
    )
    return _render_save_result(request, result, settings_tab="targets")


@login_required
@require_POST
def settings_target_create_view(request):
    """Add a weekly time target (VX-17)."""
    domain_raw = request.POST.get("domain_id", "").strip()
    tag_raw = request.POST.get("tag_id", "").strip()
    result = create_time_target(
        minutes_per_week=request.POST.get("minutes_per_week", "60"),
        domain_id=int(domain_raw) if domain_raw.isdigit() else None,
        tag_id=int(tag_raw) if tag_raw.isdigit() else None,
    )
    return _render_save_result(request, result, settings_tab="targets")


@login_required
@require_POST
def settings_target_delete_view(request, target_id: int):
    """Delete a weekly time target."""
    result = delete_time_target(target_id)
    return _render_save_result(request, result, settings_tab="targets")


@login_required
@require_GET
def settings_backup_export_view(request):
    """Download a secrets-safe full JSON backup (VN-A05 / S-41)."""
    payload = export_backup_bytes()
    stamp = timezone.localdate().isoformat().replace("-", "")
    response = HttpResponse(payload, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="phronesis-backup-{stamp}.json"'
    return response


@login_required
@require_POST
def settings_backup_restore_view(request):
    """Replace local owner data from an uploaded backup JSON."""
    confirm = request.POST.get("confirm") in ("1", "true", "on", "yes")
    if not confirm:
        return _render_save_result(
            request,
            SaveResult(ok=False, message="Confirm restore before continuing."),
            settings_tab="backup",
        )
    upload = request.FILES.get("backup_file")
    if not upload:
        return _render_save_result(
            request,
            SaveResult(ok=False, message="Choose a backup JSON file."),
            settings_tab="backup",
        )
    try:
        scope = normalize_scope(request.POST.get("scope"))
        payload = parse_backup_bytes(upload.read())
        result = restore_backup(payload, scope=scope)
    except ValueError as exc:
        return _render_save_result(
            request,
            SaveResult(ok=False, message=str(exc)),
            settings_tab="backup",
        )
    msg = result.message
    if result.warnings:
        msg = f"{msg} ({'; '.join(result.warnings)})"
    return _render_save_result(
        request,
        SaveResult(ok=result.ok, message=msg),
        settings_tab="backup",
    )


@login_required
@require_POST
def settings_backup_clear_view(request):
    """Wipe owner data for the selected scope without importing a file."""
    if (request.POST.get("confirm_text") or "").strip().upper() != "CLEAR":
        return _render_save_result(
            request,
            SaveResult(ok=False, message='Type CLEAR to confirm wiping local data.'),
            settings_tab="backup",
        )
    try:
        scope = normalize_scope(request.POST.get("scope"))
        result = clear_owner_data(scope=scope)
    except ValueError as exc:
        return _render_save_result(
            request,
            SaveResult(ok=False, message=str(exc)),
            settings_tab="backup",
        )
    return _render_save_result(
        request,
        SaveResult(ok=result.ok, message=result.message),
        settings_tab="backup",
    )


@login_required
@require_GET
def settings_sync_export_view(request):
    """Download a phronesis.sync_pack v0 JSON (VN-D02 cable sync)."""
    ensure_device_id()
    payload = export_sync_pack_bytes()
    stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    device_short = str(ensure_device_id())[:8]
    response = HttpResponse(payload, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="phronesis-sync-{device_short}-{stamp}.json"'
    )
    return response


@login_required
@require_POST
def settings_sync_import_view(request):
    """Apply an uploaded sync-pack with LWW; show session summary on Sync tab."""
    upload = request.FILES.get("sync_pack_file")
    if not upload:
        return _render_save_result(
            request,
            SaveResult(ok=False, message="Choose a sync-pack JSON file."),
            settings_tab="sync",
        )
    try:
        payload = parse_sync_pack_bytes(upload.read())
        result = apply_sync_pack(payload)
    except ValueError as exc:
        return _render_save_result(
            request,
            SaveResult(ok=False, message=str(exc)),
            settings_tab="sync",
        )
    msg = result.message
    if result.skipped_conflicts:
        msg = f"{msg} ({len(result.skipped_conflicts)} kept local — LWW)."
    return _render_save_result(
        request,
        SaveResult(ok=result.ok, message=msg),
        settings_tab="sync",
    )


@login_required
@require_POST
def settings_sync_accept_remote_view(request):
    """Force-accept selected conflict sync_ids from the cached last import (VN-D03)."""
    raw_ids = request.POST.getlist("sync_id")
    result = force_accept_remote(raw_ids)
    return _render_save_result(
        request,
        SaveResult(ok=result.ok, message=result.message),
        settings_tab="sync",
    )


@login_required
@require_POST
def settings_lan_start_view(request):
    """Start ephemeral LAN receive (VN-D04) — shows URL + token on Sync tab."""
    status = start_lan_pair()
    ok = status.active
    msg = status.message if ok else (status.last_error or status.message)
    if ok and status.warning:
        msg = f"{msg} {status.warning}"
    return _render_save_result(
        request,
        SaveResult(ok=ok, message=msg),
        settings_tab="sync",
    )


@login_required
@require_POST
def settings_lan_stop_view(request):
    """Stop LAN receive session."""
    status = stop_lan_pair()
    return _render_save_result(
        request,
        SaveResult(ok=True, message=status.message),
        settings_tab="sync",
    )
