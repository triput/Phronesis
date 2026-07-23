# ==============================================================================
# File: phronesis_app/migrations/0020_sync_id_cable_sync.py
# Description: VN-D02 sync_id / updated_at / device_id for cable sync packs
# Component: Migrations
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================

import uuid

import phronesis_app.models
from django.db import migrations, models


def _backfill_uuids(apps, schema_editor):
    """Assign real UUIDs to existing rows (nullable add → fill → unique)."""
    model_names = (
        "AppSettings",
        "DomainCategory",
        "Tag",
        "WorkspaceContainer",
        "ExecutionItem",
        "ItemContainerLink",
        "ItemDependencyLink",
        "FocusSession",
    )
    for name in model_names:
        Model = apps.get_model("phronesis_app", name)
        for row in Model.objects.all():
            changed = []
            if getattr(row, "sync_id", None) is None:
                row.sync_id = uuid.uuid4()
                changed.append("sync_id")
            if name == "AppSettings" and getattr(row, "device_id", None) is None:
                row.device_id = uuid.uuid4()
                changed.append("device_id")
            if changed:
                row.save(update_fields=changed)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("phronesis_app", "0019_appsettings_modules"),
    ]

    operations = [
        # --- nullable UUID columns first ---
        migrations.AddField(
            model_name="appsettings",
            name="device_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="sync_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="last_sync_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="last_sync_peer_device_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="last_sync_summary",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="domaincategory",
            name="sync_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="domaincategory",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name="tag",
            name="sync_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="tag",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name="workspacecontainer",
            name="sync_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="executionitem",
            name="sync_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="itemcontainerlink",
            name="sync_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="itemcontainerlink",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name="itemdependencylink",
            name="sync_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="itemdependencylink",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name="focussession",
            name="sync_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="focussession",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.RunPython(_backfill_uuids, noop_reverse),
        # --- tighten uniqueness + match model defaults (wipe-friendly final state) ---
        migrations.AlterField(
            model_name="appsettings",
            name="device_id",
            field=models.UUIDField(
                default=phronesis_app.models.new_sync_id,
                editable=False,
                help_text="Stable install UUID for sync-pack source_device_id.",
            ),
        ),
        migrations.AlterField(
            model_name="appsettings",
            name="sync_id",
            field=models.UUIDField(
                default=phronesis_app.models.new_sync_id,
                editable=False,
                help_text="Settings singleton sync identity for pack LWW.",
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="appsettings",
            name="last_sync_summary",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Last import/export counts + conflicts (VN-D02 session report).",
            ),
        ),
        migrations.AlterField(
            model_name="domaincategory",
            name="sync_id",
            field=models.UUIDField(
                default=phronesis_app.models.new_sync_id,
                editable=False,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="domaincategory",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="tag",
            name="sync_id",
            field=models.UUIDField(
                default=phronesis_app.models.new_sync_id,
                editable=False,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="tag",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="workspacecontainer",
            name="sync_id",
            field=models.UUIDField(
                default=phronesis_app.models.new_sync_id,
                editable=False,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="executionitem",
            name="sync_id",
            field=models.UUIDField(
                default=phronesis_app.models.new_sync_id,
                editable=False,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="itemcontainerlink",
            name="sync_id",
            field=models.UUIDField(
                default=phronesis_app.models.new_sync_id,
                editable=False,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="itemcontainerlink",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="itemdependencylink",
            name="sync_id",
            field=models.UUIDField(
                default=phronesis_app.models.new_sync_id,
                editable=False,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="itemdependencylink",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="focussession",
            name="sync_id",
            field=models.UUIDField(
                default=phronesis_app.models.new_sync_id,
                editable=False,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="focussession",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
    ]
