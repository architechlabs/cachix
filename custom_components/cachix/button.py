"""Button entities for the Cachix integration.

One Button entity is created for every command stored in the config-entry
options.  Pressing the button sends the stored TCP command to the device.

IR commands are auto-assembled from structured fields (frequency, repeat,
pulse data).  Relay commands use setstate.  Serial commands use set_SERIAL.
Raw commands are sent verbatim.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import GlobalCacheClient
from .const import (
    CMD_KEY_COMMAND,
    CMD_KEY_DESCRIPTION,
    CMD_KEY_FREQUENCY,
    CMD_KEY_ICON,
    CMD_KEY_ID,
    CMD_KEY_IR_CODE,
    CMD_KEY_MODULE_PORT,
    CMD_KEY_NAME,
    CMD_KEY_RELAY_ACTION,
    CMD_KEY_REPEAT,
    CMD_KEY_SERIAL_DATA,
    CMD_KEY_TYPE,
    COMMAND_TYPE_IR,
    COMMAND_TYPE_RAW,
    COMMAND_TYPE_RELAY,
    COMMAND_TYPE_SERIAL,
    CONF_COMMANDS,
    DEFAULT_ICONS,
    DEFAULT_IR_FREQUENCY,
    DEFAULT_IR_REPEAT,
    DOMAIN,
    RELAY_ACTION_OFF,
    RELAY_ACTION_ON,
    RELAY_ACTION_TOGGLE,
)
from .coordinator import CachixCoordinator
from .entity import CachixEntity

_LOGGER = logging.getLogger(__name__)

# ── IR ID counter shared across all buttons ──────────────────────────────────
_ir_id_counter: int = 0


def _next_ir_id() -> int:
    """Return a rotating IR command-ID (1-65535)."""
    global _ir_id_counter  # noqa: PLW0603
    _ir_id_counter = _ir_id_counter % 65535 + 1
    return _ir_id_counter


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create button entities for every stored command."""
    coordinator: CachixCoordinator = hass.data[DOMAIN][entry.entry_id]
    commands: list[dict[str, Any]] = entry.options.get(CONF_COMMANDS, [])

    async_add_entities(
        CachixCommandButton(coordinator, entry, cmd) for cmd in commands
    )


class CachixCommandButton(CachixEntity, ButtonEntity):
    """A button that sends a single Global Caché command on press."""

    def __init__(
        self,
        coordinator: CachixCoordinator,
        entry: ConfigEntry,
        command: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, entry)
        self._cmd = command
        self._cmd_id: str = command[CMD_KEY_ID]
        self._cmd_name: str = command[CMD_KEY_NAME]
        self._cmd_type: str = command[CMD_KEY_TYPE]
        self._module_port: str = command.get(CMD_KEY_MODULE_PORT, "1:1")

        self._attr_name = self._cmd_name
        self._attr_unique_id = f"{entry.entry_id}_{self._cmd_id}"
        self._attr_icon = command.get(CMD_KEY_ICON) or DEFAULT_ICONS.get(
            self._cmd_type, "mdi:remote"
        )
        desc = command.get(CMD_KEY_DESCRIPTION, "")
        if desc:
            self._attr_entity_description = desc

    # ── Command builders (from structured fields) ────────────────────────

    def _build_ir_command(self) -> str:
        """Assemble a ``sendir`` string from the stored IR fields."""
        ir_code = self._cmd.get(CMD_KEY_IR_CODE, "")
        # If the user stored a full sendir string, use it as-is.
        if ir_code.lower().startswith("sendir"):
            return ir_code
        freq = self._cmd.get(CMD_KEY_FREQUENCY, DEFAULT_IR_FREQUENCY)
        repeat = self._cmd.get(CMD_KEY_REPEAT, DEFAULT_IR_REPEAT)
        cid = _next_ir_id()
        return f"sendir,{self._module_port},{cid},{freq},{repeat},1,{ir_code}"

    def _build_relay_command(self) -> str:
        """Build the ``setstate`` string for the stored relay action."""
        action = self._cmd.get(CMD_KEY_RELAY_ACTION, RELAY_ACTION_ON)
        if action == RELAY_ACTION_ON:
            return f"setstate,{self._module_port},1"
        if action == RELAY_ACTION_OFF:
            return f"setstate,{self._module_port},0"
        # TOGGLE: read current state first
        return ""  # handled specially in async_press

    def _build_serial_command(self) -> str:
        """Build the ``set_SERIAL`` string from the stored serial data."""
        data = self._cmd.get(CMD_KEY_SERIAL_DATA, "")
        return f"set_SERIAL,{self._module_port},{data}"

    # ── Press handler ────────────────────────────────────────────────────

    async def async_press(self) -> None:
        """Handle the button press – build and send the command."""
        client: GlobalCacheClient = self.coordinator.client
        host = self._entry.data.get("host", "?")
        _LOGGER.info(
            "Sending %s command '%s' → %s",
            self._cmd_type,
            self._cmd_name,
            host,
        )
        try:
            if self._cmd_type == COMMAND_TYPE_IR:
                cmd_str = self._build_ir_command()
                response = await client.send_ir(cmd_str)

            elif self._cmd_type == COMMAND_TYPE_RELAY:
                action = self._cmd.get(CMD_KEY_RELAY_ACTION, RELAY_ACTION_ON)
                if action == RELAY_ACTION_TOGGLE:
                    current = await client.get_state(self._module_port)
                    new_val = 0 if current == 1 else 1
                    cmd_str = f"setstate,{self._module_port},{new_val}"
                else:
                    cmd_str = self._build_relay_command()
                response = await client.send_raw(cmd_str)

            elif self._cmd_type == COMMAND_TYPE_SERIAL:
                cmd_str = self._build_serial_command()
                response = await client.send_raw(cmd_str)

            else:
                # Raw – use the stored command string verbatim
                cmd_str = self._cmd.get(CMD_KEY_COMMAND, "")
                response = await client.send_raw(cmd_str)

            self.coordinator.set_last_command(cmd_str)
            _LOGGER.debug("Command '%s' response: %s", self._cmd_name, response)
        except Exception:
            _LOGGER.error(
                "Failed to send command '%s'", self._cmd_name, exc_info=True
            )
            raise
