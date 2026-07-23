# ==============================================================================
# File: phronesis_app/services/structure.py
# Description: VN-A09 Simple-mode container / domain create helpers
# Component: Services / Structure
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Create workspace containers and domains without Bulk/Templates (Simple spine)."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils.text import slugify

from phronesis_app.models import DomainCategory, SystemEnums, WorkspaceContainer
from phronesis_app.services.appearance_defaults import DOMAIN_COLOR_FALLBACK

# Civilian create — skip system INBOX and heavy Academy types in the default picker.
SIMPLE_CONTAINER_TYPES: tuple[str, ...] = (
    SystemEnums.ContainerType.LIST,
    SystemEnums.ContainerType.PROJECT,
    SystemEnums.ContainerType.EPIC,
    SystemEnums.ContainerType.SPRINT,
)


@dataclass
class StructureResult:
    """Outcome of a structure create call."""

    ok: bool
    message: str = ""
    container: WorkspaceContainer | None = None
    domain: DomainCategory | None = None


def _unique_domain_slug(name: str) -> str:
    base = slugify(name) or "domain"
    candidate = base
    n = 2
    while DomainCategory.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _unique_container_slug(title: str) -> str:
    base = slugify(title) or "container"
    candidate = base
    n = 2
    while WorkspaceContainer.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def create_domain(name: str, *, color: str = "") -> StructureResult:
    """Create an active DomainCategory from a display name."""
    name = (name or "").strip()
    if not name:
        return StructureResult(ok=False, message="Domain name is required.")
    if DomainCategory.objects.filter(name__iexact=name).exists():
        return StructureResult(ok=False, message=f"Domain “{name}” already exists.")

    hex_color = (color or "").strip() or DOMAIN_COLOR_FALLBACK
    if not hex_color.startswith("#") or len(hex_color) not in (4, 7):
        hex_color = DOMAIN_COLOR_FALLBACK

    domain = DomainCategory.objects.create(
        name=name,
        slug=_unique_domain_slug(name),
        color=hex_color,
        is_active=True,
    )
    return StructureResult(ok=True, message=f"Created domain “{domain.name}”.", domain=domain)


@transaction.atomic
def create_container(
    title: str,
    *,
    container_type: str = "",
    domain_id: int | None = None,
    new_domain_name: str = "",
    parent_id: int | None = None,
) -> StructureResult:
    """Create a WorkspaceContainer for Matrix / Simple structure UX.

    Optional ``new_domain_name`` creates (or reuses) a domain when ``domain_id``
    is not set — so Simple mode can grow domains without Admin.
    """
    title = (title or "").strip()
    if not title:
        return StructureResult(ok=False, message="Container title is required.")

    ctype = (container_type or SystemEnums.ContainerType.LIST).strip().upper()
    valid_types = {c.value for c in SystemEnums.ContainerType}
    if ctype not in valid_types:
        return StructureResult(ok=False, message=f"Unknown container type: {container_type!r}.")
    if ctype == SystemEnums.ContainerType.INBOX:
        return StructureResult(ok=False, message="Cannot create another Inbox container.")

    domain: DomainCategory | None = None
    if domain_id:
        domain = DomainCategory.objects.filter(pk=domain_id, is_active=True).first()
        if domain is None:
            return StructureResult(ok=False, message="Domain not found.")
    elif (new_domain_name or "").strip():
        existing = DomainCategory.objects.filter(name__iexact=new_domain_name.strip()).first()
        if existing:
            domain = existing
        else:
            created = create_domain(new_domain_name)
            if not created.ok:
                return created
            domain = created.domain

    parent: WorkspaceContainer | None = None
    if parent_id:
        parent = WorkspaceContainer.objects.filter(pk=parent_id, is_archived=False).first()
        if parent is None:
            return StructureResult(ok=False, message="Parent container not found.")

    container = WorkspaceContainer.objects.create(
        title=title,
        slug=_unique_container_slug(title),
        container_type=ctype,
        para_state=SystemEnums.PARACategory.PROJECT,
        domain=domain,
        parent=parent,
    )
    bits = [f"Created #{container.slug}"]
    if domain:
        bits.append(f"in {domain.name}")
    return StructureResult(
        ok=True,
        message=" · ".join(bits) + ".",
        container=container,
        domain=domain,
    )
