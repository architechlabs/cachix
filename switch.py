"""Switch entities for the Cachix integration.

One switch is created per *relay*-type port reported by the Global Caché
device via ``getdevices``.  Toggling the switch sends ``setstate`` to
open / close the relay.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
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
    """Create switch entities for detected relay-type ports."""
    coordinator: CachixCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SwitchEntity] = []
    data = coordinator.data or {}

    for mod in data.get("modules", []):
        if mod.get("type", "").upper() != "RELAY":
            continue
        module_id = mod["module"]
        for port_num in range(1, mod.get("port_count", 0) + 1):
            mp = f"{module_id}:{port_num}"
            entities.append(CachixRelaySwitch(coordinator, entry, mp))

    async_add_entities(entities)


class CachixRelaySwitch(CachixEntity, SwitchEntity):
    """Switch controlling a Global Caché relay port."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:electric-switch"

    def __init__(
        self,
        coordinator: CachixCoordinator,
        entry: ConfigEntry,
        module_port: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._module_port = module_port
        self._attr_name = f"Relay {module_port}"
        self._attr_unique_id = (
            f"{entry.entry_id}_relay_{module_port.replace(':', '_')}"
        )

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data or {}
        state = data.get("port_states", {}).get(self._module_port)
        if state is not None:
            return state == 1
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Close the relay (state = 1)."""
        await self.coordinator.client.set_state(self._module_port, 1)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Open the relay (state = 0)."""
        await self.coordinator.client.set_state(self._module_port, 0)
        await self.coordinator.async_request_refresh()
