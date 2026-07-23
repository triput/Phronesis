# ==============================================================================
# File: phronesis_app/views/matrix.py
# Description: Backlog Matrix surface and inline mutation endpoints
# Component: Surfaces / Matrix
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-22
# ==============================================================================
"""Matrix tree grid — facets, lazy children, patch-field, bulk actions, VN-A09 create."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from phronesis_app.models import ExecutionItem, SystemEnums, WorkspaceContainer
from phronesis_app.services.matrix import (
    MatrixFacets,
    child_containers,
    container_items,
    facet_context,
    item_subtasks,
    root_containers,
)
from phronesis_app.services.modules import is_enabled
from phronesis_app.services.patch import bulk_update_items, patch_container_field, patch_item_field
from phronesis_app.services.structure import SIMPLE_CONTAINER_TYPES, create_container
from phronesis_app.views.htmx import set_cockpit_refresh


@login_required
def matrix_view(request):
    """Render Backlog Matrix with facet bar and root container rows."""
    from phronesis_app.services.saved_views import views_bar_context

    facets = MatrixFacets.from_request(request)
    ctx = facet_context(facets)
    ctx.update(
        {
            "surface": "matrix",
            "roots": root_containers(facets),
            "show_bulk_add": is_enabled("mod.bulk"),
            "container_type_choices": [
                (value, label)
                for value, label in SystemEnums.ContainerType.choices
                if value in SIMPLE_CONTAINER_TYPES
            ],
            "parent_choices": WorkspaceContainer.objects.filter(is_archived=False)
            .exclude(container_type=SystemEnums.ContainerType.INBOX)
            .order_by("title"),
        }
    )
    ctx.update(views_bar_context(surface="matrix", facets=facets))
    return render(request, "surfaces/matrix.html", ctx)


@login_required
def matrix_children_view(request, container_id: int):
    """Lazy-load child containers and items for a folded node."""
    facets = MatrixFacets.from_request(request)
    container = get_object_or_404(WorkspaceContainer, pk=container_id)
    depth = int(request.GET.get("depth", 0)) + 1
    return render(
        request,
        "partials/matrix_children.html",
        {
            "parent": container,
            "facets": facets,
            "depth": depth,
            "children": child_containers(container_id, facets),
            "items": container_items(container_id, facets),
        },
    )


@login_required
def matrix_item_subtasks_view(request, item_id: int):
    """Lazy-load subtasks under a parent item row."""
    facets = MatrixFacets.from_request(request)
    parent = get_object_or_404(ExecutionItem, pk=item_id, is_deleted=False)
    depth = int(request.GET.get("depth", 1)) + 1
    return render(
        request,
        "partials/matrix_subtasks.html",
        {
            "parent": parent,
            "facets": facets,
            "depth": depth,
            "subtasks": item_subtasks(item_id, facets),
        },
    )


@login_required
@require_POST
def item_patch_field_view(request, item_id: int):
    """Inline cell save for execution item fields (Matrix badge or drawer refresh)."""
    item = get_object_or_404(ExecutionItem, pk=item_id, is_deleted=False)
    field = request.POST.get("field", "")
    value = request.POST.get("value", "")
    return_to = request.POST.get("return", "")
    result = patch_item_field(item, field, value)

    if return_to == "drawer":
        from phronesis_app.views.drawer import render_item_drawer

        item = get_object_or_404(
            ExecutionItem.objects.prefetch_related(
                "tags", "container_links__container", "dependency_links_out__to_item"
            ),
            pk=item_id,
            is_deleted=False,
        )
        if not result.ok:
            return render_item_drawer(request, item, error=result.message, status=422)
        response = render_item_drawer(request, item)
        set_cockpit_refresh(response, **{"drawer-open": True})
        return response

    if not result.ok:
        response = render(
            request,
            "partials/matrix_item_badge.html",
            {"item": item, "field": field, "error": result.message},
            status=422,
        )
        return response
    item.refresh_from_db()
    response = render(
        request,
        "partials/matrix_item_badge.html",
        {"item": item, "field": field},
    )
    set_cockpit_refresh(response)
    return response


@login_required
@require_POST
def container_patch_field_view(request, container_id: int):
    """Inline cell save for workspace container fields (Matrix badge or drawer refresh)."""
    container = get_object_or_404(WorkspaceContainer, pk=container_id)
    field = request.POST.get("field", "")
    value = request.POST.get("value", "")
    return_to = request.POST.get("return", "")
    result = patch_container_field(container, field, value)

    if return_to == "drawer":
        from phronesis_app.views.drawer import render_container_drawer

        container = get_object_or_404(
            WorkspaceContainer.objects.select_related("domain", "parent", "certification"),
            pk=container_id,
        )
        if not result.ok:
            return render_container_drawer(request, container, error=result.message, status=422)
        return render_container_drawer(request, container)

    if not result.ok:
        return render(
            request,
            "partials/matrix_container_badge.html",
            {"container": container, "field": field, "error": result.message},
            status=422,
        )
    container.refresh_from_db()
    return render(
        request,
        "partials/matrix_container_badge.html",
        {"container": container, "field": field},
    )


@login_required
@require_POST
def matrix_container_create_view(request):
    """VN-A09 — create a container (and optional domain) from Matrix."""
    domain_raw = (request.POST.get("domain_id") or "").strip()
    parent_raw = (request.POST.get("parent_id") or "").strip()
    domain_id = int(domain_raw) if domain_raw.isdigit() else None
    parent_id = int(parent_raw) if parent_raw.isdigit() else None

    result = create_container(
        request.POST.get("title", ""),
        container_type=request.POST.get("container_type", ""),
        domain_id=domain_id,
        new_domain_name=request.POST.get("new_domain_name", ""),
        parent_id=parent_id,
    )

    if request.htmx:
        response = render(
            request,
            "partials/matrix_create_toast.html",
            {"result": result},
            status=200 if result.ok else 422,
        )
        if result.ok:
            set_cockpit_refresh(response, **{"matrix-reload": True})
        return response

    if result.ok:
        from django.contrib import messages
        from django.shortcuts import redirect

        messages.success(request, result.message)
        return redirect("canvas-matrix")
    return HttpResponse(result.message, status=422)


@login_required
@require_POST
def items_bulk_view(request):
    """Bulk status update or soft-delete for selected items."""
    raw_ids = request.POST.getlist("item_ids")
    item_ids = [int(i) for i in raw_ids if str(i).isdigit()]
    action = request.POST.get("action", "")
    value = request.POST.get("value", "")
    result = bulk_update_items(item_ids, action, value)

    if request.htmx:
        facets = MatrixFacets.from_request(request)
        response = render(
            request,
            "partials/matrix_bulk_toast.html",
            {"result": result, "facets": facets},
            status=200 if result.ok else 422,
        )
        if result.ok:
            set_cockpit_refresh(response, **{"matrix-reload": True})
        return response

    return HttpResponse(result.message, status=200 if result.ok else 422)
