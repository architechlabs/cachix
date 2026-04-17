"""Constants for the Cachix integration."""
from __future__ import annotations

DOMAIN = "cachix"
MANUFACTURER = "Architech Labs"

# ── Network Defaults ─────────────────────────────────────────────────────────
DEFAULT_PORT = 4998
DISCOVERY_MULTICAST_GROUP = "239.255.250.250"
DISCOVERY_PORT = 9131

# ── Timeouts & Intervals ────────────────────────────────────────────────────
DEFAULT_TIMEOUT = 5.0
IR_SEND_TIMEOUT = 10.0
DEFAULT_SCAN_INTERVAL = 30
RECONNECT_MIN_DELAY = 1
RECONNECT_MAX_DELAY = 60

# ── Command Types ────────────────────────────────────────────────────────────
COMMAND_TYPE_IR = "ir"
COMMAND_TYPE_RELAY = "relay"
COMMAND_TYPE_SERIAL = "serial"
COMMAND_TYPE_RAW = "raw"

COMMAND_TYPES: list[str] = [
    COMMAND_TYPE_IR,
    COMMAND_TYPE_RELAY,
    COMMAND_TYPE_SERIAL,
    COMMAND_TYPE_RAW,
]

# ── Global Caché TCP API Commands ────────────────────────────────────────────
CMD_GETVERSION = "getversion"
CMD_GETDEVICES = "getdevices"
CMD_GETSTATE = "getstate"
CMD_SETSTATE = "setstate"
CMD_SENDIR = "sendir"
CMD_STOPIR = "stopir"
CMD_GET_IRL = "get_IRL"
CMD_STOP_IRL = "stop_IRL"
CMD_GET_SERIAL = "get_SERIAL"
CMD_SET_SERIAL = "set_SERIAL"

# ── Response Prefixes ────────────────────────────────────────────────────────
RESP_VERSION = "version"
RESP_DEVICE = "device"
RESP_END_DEVICES = "endlistdevices"
RESP_STATE = "state"
RESP_COMPLETE_IR = "completeir"
RESP_BUSY_IR = "busyir"
RESP_STOP_IR = "stopir"
RESP_IR_LEARN = "IR Learner"
RESP_ERROR = "ERR"

# ── Module Types (from getdevices) ───────────────────────────────────────────
MODULE_TYPE_IR = "IR"
MODULE_TYPE_SERIAL = "SERIAL"
MODULE_TYPE_RELAY = "RELAY"
MODULE_TYPE_SENSOR = "SENSOR"
MODULE_TYPE_IR_BLASTER = "IR_BLASTER"
MODULE_TYPE_WIFI = "WIFI"
MODULE_TYPE_NET = "NET"

# ── Config Entry Keys ───────────────────────────────────────────────────────
CONF_HOST = "host"
CONF_PORT = "port"
CONF_NAME = "name"
CONF_UUID = "uuid"
CONF_MODEL = "model"
CONF_FIRMWARE = "firmware"
CONF_COMMANDS = "commands"
CONF_SCAN_INTERVAL = "scan_interval"

# ── Command Dictionary Keys ─────────────────────────────────────────────────
CMD_KEY_ID = "id"
CMD_KEY_NAME = "name"
CMD_KEY_TYPE = "command_type"
CMD_KEY_MODULE_PORT = "module_port"
CMD_KEY_COMMAND = "command"
CMD_KEY_ICON = "icon"
CMD_KEY_DESCRIPTION = "description"

# IR-specific structured fields
CMD_KEY_FREQUENCY = "frequency"
CMD_KEY_REPEAT = "repeat"
CMD_KEY_IR_CODE = "ir_code"

# Relay-specific
CMD_KEY_RELAY_ACTION = "relay_action"
RELAY_ACTION_ON = "on"
RELAY_ACTION_OFF = "off"
RELAY_ACTION_TOGGLE = "toggle"

# Serial-specific
CMD_KEY_SERIAL_DATA = "serial_data"

# ── Common IR Frequencies ────────────────────────────────────────────────────
IR_FREQUENCIES: list[dict[str, str]] = [
    {"value": "38000", "label": "38 kHz (most common)"},
    {"value": "40000", "label": "40 kHz (Sony / Panasonic)"},
    {"value": "36000", "label": "36 kHz (Philips RC-5/RC-6)"},
    {"value": "56000", "label": "56 kHz (Bang & Olufsen)"},
    {"value": "455000", "label": "455 kHz (RS-232 bridge)"},
]

DEFAULT_IR_FREQUENCY = "38000"
DEFAULT_IR_REPEAT = 1

# ── Entity Platforms ─────────────────────────────────────────────────────────
PLATFORMS: list[str] = ["button", "sensor", "binary_sensor", "switch"]

# ── Default Icons per Command Type ───────────────────────────────────────────
DEFAULT_ICONS: dict[str, str] = {
    COMMAND_TYPE_IR: "mdi:remote",
    COMMAND_TYPE_RELAY: "mdi:electric-switch",
    COMMAND_TYPE_SERIAL: "mdi:serial-port",
    COMMAND_TYPE_RAW: "mdi:console",
}

# ── Global Caché Error Codes ────────────────────────────────────────────────
GC_ERROR_CODES: dict[str, str] = {
    "001": "Invalid command. Command not found.",
    "002": "Invalid module address (does not exist).",
    "003": "Invalid connector address (does not exist).",
    "004": "Invalid ID value.",
    "005": "Invalid frequency value.",
    "006": "Invalid repeat value.",
    "007": "Invalid offset value.",
    "008": "Invalid pulse data.",
    "009": "Invalid state value.",
    "010": "Invalid port value.",
    "011": "Invalid baud rate.",
    "012": "Invalid flow control setting.",
    "013": "Invalid parity setting.",
    "014": "Invalid stop bits setting.",
    "015": "Invalid data bits setting.",
    "016": "Invalid duplex setting.",
    "021": "Command not supported by this device.",
    "023": "Settings are locked.",
}
