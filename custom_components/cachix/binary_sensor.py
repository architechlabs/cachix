"""Binary-sensor entities for the Cachix integration.

One binary sensor is created per *sensor*-type port reported by the
Global Caché device via ``getdevices``.
"""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CachixCoordinator
from .entity import CachixEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create binary sensors for detected sensor-type ports."""
    coordinator: CachixCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = []
    data = coordinator.data or {}

    for mod in data.get("modules", []):
        if mod.get("type", "").upper() != "SENSOR":
            continue
        module_id = mod["module"]
        for port_num in range(1, mod.get("port_count", 0) + 1):
            mp = f"{module_id}:{port_num}"
            entities.append(CachixPortBinarySensor(coordinator, entry, mp))

    async_add_entities(entities)


class CachixPortBinarySensor(CachixEntity, BinarySensorEntity):
    """Binary sensor tracking the state of a Global Caché sensor port."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: CachixCoordinator,
        entry: ConfigEntry,
        module_port: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._module_port = module_port
        self._attr_name = f"Sensor Port {module_port}"
        self._attr_unique_id = (
            f"{entry.entry_id}_sensor_{module_port.replace(':', '_')}"
        )
        self._attr_icon = "mdi:electric-switch"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data or {}
        state = data.get("port_states", {}).get(self._module_port)
        if state is not None:
            return state == 1
        return None
