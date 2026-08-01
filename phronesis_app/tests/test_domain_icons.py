# ==============================================================================
# File: phronesis_app/tests/test_domain_icons.py
# Description: Domain Heroicons resolve + settings chip markup smoke tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-31
# Last Update: 2026-07-31
# ==============================================================================
"""Light coverage for vendored domain icons (Heroicons outline subset).

Verifies:
- ``resolve_icon_name`` maps known names and falls back to ``folder``
- Settings appearance color chips emit ``data-testid="domain-icon"`` when a
  domain has an icon (e.g. seed Tech → ``terminal``)
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from phronesis_app.models import DomainCategory
from phronesis_app.services.heroicons import (
    DEFAULT_ICON,
    HEROICON_PATHS,
    icon_path_data,
    resolve_icon_name,
)


class HeroiconResolveTests(TestCase):
    """Unit tests for the offline Heroicons name resolver."""

    def test_resolve_known_heart(self):
        """Known outline names pass through unchanged."""
        self.assertEqual(resolve_icon_name("heart"), "heart")
        self.assertIn("heart", HEROICON_PATHS)

    def test_resolve_terminal_seed_icon(self):
        """Seed Tech domain uses ``terminal``; it must be in the path map."""
        self.assertEqual(resolve_icon_name("terminal"), "terminal")
        self.assertIn("terminal", HEROICON_PATHS)

    def test_resolve_unknown_falls_back_to_folder(self):
        """Unknown or empty names fall back to the default folder icon."""
        self.assertEqual(resolve_icon_name("not-a-real-icon"), DEFAULT_ICON)
        self.assertEqual(resolve_icon_name(""), DEFAULT_ICON)
        self.assertEqual(resolve_icon_name(None), DEFAULT_ICON)

    def test_icon_path_data_returns_svg_d(self):
        """Path helper returns canonical name plus a non-empty SVG ``d`` string."""
        name, path_d = icon_path_data("terminal")
        self.assertEqual(name, "terminal")
        self.assertTrue(path_d.startswith("M"))


class DomainIconMarkupTests(TestCase):
    """Settings appearance renders domain chip SVGs when icon is set."""

    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_appearance_chip_includes_domain_icon_markup(self):
        """Domain with icon ``terminal`` yields heroicon testid + class in HTML."""
        domain = DomainCategory.objects.get(slug="tech")
        domain.icon = "terminal"
        domain.color = "#8B9EF5"
        domain.save(update_fields=["icon", "color"])

        response = self.client.get(reverse("canvas-settings"), {"tab": "appearance"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="domain-icon"')
        self.assertContains(response, "phronesis-domain-icon")
        # Path data for terminal (fragment) proves real SVG, not an empty stub.
        _, path_d = icon_path_data("terminal")
        self.assertContains(response, path_d[:40])
