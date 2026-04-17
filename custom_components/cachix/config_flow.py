"""Config flow and Options flow for the Cachix integration.

Config flow
-----------
1. **User step** – menu: *Discover* | *Manual*.
2. **Discover** – scans the LAN via UDP multicast, shows found devices.
3. **Manual** – simple host / port form.
Both paths validate the TCP connection before creating the entry.

Options flow
------------
Menu-driven command manager: Add / Edit / Remove commands, plus
general settings (polling interval).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    IconSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .client import ConnectionFailed, GlobalCacheClient
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
    COMMAND_TYPES,
    CONF_COMMANDS,
    CONF_FIRMWARE,
    CONF_HOST,
    CONF_MODEL,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_UUID,
    DEFAULT_ICONS,
    DEFAULT_IR_FREQUENCY,
    DEFAULT_IR_REPEAT,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    IR_FREQUENCIES,
    RELAY_ACTION_OFF,
    RELAY_ACTION_ON,
    RELAY_ACTION_TOGGLE,
)
from .discovery import GlobalCacheDiscovery

_LOGGER = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
#  Config Flow
# ═════════════════════════════════════════════════════════════════════════════


class CachixConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle initial setup of a Global Caché device."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise transient flow state."""
        self._discovered_devices: dict[str, dict[str, Any]] = {}

    # ── static ───────────────────────────────────────────────────────────

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CachixOptionsFlow:
        """Return the options-flow handler."""
        return CachixOptionsFlow(config_entry)

    # ── Step: user (menu) ────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry point – show discover / manual menu."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["discover", "manual"],
        )

    # ── Step: discover ───────────────────────────────────────────────────

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Scan the LAN for Global Caché beacons."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_uuid = user_input.get("device", "")
            dev = self._discovered_devices.get(selected_uuid)
            if dev:
                host = dev["host"]
                model = dev.get("model", "Global Caché")
                try:
                    version = await self._async_validate_connection(host, DEFAULT_PORT)
                except ConnectionFailed:
                    errors["base"] = "cannot_connect"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Unexpected error validating %s", host)
                    errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(selected_uuid)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=model,
                        data={
                            CONF_HOST: host,
                            CONF_PORT: DEFAULT_PORT,
                            CONF_UUID: selected_uuid,
                            CONF_MODEL: model,
                            CONF_NAME: model,
                            CONF_FIRMWARE: version,
                        },
                        options={
                            CONF_COMMANDS: [],
                            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        },
                    )
        else:
            # First visit → run discovery
            discovery = GlobalCacheDiscovery()
            try:
                self._discovered_devices = await discovery.discover(timeout=5.0)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Discovery error", exc_info=True)
                self._discovered_devices = {}

            if not self._discovered_devices:
                errors["base"] = "no_devices_found"

        # Build the selector options (may be empty on error).
        device_options = [
            {
                "value": uid,
                "label": f"{info['model']} ({info['host']})",
            }
            for uid, info in self._discovered_devices.items()
        ]

        schema: dict[vol.Marker, Any] = {}
        if device_options:
            schema[vol.Required("device")] = SelectSelector(
                SelectSelectorConfig(
                    options=device_options,
                    mode=SelectSelectorMode.LIST,
                )
            )

        return self.async_show_form(
            step_id="discover",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    # ── Step: manual ─────────────────────────────────────────────────────

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual host / port entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            port = int(user_input.get(CONF_PORT, DEFAULT_PORT))

            if not host:
                errors[CONF_HOST] = "invalid_host"
            else:
                try:
                    version = await self._async_validate_connection(host, port)
                except ConnectionFailed:
                    errors["base"] = "cannot_connect"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Unexpected error validating %s:%s", host, port)
                    errors["base"] = "unknown"
                else:
                    device_uuid = f"cachix_{host.replace('.', '_')}"
                    await self.async_set_unique_id(device_uuid)
                    self._abort_if_unique_id_configured()
                    name = f"Global Caché ({host})"
                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_HOST: host,
                            CONF_PORT: port,
                            CONF_UUID: device_uuid,
                            CONF_MODEL: "Global Caché",
                            CONF_NAME: name,
                            CONF_FIRMWARE: version,
                        },
                        options={
                            CONF_COMMANDS: [],
                            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        },
                    )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=65535,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    # ── Internal: validate connection ────────────────────────────────────

    async def _async_validate_connection(self, host: str, port: int) -> str:
        """Connect and return the firmware version string.

        Raises ``ConnectionFailed`` (or another exception) on failure so
        callers can use a clean try/except/else pattern.
        """
        client = GlobalCacheClient(host, port)
        try:
            await client.connect()
            return await client.get_version()
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass


