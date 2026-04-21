"""Button entities for the Cachix integration.

One Button entity is created for every command stored in the config-entry
options.  Pressing the button sends the stored TCP command to the device.

IR commands are auto-assembled from structured fields (frequency, repeat,
pulse data).  Relay commands use setstate.  Serial commands use set_SERIAL.
Raw commands are sent verbatim.
"""
from __future__ import annotations

import logging
import re
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
_PRONTO_FREQ_CONSTANT = 4145146

# ── IR ID counter shared across all buttons ──────────────────────────────────
_ir_id_counter: int = 0


def _next_ir_id() -> int:
    """Return a rotating IR command-ID (1-65535)."""
    global _ir_id_counter  # noqa: PLW0603
    _ir_id_counter = _ir_id_counter % 65535 + 1
    return _ir_id_counter


def _split_ir_tokens(value: str) -> list[str]:
    """Split IR values that may be comma-separated, space-separated, or mixed."""
    return [token for token in re.split(r"[\s,]+", value.strip()) if token]


def _looks_like_pronto_hex(tokens: list[str]) -> bool:
    """Return True when *tokens* look like a raw Pronto Hex sequence."""
    if len(tokens) < 6:
        return False
    if not all(re.fullmatch(r"[0-9A-Fa-f]{4}", token) for token in tokens):
        return False
    return tokens[0].lower() in {"0000", "0100"}


def _parse_numeric_token(token: str, *, force_hex: bool = False) -> int:
    """Parse a numeric token that may be decimal or hex."""
    value = token.strip()
    is_hex = (
        force_hex
        or value.lower().startswith("0x")
        or bool(re.search(r"[A-Fa-f]", value))
    )
    return int(value, 16 if is_hex else 10)


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
        """Assemble a ``sendir`` string from the stored IR fields.

        The Global Caché sendir format is:
        sendir,<module>:<port>,<id>,<frequency>,<repeat>,<offset>,<pulse1>,<pulse2>,...

        If the user enters a full sendir command, normalize delimiters and use it.
        Otherwise, parse the IR code values and build a valid sendir payload.
        """
        ir_code = self._cmd.get(CMD_KEY_IR_CODE, "").strip()
        if not ir_code:
            raise ValueError("No IR code provided")
        cid = _next_ir_id()
        repeat = int(self._cmd.get(CMD_KEY_REPEAT, DEFAULT_IR_REPEAT))

        # If the user stored a full sendir string, normalize delimiters.
        if ir_code.lower().startswith("sendir"):
            parts = _split_ir_tokens(ir_code)
            if len(parts) < 7:
                raise ValueError(
                    "Invalid sendir format. Expected at least 7 values: "
                    "sendir,<module>:<port>,<id>,<frequency>,<repeat>,<offset>,<pulse...>"
                )
            return ",".join(parts)

        tokens = _split_ir_tokens(ir_code)

        # Pronto Hex support (e.g. "0000 0071 0000 009A ...").
        if _looks_like_pronto_hex(tokens):
            pronto = [_parse_numeric_token(token, force_hex=True) for token in tokens]
            code_type, pronto_freq, intro_pairs, repeat_pairs = pronto[:4]
            if code_type != 0:
                raise ValueError(
                    "Unsupported Pronto code type. Only raw (0000) Pronto Hex is supported."
                )

            total_pairs = intro_pairs + repeat_pairs
            expected_words = 4 + (total_pairs * 2)
            if len(pronto) < expected_words:
                raise ValueError(
                    "Incomplete Pronto code: expected "
                    f"{expected_words} words but got {len(pronto)}"
                )

            pulse_nums = pronto[4:expected_words]
            if not pulse_nums:
                raise ValueError("Pronto code does not include pulse data")

            # Derive carrier frequency from the Pronto header.
            freq = (
                round(_PRONTO_FREQ_CONSTANT / pronto_freq)
                if pronto_freq > 0
                else int(self._cmd.get(CMD_KEY_FREQUENCY, DEFAULT_IR_FREQUENCY))
            )
            offset = intro_pairs + 1 if intro_pairs > 0 else 1

            if len(pulse_nums) % 2 != 0:
                pulse_nums.append(1000)

            pulse_str = ",".join(str(p) for p in pulse_nums)
            return f"sendir,{self._module_port},{cid},{freq},{repeat},{offset},{pulse_str}"

        # Accept comma-separated, space-separated, or mixed pulse input.
        try:
            pulse_nums = [_parse_numeric_token(token) for token in tokens]
        except ValueError as e:
            raise ValueError(
                "Invalid IR code format - all values must be decimal or hex numbers: "
                f"{ir_code}"
            ) from e

        # If we have an odd number of pulse values, add a final off pulse.
        if len(pulse_nums) % 2 != 0:
            # Add a default off pulse if odd number of pulses
            pulse_nums.append(1000)  # 1ms default off time

        freq = self._cmd.get(CMD_KEY_FREQUENCY, DEFAULT_IR_FREQUENCY)

        # Format: sendir,<port>,<id>,<freq>,<repeat>,1,<pulse1>,<pulse2>,...
        pulse_str = ",".join(str(p) for p in pulse_nums)
        return f"sendir,{self._module_port},{cid},{freq},{repeat},1,{pulse_str}"

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
        cmd_str = ""
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
                "Failed to send command '%s' (payload preview: %s)",
                self._cmd_name,
                cmd_str[:200],
                exc_info=True,
            )
            raise
