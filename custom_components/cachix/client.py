"""Asynchronous TCP client for Global Caché devices.

Implements the Global Caché Unified TCP API v1.1 with:
  • Persistent connection on port 4998
  • Automatic reconnection with exponential back-off
  • Serialised command queue (asyncio.Lock)
  • Full response parsing (single-line & multi-line)
  • Convenience wrappers for every major API command
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .const import (
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    GC_ERROR_CODES,
    IR_SEND_TIMEOUT,
    RECONNECT_MAX_DELAY,
    RECONNECT_MIN_DELAY,
    RESP_BUSY_IR,
    RESP_ERROR,
)

_LOGGER = logging.getLogger(__name__)


# ── Exceptions ───────────────────────────────────────────────────────────────

class GlobalCacheError(Exception):
    """Base exception for Global Caché communication errors."""


class ConnectionFailed(GlobalCacheError):
    """Could not open or maintain a TCP connection."""


class CommandError(GlobalCacheError):
    """The device returned an error response."""

    def __init__(self, raw: str) -> None:
        self.raw = raw
        code = ""
        # ERR formats: "ERR_1:1,008" or "ERR 008"
        for token in raw.replace("_", ",").replace(" ", ",").split(","):
            if token.isdigit() and len(token) == 3:
                code = token
                break
        self.code = code
        human = GC_ERROR_CODES.get(code, "Unknown error")
        super().__init__(f"{raw} – {human}")


class DeviceBusy(GlobalCacheError):
    """The IR port is currently transmitting (busyir)."""


# ── Client ───────────────────────────────────────────────────────────────────

class GlobalCacheClient:
    """Async TCP client for Global Caché / iTach / GC-100 devices."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
        disconnect_callback: Any | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._disconnect_callback = disconnect_callback
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._connected = False
        self._reconnect_task: asyncio.Task[None] | None = None
        self._reconnect_delay: float = RECONNECT_MIN_DELAY
        self._closing = False

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def connected(self) -> bool:
        return self._connected

    # ── Connection Management ────────────────────────────────────────────

    async def connect(self) -> None:
        """Open a TCP connection to the device."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._timeout,
            )
            self._connected = True
            self._closing = False
            self._reconnect_delay = RECONNECT_MIN_DELAY
            _LOGGER.info(
                "Connected to Global Caché device at %s:%s",
                self._host,
                self._port,
            )
        except (OSError, asyncio.TimeoutError) as err:
            self._connected = False
            raise ConnectionFailed(
                f"Cannot connect to {self._host}:{self._port}: {err}"
            ) from err

    async def disconnect(self) -> None:
        """Gracefully close the connection."""
        self._closing = True
        self._connected = False
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self._writer = None
            self._reader = None
        _LOGGER.debug(
            "Disconnected from Global Caché device at %s:%s",
            self._host,
            self._port,
        )

    async def reconnect(self) -> None:
        """Reconnect with exponential back-off until success or close."""
        while not self._closing:
            try:
                await self.connect()
                _LOGGER.info("Reconnected to %s:%s", self._host, self._port)
                return
            except ConnectionFailed:
                _LOGGER.warning(
                    "Reconnect to %s:%s failed – retrying in %ss",
                    self._host,
                    self._port,
                    self._reconnect_delay,
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    RECONNECT_MAX_DELAY,
                )

    def _schedule_reconnect(self) -> None:
        """Schedule a background reconnection task."""
        if self._closing:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._connected = False
        self._reconnect_task = asyncio.create_task(self.reconnect())
        if self._disconnect_callback:
            self._disconnect_callback()

    # ── Low-Level I/O ────────────────────────────────────────────────────

    async def _read_line(self) -> str:
        """Read a single CR-terminated response line from the device."""
        assert self._reader is not None  # noqa: S101
        data = await self._reader.readuntil(b"\r")
        line = data.decode("ascii", errors="replace").rstrip("\r\n")
        # Consume a stray LF that some firmware revisions append
        if self._reader._buffer and self._reader._buffer[:1] == b"\n":  # type: ignore[attr-defined]
            await self._reader.readexactly(1)
        return line

    async def _read_multiline(self) -> str:
        """Read a multi-line response terminated by ``endlistdevices``."""
        lines: list[str] = []
        while True:
            line = await asyncio.wait_for(self._read_line(), timeout=self._timeout)
            lines.append(line)
            _LOGGER.debug("Recv (multi) from %s: %s", self._host, line)
            if line.strip().lower() == "endlistdevices":
                break
        return "\n".join(lines)

    async def _send_and_receive(self, command: str, timeout: float | None = None) -> str:
        """Write *command*\\r and return the parsed response (under lock)."""
        timeout = timeout or self._timeout
        assert self._writer is not None  # noqa: S101
        assert self._reader is not None  # noqa: S101
        try:
            self._writer.write(f"{command}\r".encode("ascii"))
            await self._writer.drain()
            _LOGGER.debug("Sent to %s: %s", self._host, command)

            # Multi-line response for getdevices
            if command.strip().lower() == "getdevices":
                return await self._read_multiline()

            response = await asyncio.wait_for(self._read_line(), timeout=timeout)
            _LOGGER.debug("Recv from %s: %s", self._host, response)

            if response.startswith(RESP_ERROR):
                raise CommandError(response)
            if response.startswith(RESP_BUSY_IR):
                raise DeviceBusy(f"IR port busy: {response}")

            return response

        except (OSError, asyncio.IncompleteReadError) as err:
            _LOGGER.error("Connection lost to %s: %s", self._host, err)
            self._schedule_reconnect()
            raise ConnectionFailed(f"Connection lost: {err}") from err
        except asyncio.TimeoutError as err:
            _LOGGER.warning("Timeout awaiting response from %s", self._host)
            raise CommandError("Timeout waiting for device response") from err

    # ── Public API ───────────────────────────────────────────────────────

    async def send_command(self, command: str, timeout: float | None = None) -> str:
        """Send an arbitrary command (serialised via lock)."""
        if not self._connected or not self._writer or not self._reader:
            raise ConnectionFailed("Not connected to device")
        async with self._lock:
            return await self._send_and_receive(command, timeout=timeout)

    # ── Convenience Wrappers ─────────────────────────────────────────────

    async def get_version(self) -> str:
        """Return the firmware version string."""
        resp = await self.send_command("getversion")
        # Response: "version,<ver>"
        return resp.split(",", 1)[1] if "," in resp else resp

    async def get_devices(self) -> list[dict[str, Any]]:
        """Return a list of modules reported by ``getdevices``."""
        resp = await self.send_command("getdevices")
        devices: list[dict[str, Any]] = []
        for line in resp.split("\n"):
            line = line.strip()
            if not line.startswith("device,"):
                continue
            parts = line.split(",")
            if len(parts) >= 3:
                devices.append(
                    {
                        "module": parts[1],
                        "port_count": int(parts[2]) if parts[2].isdigit() else 0,
                        "type": parts[3] if len(parts) > 3 else "UNKNOWN",
                    }
                )
        return devices

    async def get_state(self, module_port: str) -> int:
        """Get the binary state of a relay or sensor port."""
        resp = await self.send_command(f"getstate,{module_port}")
        # Response: "state,<module>:<port>,<0|1>"
        parts = resp.split(",")
        if len(parts) >= 3 and parts[2].strip().isdigit():
            return int(parts[2].strip())
        return -1

    async def set_state(self, module_port: str, value: int) -> str:
        """Set the binary state of a relay port (0 or 1)."""
        return await self.send_command(f"setstate,{module_port},{value}")

    async def send_ir(self, command: str) -> str:
        """Send an IR command (prepends ``sendir,`` if missing)."""
        if not command.lower().startswith("sendir"):
            command = f"sendir,{command}"
        try:
            return await self.send_command(command, timeout=IR_SEND_TIMEOUT)
        except CommandError as e:
            # Log additional context for debugging Control4 issues
            if "008" in str(e):
                _LOGGER.warning(
                    "Invalid pulse data error (ERR_1:1,008) for command: %s. "
                    "This may indicate the device is controlled by Control4 or "
                    "the IR code format is incorrect. Check that IR codes are "
                    "comma-separated pulse pairs (e.g. '347,173,22,22,22,65').",
                    command
                )
            elif "023" in str(e):
                _LOGGER.warning(
                    "Settings locked error (ERR_023) for command: %s. "
                    "This device appears to be locked, possibly by Control4. "
                    "You may need to unlock the device or configure Control4 "
                    "to allow external access.",
                    command
                )
            raise

    async def stop_ir(self, module_port: str) -> str:
        """Abort an in-progress IR transmission."""
        return await self.send_command(f"stopir,{module_port}")

    async def start_ir_learner(self) -> str:
        """Activate the IR learner and return the initial response."""
        return await self.send_command("get_IRL")

    async def stop_ir_learner(self) -> str:
        """Deactivate the IR learner."""
        return await self.send_command("stop_IRL")

    async def send_serial(self, module_port: str, data: str) -> str:
        """Send data out of a serial port."""
        return await self.send_command(f"set_SERIAL,{module_port},{data}")

    async def get_serial(self, module_port: str) -> str:
        """Read buffered serial data from a port."""
        return await self.send_command(f"get_SERIAL,{module_port}")

    async def get_lock_status(self) -> str:
        """Check if the device is locked (Control4 compatibility)."""
        try:
            return await self.send_command("getlock")
        except CommandError:
            # getlock may not be supported on all devices
            return "unknown"

    async def unlock_device(self, password: str = "") -> str:
        """Attempt to unlock the device (if supported)."""
        try:
            if password:
                return await self.send_command(f"unlock,{password}")
            else:
                return await self.send_command("unlock")
        except CommandError as e:
            _LOGGER.warning("Failed to unlock device: %s", e)
            raise