# ═════════════════════════════════════════════════════════════════════════════
#  Helpers  –  Build the final TCP command from structured fields
# ═════════════════════════════════════════════════════════════════════════════


_IR_ID_COUNTER: int = 1


def _next_ir_id() -> int:
    """Return a rotating IR command-ID (1-65535)."""
    global _IR_ID_COUNTER  # noqa: PLW0603
    cid = _IR_ID_COUNTER
    _IR_ID_COUNTER = cid % 65535 + 1
    return cid


def build_ir_command(
    module_port: str, frequency: str, repeat: int, ir_code: str
) -> str:
    """Assemble a full ``sendir`` TCP string from user-friendly fields.

    Accepts *ir_code* as:
      • Pure pulse data: ``347,173,22,22,22,65,…``
      • Full sendir string already: ``sendir,1:1,4,38000,1,1,347,…`` (returned as-is)
      • Global Caché compact/learned format (returned as-is inside sendir wrapper)
    """
    code = ir_code.strip()

    # If the user pasted a complete sendir string, honour it verbatim.
    if code.lower().startswith("sendir"):
        return code

    cid = _next_ir_id()
    # offset is always 1 for normal use
    return f"sendir,{module_port},{cid},{frequency},{repeat},1,{code}"


def build_relay_command(module_port: str, action: str) -> str:
    """Build a ``setstate`` command for a relay port."""
    if action == RELAY_ACTION_ON:
        return f"setstate,{module_port},1"
    if action == RELAY_ACTION_OFF:
        return f"setstate,{module_port},0"
    # toggle – caller handles by reading current state first
    return f"setstate,{module_port},1"


def build_serial_command(module_port: str, data: str) -> str:
    """Build a ``set_SERIAL`` command."""
    return f"set_SERIAL,{module_port},{data}"


# ═════════════════════════════════════════════════════════════════════════════
#  Options Flow  –  Smart, type-specific Command Manager
# ═════════════════════════════════════════════════════════════════════════════


