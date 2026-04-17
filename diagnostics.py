"""Diagnostics support for the Cachix integration.

Provides a downloadable diagnostics dump from the device page.
Sensitive fields (IP address) are automatically redacted.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_COMMANDS, CONF_HOST, DOMAIN
from .coordinator import CachixCoordinator

TO_REDACT = {CONF_HOST, "host"}


def _redact(data: dict, keys: set) -> dict:
    """Redact sensitive keys from a flat dictionary."""
    return {
        k: ("**REDACTED**" if k in keys else v) for k, v in data.items()
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics data for a Cachix config entry."""
    coordinator: CachixCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data or {}

    return {
        "config_entry_data": _redact(dict(entry.data), TO_REDACT),
        "options": {
            "commands_count": len(entry.options.get(CONF_COMMANDS, [])),
            "scan_interval": entry.options.get("scan_interval", 30),
        },
        "device": {
            "connected": data.get("connected", False),
            "firmware": data.get("version"),
            "modules": data.get("modules", []),
            "port_states": data.get("port_states", {}),
            "last_command": data.get("last_command", ""),
        },
    }
