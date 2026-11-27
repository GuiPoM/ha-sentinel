"""Build the public Sentinel item-changed event payload."""
from __future__ import annotations

from typing import Any


def public_item_name(item: Any, *, expose_details: bool) -> str:
    """Return a safe item name unless detailed user data was enabled."""
    if expose_details:
        return item.name
    if item.provider == "devices":
        return f"Device {item.id}"
    if item.provider == "apps":
        return str(item.extra.get("slug") or item.id)
    return str(item.extra.get("domain") or item.provider)


def build_item_changed_payload(
    item: Any, *, expose_details: bool = False
) -> dict[str, Any]:
    """Return the stable user-facing payload for a health item."""
    source = item.extra.get("source", "")
    domain = item.extra.get("domain", "") or source.lower()
    if item.provider == "devices":
        item_type = "device"
    elif item.provider == "apps":
        item_type = "addon"
    else:
        item_type = "integration"
    return {
        "item_id": item.id,
        "provider": item.provider,
        "name": public_item_name(item, expose_details=expose_details),
        "domain": domain,
        "source": source,
        "item_type": item_type,
        "healthy": item.healthy,
        "state": item.state,
        "severity": item.severity,
        "reason": item.reason if expose_details else None,
        "failure_count": item.failure_count,
        "since": item.since.isoformat(),
    }