class CachixOptionsFlow(OptionsFlow):
    """Menu-driven options flow with smart per-type command forms."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._commands: list[dict[str, Any]] = list(
            config_entry.options.get(CONF_COMMANDS, [])
        )
        self._scan_interval: int = config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        self._edit_index: int | None = None
        self._pending_type: str | None = None  # type chosen in add_command step

    # ── helpers ───────────────────────────────────────────────────────────

    def _save(self) -> ConfigFlowResult:
        """Persist current state and close the options flow."""
        return self.async_create_entry(
            data={
                CONF_COMMANDS: self._commands,
                CONF_SCAN_INTERVAL: self._scan_interval,
            }
        )

    def _command_select_options(self) -> list[dict[str, str]]:
        """Build a selector-options list from current commands."""
        return [
            {
                "value": cmd[CMD_KEY_ID],
                "label": f"{cmd[CMD_KEY_NAME]}  ({cmd[CMD_KEY_TYPE].upper()})",
            }
            for cmd in self._commands
        ]

    # ── Shared schema fragments ──────────────────────────────────────────

    @staticmethod
    def _name_icon_fields(d: dict[str, Any] | None = None) -> dict:
        """Return the name / icon / description fields shared by all types."""
        d = d or {}
        return {
            vol.Required(CMD_KEY_NAME, default=d.get(CMD_KEY_NAME, "")): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            vol.Optional(CMD_KEY_ICON, default=d.get(CMD_KEY_ICON, "")): IconSelector(),
            vol.Optional(
                CMD_KEY_DESCRIPTION, default=d.get(CMD_KEY_DESCRIPTION, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        }

    @staticmethod
    def _module_port_field(d: dict[str, Any] | None = None) -> dict:
        d = d or {}
        return {
            vol.Required(
                CMD_KEY_MODULE_PORT, default=d.get(CMD_KEY_MODULE_PORT, "1:1")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        }

    # ── Step: init (menu) ────────────────────────────────────────────────

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the command-manager menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "add_command",
                "edit_command",
                "remove_command",
                "settings",
            ],
        )

    # ══════════════════════════════════════════════════════════════════════
    #  ADD COMMAND  – first pick type, then show type-specific form
    # ══════════════════════════════════════════════════════════════════════

    async def async_step_add_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1 of Add: pick the command type."""
        if user_input is not None:
            self._pending_type = user_input[CMD_KEY_TYPE]
            # Route to the correct type-specific form.
            if self._pending_type == COMMAND_TYPE_IR:
                return await self.async_step_add_ir()
            if self._pending_type == COMMAND_TYPE_RELAY:
                return await self.async_step_add_relay()
            if self._pending_type == COMMAND_TYPE_SERIAL:
                return await self.async_step_add_serial()
            return await self.async_step_add_raw()

        return self.async_show_form(
            step_id="add_command",
            data_schema=vol.Schema(
                {
                    vol.Required(CMD_KEY_TYPE, default=COMMAND_TYPE_IR): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": COMMAND_TYPE_IR, "label": "🔴 IR Remote (Infrared)"},
                                {"value": COMMAND_TYPE_RELAY, "label": "⚡ Relay (On/Off Switch)"},
                                {"value": COMMAND_TYPE_SERIAL, "label": "🔌 Serial (RS-232)"},
                                {"value": COMMAND_TYPE_RAW, "label": "⌨️ Raw TCP Command"},
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    # ── Add IR ───────────────────────────────────────────────────────────

    async def async_step_add_ir(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """User-friendly IR command form.

        Fields: name, module:port, frequency, repeat, IR code pulses, icon.
        The integration auto-builds the full ``sendir,…`` string.
        """
        if user_input is not None:
            cmd_string = build_ir_command(
                module_port=user_input.get(CMD_KEY_MODULE_PORT, "1:1"),
                frequency=user_input.get(CMD_KEY_FREQUENCY, DEFAULT_IR_FREQUENCY),
                repeat=int(user_input.get(CMD_KEY_REPEAT, DEFAULT_IR_REPEAT)),
                ir_code=user_input[CMD_KEY_IR_CODE],
            )
            self._commands.append(
                {
                    CMD_KEY_ID: str(_uuid.uuid4())[:8],
                    CMD_KEY_NAME: user_input[CMD_KEY_NAME],
                    CMD_KEY_TYPE: COMMAND_TYPE_IR,
                    CMD_KEY_MODULE_PORT: user_input.get(CMD_KEY_MODULE_PORT, "1:1"),
                    CMD_KEY_FREQUENCY: user_input.get(CMD_KEY_FREQUENCY, DEFAULT_IR_FREQUENCY),
                    CMD_KEY_REPEAT: int(user_input.get(CMD_KEY_REPEAT, DEFAULT_IR_REPEAT)),
                    CMD_KEY_IR_CODE: user_input[CMD_KEY_IR_CODE],
                    CMD_KEY_COMMAND: cmd_string,
                    CMD_KEY_ICON: user_input.get(CMD_KEY_ICON) or "mdi:remote",
                    CMD_KEY_DESCRIPTION: user_input.get(CMD_KEY_DESCRIPTION, ""),
                }
            )
            return self._save()

        schema_fields: dict[vol.Marker, Any] = {}
        schema_fields.update(self._name_icon_fields())
        schema_fields.update(self._module_port_field())
        schema_fields.update(
            {
                vol.Required(
                    CMD_KEY_FREQUENCY, default=DEFAULT_IR_FREQUENCY
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=IR_FREQUENCIES,
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                    )
                ),
                vol.Required(CMD_KEY_REPEAT, default=DEFAULT_IR_REPEAT): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=50,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CMD_KEY_IR_CODE): TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.TEXT,
                        multiline=True,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="add_ir",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={
                "ir_hint": (
                    "Paste only the IR pulse data (e.g. 347,173,22,22,22,65,…) "
                    "OR a full sendir,… string. The integration builds the "
                    "complete command automatically."
                ),
            },
        )

    # ── Add Relay ────────────────────────────────────────────────────────

    async def async_step_add_relay(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Simple relay On / Off / Toggle form."""
        if user_input is not None:
            action = user_input[CMD_KEY_RELAY_ACTION]
            cmd_string = build_relay_command(
                module_port=user_input.get(CMD_KEY_MODULE_PORT, "1:1"),
                action=action,
            )
            self._commands.append(
                {
                    CMD_KEY_ID: str(_uuid.uuid4())[:8],
                    CMD_KEY_NAME: user_input[CMD_KEY_NAME],
                    CMD_KEY_TYPE: COMMAND_TYPE_RELAY,
                    CMD_KEY_MODULE_PORT: user_input.get(CMD_KEY_MODULE_PORT, "1:1"),
                    CMD_KEY_RELAY_ACTION: action,
                    CMD_KEY_COMMAND: cmd_string,
                    CMD_KEY_ICON: user_input.get(CMD_KEY_ICON) or "mdi:electric-switch",
                    CMD_KEY_DESCRIPTION: user_input.get(CMD_KEY_DESCRIPTION, ""),
                }
            )
            return self._save()

        schema_fields: dict[vol.Marker, Any] = {}
        schema_fields.update(self._name_icon_fields())
        schema_fields.update(self._module_port_field())
        schema_fields[vol.Required(CMD_KEY_RELAY_ACTION, default=RELAY_ACTION_ON)] = (
            SelectSelector(
                SelectSelectorConfig(
                    options=[
                        {"value": RELAY_ACTION_ON, "label": "Turn ON (close relay)"},
                        {"value": RELAY_ACTION_OFF, "label": "Turn OFF (open relay)"},
                        {"value": RELAY_ACTION_TOGGLE, "label": "Toggle"},
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        )

        return self.async_show_form(
            step_id="add_relay",
            data_schema=vol.Schema(schema_fields),
        )

    # ── Add Serial ───────────────────────────────────────────────────────

    async def async_step_add_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Serial data form."""
        if user_input is not None:
            cmd_string = build_serial_command(
                module_port=user_input.get(CMD_KEY_MODULE_PORT, "1:1"),
                data=user_input[CMD_KEY_SERIAL_DATA],
            )
            self._commands.append(
                {
                    CMD_KEY_ID: str(_uuid.uuid4())[:8],
                    CMD_KEY_NAME: user_input[CMD_KEY_NAME],
                    CMD_KEY_TYPE: COMMAND_TYPE_SERIAL,
                    CMD_KEY_MODULE_PORT: user_input.get(CMD_KEY_MODULE_PORT, "1:1"),
                    CMD_KEY_SERIAL_DATA: user_input[CMD_KEY_SERIAL_DATA],
                    CMD_KEY_COMMAND: cmd_string,
                    CMD_KEY_ICON: user_input.get(CMD_KEY_ICON) or "mdi:serial-port",
                    CMD_KEY_DESCRIPTION: user_input.get(CMD_KEY_DESCRIPTION, ""),
                }
            )
            return self._save()

        schema_fields: dict[vol.Marker, Any] = {}
        schema_fields.update(self._name_icon_fields())
        schema_fields.update(self._module_port_field())
        schema_fields[vol.Required(CMD_KEY_SERIAL_DATA)] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
        )

        return self.async_show_form(
            step_id="add_serial",
            data_schema=vol.Schema(schema_fields),
        )

    # ── Add Raw ──────────────────────────────────────────────────────────

    async def async_step_add_raw(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Power-user raw TCP command form."""
        if user_input is not None:
            self._commands.append(
                {
                    CMD_KEY_ID: str(_uuid.uuid4())[:8],
                    CMD_KEY_NAME: user_input[CMD_KEY_NAME],
                    CMD_KEY_TYPE: COMMAND_TYPE_RAW,
                    CMD_KEY_MODULE_PORT: "",
                    CMD_KEY_COMMAND: user_input[CMD_KEY_COMMAND],
                    CMD_KEY_ICON: user_input.get(CMD_KEY_ICON) or "mdi:console",
                    CMD_KEY_DESCRIPTION: user_input.get(CMD_KEY_DESCRIPTION, ""),
                }
            )
            return self._save()

        schema_fields: dict[vol.Marker, Any] = {}
        schema_fields.update(self._name_icon_fields())
        schema_fields[vol.Required(CMD_KEY_COMMAND)] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
        )

        return self.async_show_form(
            step_id="add_raw",
            data_schema=vol.Schema(schema_fields),
        )

    # ══════════════════════════════════════════════════════════════════════
    #  EDIT COMMAND  – select → route to correct type-specific form
    # ══════════════════════════════════════════════════════════════════════

    async def async_step_edit_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select which command to edit."""
        if not self._commands:
            return self.async_abort(reason="no_commands")

        if user_input is not None:
            selected_id = user_input.get("command_select", "")
            for idx, cmd in enumerate(self._commands):
                if cmd[CMD_KEY_ID] == selected_id:
                    self._edit_index = idx
                    # Route to the right type-specific edit form.
                    cmd_type = cmd.get(CMD_KEY_TYPE, COMMAND_TYPE_RAW)
                    if cmd_type == COMMAND_TYPE_IR:
                        return await self.async_step_edit_ir()
                    if cmd_type == COMMAND_TYPE_RELAY:
                        return await self.async_step_edit_relay()
                    if cmd_type == COMMAND_TYPE_SERIAL:
                        return await self.async_step_edit_serial()
                    return await self.async_step_edit_raw()
            return self.async_abort(reason="command_not_found")

        return self.async_show_form(
            step_id="edit_command",
            data_schema=vol.Schema(
                {
                    vol.Required("command_select"): SelectSelector(
                        SelectSelectorConfig(
                            options=self._command_select_options(),
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    # ── Edit IR ──────────────────────────────────────────────────────────

    async def async_step_edit_ir(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit an existing IR command with friendly fields."""
        if self._edit_index is None:
            return self.async_abort(reason="command_not_found")
        cmd = self._commands[self._edit_index]

        if user_input is not None:
            cmd_string = build_ir_command(
                module_port=user_input.get(CMD_KEY_MODULE_PORT, "1:1"),
                frequency=user_input.get(CMD_KEY_FREQUENCY, DEFAULT_IR_FREQUENCY),
                repeat=int(user_input.get(CMD_KEY_REPEAT, DEFAULT_IR_REPEAT)),
                ir_code=user_input[CMD_KEY_IR_CODE],
            )
            cmd.update(
                {
                    CMD_KEY_NAME: user_input[CMD_KEY_NAME],
                    CMD_KEY_MODULE_PORT: user_input.get(CMD_KEY_MODULE_PORT, "1:1"),
                    CMD_KEY_FREQUENCY: user_input.get(CMD_KEY_FREQUENCY, DEFAULT_IR_FREQUENCY),
                    CMD_KEY_REPEAT: int(user_input.get(CMD_KEY_REPEAT, DEFAULT_IR_REPEAT)),
                    CMD_KEY_IR_CODE: user_input[CMD_KEY_IR_CODE],
                    CMD_KEY_COMMAND: cmd_string,
                    CMD_KEY_ICON: user_input.get(CMD_KEY_ICON) or "mdi:remote",
                    CMD_KEY_DESCRIPTION: user_input.get(CMD_KEY_DESCRIPTION, ""),
                }
            )
            self._commands[self._edit_index] = cmd
            return self._save()

        d = cmd
        schema_fields: dict[vol.Marker, Any] = {}
        schema_fields.update(self._name_icon_fields(d))
        schema_fields.update(self._module_port_field(d))
        schema_fields.update(
            {
                vol.Required(
                    CMD_KEY_FREQUENCY,
                    default=d.get(CMD_KEY_FREQUENCY, DEFAULT_IR_FREQUENCY),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=IR_FREQUENCIES,
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                    )
                ),
                vol.Required(
                    CMD_KEY_REPEAT,
                    default=d.get(CMD_KEY_REPEAT, DEFAULT_IR_REPEAT),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=50, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CMD_KEY_IR_CODE, default=d.get(CMD_KEY_IR_CODE, "")
                ): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
                ),
            }
        )

        return self.async_show_form(
            step_id="edit_ir",
            data_schema=vol.Schema(schema_fields),
        )

    # ── Edit Relay ───────────────────────────────────────────────────────

    async def async_step_edit_relay(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit an existing relay command."""
        if self._edit_index is None:
            return self.async_abort(reason="command_not_found")
        cmd = self._commands[self._edit_index]

        if user_input is not None:
            action = user_input[CMD_KEY_RELAY_ACTION]
            cmd_string = build_relay_command(
                module_port=user_input.get(CMD_KEY_MODULE_PORT, "1:1"),
                action=action,
            )
            cmd.update(
                {
                    CMD_KEY_NAME: user_input[CMD_KEY_NAME],
                    CMD_KEY_MODULE_PORT: user_input.get(CMD_KEY_MODULE_PORT, "1:1"),
                    CMD_KEY_RELAY_ACTION: action,
                    CMD_KEY_COMMAND: cmd_string,
                    CMD_KEY_ICON: user_input.get(CMD_KEY_ICON) or "mdi:electric-switch",
                    CMD_KEY_DESCRIPTION: user_input.get(CMD_KEY_DESCRIPTION, ""),
                }
            )
            self._commands[self._edit_index] = cmd
            return self._save()

        d = cmd
        schema_fields: dict[vol.Marker, Any] = {}
        schema_fields.update(self._name_icon_fields(d))
        schema_fields.update(self._module_port_field(d))
        schema_fields[
            vol.Required(
                CMD_KEY_RELAY_ACTION,
                default=d.get(CMD_KEY_RELAY_ACTION, RELAY_ACTION_ON),
            )
        ] = SelectSelector(
            SelectSelectorConfig(
                options=[
                    {"value": RELAY_ACTION_ON, "label": "Turn ON (close relay)"},
                    {"value": RELAY_ACTION_OFF, "label": "Turn OFF (open relay)"},
                    {"value": RELAY_ACTION_TOGGLE, "label": "Toggle"},
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )

        return self.async_show_form(
            step_id="edit_relay",
            data_schema=vol.Schema(schema_fields),
        )

    # ── Edit Serial ──────────────────────────────────────────────────────

    async def async_step_edit_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit an existing serial command."""
        if self._edit_index is None:
            return self.async_abort(reason="command_not_found")
        cmd = self._commands[self._edit_index]

        if user_input is not None:
            cmd_string = build_serial_command(
                module_port=user_input.get(CMD_KEY_MODULE_PORT, "1:1"),
                data=user_input[CMD_KEY_SERIAL_DATA],
            )
            cmd.update(
                {
                    CMD_KEY_NAME: user_input[CMD_KEY_NAME],
                    CMD_KEY_MODULE_PORT: user_input.get(CMD_KEY_MODULE_PORT, "1:1"),
                    CMD_KEY_SERIAL_DATA: user_input[CMD_KEY_SERIAL_DATA],
                    CMD_KEY_COMMAND: cmd_string,
                    CMD_KEY_ICON: user_input.get(CMD_KEY_ICON) or "mdi:serial-port",
                    CMD_KEY_DESCRIPTION: user_input.get(CMD_KEY_DESCRIPTION, ""),
                }
            )
            self._commands[self._edit_index] = cmd
            return self._save()

        d = cmd
        schema_fields: dict[vol.Marker, Any] = {}
        schema_fields.update(self._name_icon_fields(d))
        schema_fields.update(self._module_port_field(d))
        schema_fields[
            vol.Required(CMD_KEY_SERIAL_DATA, default=d.get(CMD_KEY_SERIAL_DATA, ""))
        ] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
        )

        return self.async_show_form(
            step_id="edit_serial",
            data_schema=vol.Schema(schema_fields),
        )

    # ── Edit Raw ─────────────────────────────────────────────────────────

    async def async_step_edit_raw(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit an existing raw TCP command."""
        if self._edit_index is None:
            return self.async_abort(reason="command_not_found")
        cmd = self._commands[self._edit_index]

        if user_input is not None:
            cmd.update(
                {
                    CMD_KEY_NAME: user_input[CMD_KEY_NAME],
                    CMD_KEY_COMMAND: user_input[CMD_KEY_COMMAND],
                    CMD_KEY_ICON: user_input.get(CMD_KEY_ICON) or "mdi:console",
                    CMD_KEY_DESCRIPTION: user_input.get(CMD_KEY_DESCRIPTION, ""),
                }
            )
            self._commands[self._edit_index] = cmd
            return self._save()

        d = cmd
        schema_fields: dict[vol.Marker, Any] = {}
        schema_fields.update(self._name_icon_fields(d))
        schema_fields[
            vol.Required(CMD_KEY_COMMAND, default=d.get(CMD_KEY_COMMAND, ""))
        ] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
        )

        return self.async_show_form(
            step_id="edit_raw",
            data_schema=vol.Schema(schema_fields),
        )

    # ══════════════════════════════════════════════════════════════════════
    #  REMOVE COMMAND
    # ══════════════════════════════════════════════════════════════════════

    async def async_step_remove_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a command."""
        if not self._commands:
            return self.async_abort(reason="no_commands")

        if user_input is not None:
            selected_id = user_input.get("command_select", "")
            self._commands = [
                c for c in self._commands if c[CMD_KEY_ID] != selected_id
            ]
            return self._save()

        return self.async_show_form(
            step_id="remove_command",
            data_schema=vol.Schema(
                {
                    vol.Required("command_select"): SelectSelector(
                        SelectSelectorConfig(
                            options=self._command_select_options(),
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    # ══════════════════════════════════════════════════════════════════════
    #  SETTINGS
    # ══════════════════════════════════════════════════════════════════════

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """General integration settings."""
        if user_input is not None:
            self._scan_interval = int(
                user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            )
            return self._save()

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self._scan_interval,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=10,
                            max=300,
                            step=5,
                            mode=NumberSelectorMode.SLIDER,
                            unit_of_measurement="seconds",
                        )
                    ),
                }
            ),
        )
