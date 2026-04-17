"""Base entity for the Cachix integration.

All platform entities inherit from :class:`CachixEntity` so that
``device_info`` and ``has_entity_name`` are defined in one place.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_FIRMWARE,
    CONF_HOST,
    CONF_MODEL,
    CONF_NAME,
    CONF_UUID,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import CachixCoordinator


class CachixEntity(CoordinatorEntity[CachixCoordinator]):
    """Base class shared by every Cachix entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CachixCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Link this entity to its parent device in the device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.data[CONF_UUID])},
            name=self._entry.data.get(CONF_NAME, "Global Caché"),
            manufacturer=MANUFACTURER,
            model=self._entry.data.get(CONF_MODEL, "Unknown"),
            sw_version=self._entry.data.get(CONF_FIRMWARE),
            configuration_url=f"http://{self._entry.data[CONF_HOST]}",
        )
