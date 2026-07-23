# ==============================================================================
# File: phronesis_app/tests/test_p0_modules.py
# Description: VN-A03 Simple/Full module gating tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-21
# ==============================================================================
"""Module flags — presets, rail/Cmd gating, soft redirects, data preserved."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from phronesis_app.models import AppSettings, ExecutionItem, SystemEnums
from phronesis_app.services.cmd import preview_command
from phronesis_app.services.modules import (
    apply_preset,
    is_enabled,
    resolve_modules,
    set_modules,
)


class ModuleGatingTests(TestCase):
    """Exercise Simple/Full presets and optional surface gates."""

    def setUp(self):
        self.User = get_user_model()
        self.owner = self.User.objects.create_superuser(
            "owner",
            "owner@example.com",
            "OwnerPass123!",
        )
        self.client = Client()
        self.client.login(username="owner", password="OwnerPass123!")
        apply_preset("simple")

    def test_simple_preset_disables_optional_modules(self):
        resolved = resolve_modules()
        self.assertFalse(resolved["mod.academy"])
        self.assertFalse(resolved["mod.boards"])
        self.assertFalse(is_enabled("mod.calendar_grid"))

    def test_full_preset_enables_all_optional_modules(self):
        apply_preset("full")
        resolved = resolve_modules()
        self.assertTrue(all(resolved.values()))
        solo = AppSettings.get_solo()
        self.assertEqual(solo.ui_preset, "full")

    def test_single_toggle_marks_custom(self):
        apply_preset("simple")
        set_modules({"mod.academy": True})
        solo = AppSettings.get_solo()
        self.assertEqual(solo.ui_preset, "custom")
        self.assertTrue(is_enabled("mod.academy"))
        self.assertFalse(is_enabled("mod.boards"))

    def test_simple_hides_academy_from_home_rail(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "canvas-academy")
        self.assertContains(response, "Inbox")
        self.assertContains(response, "Matrix")

    def test_full_shows_academy_on_rail(self):
        apply_preset("full")
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("canvas-academy"))

    def test_go_academy_blocked_when_simple(self):
        preview = preview_command("go academy")
        self.assertEqual(preview.redirect_url, reverse("home"))
        self.assertTrue(preview.warnings)

    def test_go_academy_allowed_when_full(self):
        apply_preset("full")
        preview = preview_command("go academy")
        self.assertEqual(preview.redirect_url, reverse("canvas-academy"))

    def test_direct_academy_url_redirects_when_off(self):
        response = self.client.get(reverse("canvas-academy"))
        self.assertRedirects(response, reverse("home"))

    def test_direct_academy_url_ok_when_on(self):
        apply_preset("full")
        response = self.client.get(reverse("canvas-academy"))
        self.assertEqual(response.status_code, 200)

    def test_modules_settings_save_simple_preset(self):
        apply_preset("full")
        response = self.client.post(
            reverse("settings-modules-save"),
            {"preset": "simple", "settings_tab": "modules"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(is_enabled("mod.academy"))
        self.assertEqual(AppSettings.get_solo().ui_preset, "simple")

    def test_toggling_module_off_does_not_delete_items(self):
        apply_preset("full")
        item = ExecutionItem.objects.create(
            title="Keep me",
            status=SystemEnums.ItemStatus.BACKLOG,
        )
        apply_preset("simple")
        self.assertTrue(ExecutionItem.objects.filter(pk=item.pk).exists())
        apply_preset("full")
        self.assertTrue(ExecutionItem.objects.filter(pk=item.pk).exists())

    def test_home_hides_telemetry_and_stability_in_simple(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Telemetry")
        # Stability HUD partial title cue
        body = response.content.decode("utf-8")
        self.assertNotIn('id="stability-hud"', body)
