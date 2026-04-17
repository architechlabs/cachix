"""The Cachix integration – modern Global Caché controller for Home Assistant.

Supports iTach IP2IR / WF2IR, IP2SL / WF2SL, IP2CC / WF2CC, GC-100 series,
iTach Flex, Global Connect, and any device speaking the Unified TCP API on
port 4998.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .client import ConnectionFailed
from .const import (
    CMD_KEY_COMMAND,
    CMD_KEY_NAME,
    CONF_COMMANDS,
    CONF_HOST,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import CachixCoordinator

_LOGGER = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
#  Setup / Teardown
# ═════════════════════════════════════════════════════════════════════════════


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Cachix integration (YAML is intentionally not supported)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Global Caché device from a config entry."""
    coordinator = CachixCoordinator(hass, entry)

    try:
        await coordinator.async_connect()
    except ConnectionFailed as err:
        raise ConfigEntryNotReady(
            f"Cannot connect to {entry.data[CONF_HOST]}: {err}"
        ) from err

    # First data pull – populates version, modules, port states.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Forward to entity platforms.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register domain services (idempotent).
    _async_register_services(hass)

    # Reload on options change (new/edited commands).
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info(
        "Cachix: device %s at %s is ready",
        entry.title,
        entry.data[CONF_HOST],
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and disconnect from the device."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: CachixCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_disconnect()
    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload entry when options change (commands added/removed/edited)."""
    await hass.config_entries.async_reload(entry.entry_id)


# ═════════════════════════════════════════════════════════════════════════════
#  Services
# ═════════════════════════════════════════════════════════════════════════════


def _get_coordinator(
    hass: HomeAssistant, device_id: str
) -> CachixCoordinator | None:
    """Resolve a coordinator by config-entry ID *or* device UUID."""
    domain_data: dict[str, CachixCoordinator] = hass.data.get(DOMAIN, {})

    # Direct entry-id lookup.
    if device_id in domain_data:
        return domain_data[device_id]

    # Fallback: match on UUID stored in entry data.
    for coordinator in domain_data.values():
        if coordinator.entry.data.get("uuid") == device_id:
            return coordinator
    return None


def _async_register_services(hass: HomeAssistant) -> None:
    """Register cachix.* services (called once, idempotent)."""

    if hass.services.has_service(DOMAIN, "send_command"):
        return

    # ── send_command ─────────────────────────────────────────────────────

    async def _handle_send_command(call: ServiceCall) -> None:
        device_id: str = call.data["device_id"]
        command_name: str | None = call.data.get("command_name")
        raw_command: str | None = call.data.get("raw_command")

        coordinator = _get_coordinator(hass, device_id)
        if coordinator is None:
            raise ServiceValidationError(
                f"No Cachix device found for ID '{device_id}'",
                translation_domain=DOMAIN,
                translation_key="device_not_found",
            )

        if raw_command:
            response = await coordinator.client.send_raw(raw_command)
            coordinator.set_last_command(raw_command)
        elif command_name:
            commands = coordinator.entry.options.get(CONF_COMMANDS, [])
            cmd = next(
                (c for c in commands if c[CMD_KEY_NAME] == command_name), None
            )
            if cmd is None:
                raise ServiceValidationError(
                    f"Command '{command_name}' not found on this device",
                    translation_domain=DOMAIN,
                    translation_key="command_not_found",
                )
            response = await coordinator.client.send_raw(cmd[CMD_KEY_COMMAND])
            coordinator.set_last_command(cmd[CMD_KEY_COMMAND])
        else:
            raise ServiceValidationError(
                "Provide either 'command_name' or 'raw_command'",
                translation_domain=DOMAIN,
                translation_key="missing_command",
            )

        _LOGGER.info("send_command response: %s", response)

    hass.services.async_register(
        DOMAIN,
        "send_command",
        _handle_send_command,
        schema=vol.Schema(
            {
                vol.Required("device_id"): cv.string,
                vol.Optional("command_name"): cv.string,
                vol.Optional("raw_command"): cv.string,
            }
        ),
    )

    # ── send_ir ──────────────────────────────────────────────────────────

    async def _handle_send_ir(call: ServiceCall) -> None:
        device_id: str = call.data["device_id"]
        command: str = call.data["command"]

        coordinator = _get_coordinator(hass, device_id)
        if coordinator is None:
            raise ServiceValidationError(
                f"No Cachix device found for ID '{device_id}'",
                translation_domain=DOMAIN,
                translation_key="device_not_found",
            )

        response = await coordinator.client.send_ir(command)
        coordinator.set_last_command(command)
        _LOGGER.info("send_ir response: %s", response)

    hass.services.async_register(
        DOMAIN,
        "send_ir",
        _handle_send_ir,
        schema=vol.Schema(
            {
                vol.Required("device_id"): cv.string,
                vol.Required("command"): cv.string,
            }
        ),
    )

    # ── learn_ir ─────────────────────────────────────────────────────────

    async def _handle_learn_ir(call: ServiceCall) -> None:
        device_id: str = call.data["device_id"]

        coordinator = _get_coordinator(hass, device_id)
        if coordinator is None:
            raise ServiceValidationError(
                f"No Cachix device found for ID '{device_id}'",
                translation_domain=DOMAIN,
                translation_key="device_not_found",
            )

        response = await coordinator.client.start_ir_learner()
        _LOGGER.info("learn_ir started – response: %s", response)

    hass.services.async_register(
        DOMAIN,
        "learn_ir",
        _handle_learn_ir,
        schema=vol.Schema(
            {
                vol.Required("device_id"): cv.string,
            }
        ),
    )
