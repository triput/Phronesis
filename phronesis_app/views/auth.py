# ==============================================================================
# File: phronesis_app/views/auth.py
# Description: Login / logout views for the single-owner cockpit
# Component: Core / Auth Views
# Version: 2.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-22
# ==============================================================================
"""Authentication entry points for Phronesis V3 (VN-E04 axes lockout)."""

from axes.handlers.proxy import AxesProxyHandler
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from phronesis_app.services.owner import create_owner_user, owner_exists


def _lockout_message() -> str:
    """Friendly lockout copy for the login template (S-53 / VN-E04)."""
    cooloff = getattr(settings, "AXES_COOLOFF_TIME", None)
    if cooloff:
        return (
            "Too many failed sign-ins. This username and IP are locked temporarily. "
            "Try again after the cool-off window, or unlock via `manage.py axes_reset`."
        )
    return (
        "Too many failed sign-ins. This username and IP are locked. "
        "Unlock with `manage.py axes_reset` on the host."
    )


def login_view(request):
    """Render login form and authenticate the owner superuser."""
    if not owner_exists():
        return redirect("setup-owner")

    if request.user.is_authenticated and request.user.is_superuser:
        return redirect("home")

    error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        credentials = {"username": username, "password": password}

        if AxesProxyHandler.is_locked(request, credentials):
            error = _lockout_message()
        else:
            try:
                user = authenticate(request, username=username, password=password)
            except PermissionDenied:
                # AxesStandaloneBackend raises when the attempt is already locked.
                error = _lockout_message()
                user = None

            if error is None:
                if user is not None and user.is_superuser:
                    login(request, user)
                    next_url = request.GET.get("next", "")
                    if not url_has_allowed_host_and_scheme(
                        next_url,
                        allowed_hosts={request.get_host()},
                        require_https=request.is_secure(),
                    ):
                        next_url = ""
                    return redirect(next_url or "home")

                # Failed auth: re-check lock so the Nth failure surfaces immediately.
                if AxesProxyHandler.is_locked(request, credentials):
                    error = _lockout_message()
                else:
                    error = "Invalid credentials or non-owner account."

    return render(request, "registration/login.html", {"error": error, "needs_setup": False})


def setup_owner_view(request):
    """First-run owner provisioning — only available before any superuser exists."""
    if owner_exists():
        if request.user.is_authenticated and request.user.is_superuser:
            return redirect("home")
        return redirect("login")

    error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        password_confirm = request.POST.get("password_confirm", "")
        email = request.POST.get("email", "").strip()

        if password != password_confirm:
            error = "Passwords do not match."
        else:
            try:
                user, _ = create_owner_user(username, password, email)
                login(request, user)
                return redirect("home")
            except ValidationError as exc:
                error = exc.messages[0] if exc.messages else str(exc)

    return render(request, "registration/setup_owner.html", {"error": error})


@login_required
def logout_view(request):
    """End the owner session and return to login."""
    logout(request)
    return redirect("login")
