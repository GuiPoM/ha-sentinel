"""Abstract base class for HA Sentinel providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@dataclass
class HealthItem:
    """Represents a monitored item (integration, app, etc.)."""

    id: str
    """Unique identifier (config_entry_id, addon_slug, ...)."""

    name: str
    """Human-readable label."""

    provider: str
    """Provider identifier (PROVIDER_INTEGRATIONS, PROVIDER_APPS, ...)."""

    healthy: bool
    """True if the item is operating normally."""

    state: str
    """Raw state string from the underlying system."""

    severity: str = "ok"
    """Severity: 'ok', 'warning', or 'error'."""

    reason: str | None = None
    """Error reason/message if unhealthy."""

    since: datetime = field(default_factory=datetime.now)
    """Timestamp of last state change."""

    failure_count: int = 0
    """Number of times this item has entered an unhealthy state."""

    can_reload: bool = False
    """Whether a reload action is supported for this item."""

    extra: dict = field(default_factory=dict)
    """Provider-specific extra attributes."""


class HealthProvider(ABC):
    """Abstract base class for Sentinel health providers."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the provider."""
        self.hass = hass
        self._items: dict[str, HealthItem] = {}

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Return the provider identifier (e.g. 'integrations')."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the human-readable provider name."""

    @property
    def available(self) -> bool:
        """Return True if this provider is available on this HA instance."""
        return True

    @abstractmethod
    async def async_setup(self, on_change_callback) -> None:
        """Set up the provider and subscribe to state changes.

        on_change_callback(item: HealthItem) must be called whenever
        an item's state changes.
        """

    @abstractmethod
    async def async_unload(self) -> None:
        """Unload the provider and clean up subscriptions."""

    @abstractmethod
    async def async_reload_item(self, item_id: str) -> bool:
        """Reload/restart the given item. Returns True on success."""

    def get_items(self) -> dict[str, HealthItem]:
        """Return all currently known items."""
        return dict(self._items)

    def get_item(self, item_id: str) -> HealthItem | None:
        """Return a specific item by ID."""
        return self._items.get(item_id)
