"""Build the public Sentinel item-changed event payload."""
from __future__ import annotations

from typing import Any


def build_item_changed_payload(item: Any) -> dict[str, Any]:
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
        "name": item.name,
        "domain": domain,
        "source": source,
        "item_type": item_type,
        "healthy": item.healthy,
        "state": item.state,
        "severity": item.severity,
        "reason": item.reason,
        "failure_count": item.failure_count,
        "since": item.since.isoformat(),
    }
