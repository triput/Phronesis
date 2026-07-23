# ==============================================================================
# File: phronesis_app/migrations/0021_encrypted_credentials_json.py
# Description: VN-E05 swap CalendarIntegration.credentials_json to EncryptedJSONField
# Component: Migrations
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""State-only field class change; column type remains JSON. Data encrypts on write."""

from django.db import migrations

import phronesis_app.encrypted_json


class Migration(migrations.Migration):

    dependencies = [
        ("phronesis_app", "0020_sync_id_cable_sync"),
    ]

    operations = [
        migrations.AlterField(
            model_name="calendarintegration",
            name="credentials_json",
            field=phronesis_app.encrypted_json.EncryptedJSONField(
                blank=True,
                null=True,
            ),
        ),
    ]
