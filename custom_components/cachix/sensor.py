"""Sensor entities for the Cachix integration.

Provides diagnostic sensors for:
  • Connection status (Connected / Disconnected)
  • Firmware version
  • Last command sent
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_FIRMWARE, CONF_HOST, DOMAIN
from .coordinator import CachixCoordinator
from .entity import CachixEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up diagnostic sensor entities."""
    coordinator: CachixCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            CachixStatusSensor(coordinator, entry),
            CachixFirmwareSensor(coordinator, entry),
            CachixLastCommandSensor(coordinator, entry),
        ]
    )


# ─────────────────────────────────────────────────────────────────────────────


class CachixStatusSensor(CachixEntity, SensorEntity):
    """Reports the TCP connection status of the Global Caché device."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lan-connect"

    def __init__(
        self, coordinator: CachixCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Connection Status"
        self._attr_unique_id = f"{entry.entry_id}_status"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        return "Connected" if data.get("connected") else "Disconnected"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        attrs: dict[str, Any] = {
            "host": self._entry.data.get(CONF_HOST),
            "port": self._entry.data.get("port", 4998),
        }
        modules = data.get("modules") or []
        if modules:
            attrs["modules"] = [
                f"Module {m['module']}: {m['type']} ({m['port_count']} ports)"
                for m in modules
            ]
        return attrs


# ─────────────────────────────────────────────────────────────────────────────


class CachixFirmwareSensor(CachixEntity, SensorEntity):
    """Reports the firmware version of the Global Caché device."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"

    def __init__(
        self, coordinator: CachixCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Firmware Version"
        self._attr_unique_id = f"{entry.entry_id}_firmware"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data or {}
        return data.get("version") or self._entry.data.get(CONF_FIRMWARE)


# ─────────────────────────────────────────────────────────────────────────────


class CachixLastCommandSensor(CachixEntity, SensorEntity):
    """Shows the most recent command sent to the device."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:console"

    def __init__(
        self, coordinator: CachixCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Last Command"
        self._attr_unique_id = f"{entry.entry_id}_last_command"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        cmd = data.get("last_command", "")
        if not cmd:
            return "None"
        # Truncate very long IR strings for readability.
        return cmd[:120] + "…" if len(cmd) > 120 else cmd
