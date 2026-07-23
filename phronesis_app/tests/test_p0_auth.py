# ==============================================================================
# File: phronesis_app/tests/test_p0_auth.py
# Description: Authentication, owner provisioning, and access-control tests
# Component: Tests
# Version: 1.1 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-22
# ==============================================================================
"""Security-focused tests for the single-owner authentication boundary."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from phronesis_app.models import ExecutionItem, SystemEnums


class OwnerAuthenticationTests(TestCase):
    """Exercise login, logout, setup closure, and safe redirects."""

    def setUp(self):
        self.User = get_user_model()
        self.owner = self.User.objects.create_superuser(
            "owner",
            "owner@example.com",
            "OwnerPass123!",
        )
        self.client = Client()

    def test_valid_owner_login_creates_session(self):
        response = self.client.post(
            reverse("login"),
            {"username": "owner", "password": "OwnerPass123!"},
        )

        self.assertRedirects(response, reverse("home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.owner.pk)

    def test_invalid_login_returns_friendly_error(self):
        response = self.client.post(
            reverse("login"),
            {"username": "owner", "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid credentials")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_non_owner_cannot_authenticate_through_owner_login(self):
        self.User.objects.create_user("guest", "guest@example.com", "GuestPass123!")

        response = self.client.post(
            reverse("login"),
            {"username": "guest", "password": "GuestPass123!"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "non-owner")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_external_next_url_is_rejected(self):
        """Regression: successful login must not become an open redirect."""
        response = self.client.post(
            f"{reverse('login')}?next=https://attacker.example/phish",
            {"username": "owner", "password": "OwnerPass123!"},
        )

        self.assertRedirects(response, reverse("home"))

    def test_setup_is_closed_after_owner_exists(self):
        response = self.client.get(reverse("setup-owner"))

        self.assertRedirects(response, reverse("login"))

    def test_setup_password_mismatch_does_not_create_owner(self):
        self.owner.delete()

        response = self.client.post(
            reverse("setup-owner"),
            {
                "username": "replacement",
                "password": "StrongPass123!",
                "password_confirm": "different",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwords do not match")
        self.assertFalse(self.User.objects.filter(username="replacement").exists())

    def test_logout_clears_owner_session(self):
        self.client.login(username="owner", password="OwnerPass123!")

        response = self.client.get(reverse("logout"))

        self.assertRedirects(response, reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_reset_entry_point_renders(self):
        response = self.client.get(reverse("password_reset"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reset")


@override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3, AXES_COOLOFF_TIME=1)
class LoginRateLimitTests(TestCase):
    """VN-E04 / S-53 — django-axes locks after repeated failed owner logins."""

    def setUp(self):
        User = get_user_model()
        User.objects.create_superuser("owner", "owner@example.com", "OwnerPass123!")
        self.client = Client()
        self.login_url = reverse("login")

    def test_repeated_failures_lock_username_and_ip(self):
        # Limit is 3: first two failures stay on the login form; third trips lockout.
        for _ in range(2):
            response = self.client.post(
                self.login_url,
                {"username": "owner", "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Invalid credentials")

        locked = self.client.post(
            self.login_url,
            {"username": "owner", "password": "wrong-password"},
        )
        # AxesMiddleware serves AXES_LOCKOUT_TEMPLATE with 429 once the limit trips.
        self.assertEqual(locked.status_code, 429)
        self.assertContains(locked, "Too many failed sign-ins", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

        # Correct password must still be refused while locked (view or middleware).
        still_locked = self.client.post(
            self.login_url,
            {"username": "owner", "password": "OwnerPass123!"},
        )
        self.assertIn(still_locked.status_code, (200, 429))
        self.assertContains(
            still_locked,
            "Too many failed sign-ins",
            status_code=still_locked.status_code,
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_successful_login_resets_failure_count(self):
        for _ in range(2):
            self.client.post(
                self.login_url,
                {"username": "owner", "password": "wrong-password"},
            )

        ok = self.client.post(
            self.login_url,
            {"username": "owner", "password": "OwnerPass123!"},
        )
        self.assertRedirects(ok, reverse("home"))

        # After reset, failures again show invalid credentials (not lockout yet).
        self.client.logout()
        for _ in range(2):
            response = self.client.post(
                self.login_url,
                {"username": "owner", "password": "wrong-password"},
            )
            self.assertContains(response, "Invalid credentials")


class OwnerAccessBoundaryTests(TestCase):
    """Verify middleware protects representative state-changing routes."""

    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser(
            "owner",
            "owner@example.com",
            "OwnerPass123!",
        )
        self.guest = User.objects.create_user(
            "guest",
            "guest@example.com",
            "GuestPass123!",
        )
        self.item = ExecutionItem.objects.create(
            title="Protected mutation",
            status=SystemEnums.ItemStatus.PLANNED,
        )

    def test_anonymous_mutation_redirects_to_login(self):
        response = self.client.post(reverse("focus-start", args=[self.item.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("login"))

    def test_authenticated_non_owner_mutation_is_forbidden(self):
        self.client.login(username="guest", password="GuestPass123!")

        response = self.client.post(reverse("focus-start", args=[self.item.pk]))

        self.assertEqual(response.status_code, 403)
