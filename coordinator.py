"""DataUpdateCoordinator for the Cachix integration.

Polls firmware version, module listing, and relay/sensor states from the
Global Caché device at a configurable interval (default 30 s).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .client import ConnectionFailed, GlobalCacheClient
from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class CachixCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls a Global Caché device for status."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.client = GlobalCacheClient(
            host=entry.data[CONF_HOST],
            port=entry.data.get(CONF_PORT, DEFAULT_PORT),
            disconnect_callback=self._on_disconnect,
        )
        self._version: str | None = None
        self._modules: list[dict[str, Any]] = []
        self._port_states: dict[str, int] = {}
        self._last_command: str = ""

        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=scan_interval),
        )

    # ── Callbacks ────────────────────────────────────────────────────────

    def _on_disconnect(self) -> None:
        _LOGGER.warning(
            "Lost connection to Global Caché device at %s",
            self.entry.data.get(CONF_HOST),
        )

    # ── Connection helpers ───────────────────────────────────────────────

    async def async_connect(self) -> None:
        """Open the TCP connection."""
        await self.client.connect()

    async def async_disconnect(self) -> None:
        """Close the TCP connection."""
        await self.client.disconnect()

    # ── Polling ──────────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from the device."""
        # Ensure we have a live connection.
        if not self.client.connected:
            try:
                await self.client.connect()
            except ConnectionFailed as err:
                raise UpdateFailed(f"Cannot connect: {err}") from err

        try:
            # Firmware version
            version = await self.client.get_version()
            self._version = version

            # Module listing
            modules = await self.client.get_devices()
            self._modules = modules

            # Poll relay / sensor states
            port_states: dict[str, int] = {}
            for mod in modules:
                mod_id = mod.get("module", "")
                port_count = mod.get("port_count", 0)
                mod_type = mod.get("type", "").upper()
                if mod_type in ("RELAY", "SENSOR"):
                    for port_num in range(1, port_count + 1):
                        mp = f"{mod_id}:{port_num}"
                        try:
                            port_states[mp] = await self.client.get_state(mp)
                        except Exception:  # noqa: BLE001
                            _LOGGER.debug("Could not read state for %s", mp)
            self._port_states = port_states

            return {
                "version": version,
                "modules": modules,
                "port_states": port_states,
                "connected": True,
                "host": self.entry.data[CONF_HOST],
                "last_command": self._last_command,
            }

        except ConnectionFailed as err:
            raise UpdateFailed(f"Connection lost: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Error polling device: {err}") from err

    # ── Public helpers ───────────────────────────────────────────────────

    @property
    def version(self) -> str | None:
        return self._version

    @property
    def device_modules(self) -> list[dict[str, Any]]:
        return self._modules

    @property
    def port_states(self) -> dict[str, int]:
        return self._port_states

    @property
    def is_connected(self) -> bool:
        return self.client.connected

    def set_last_command(self, command: str) -> None:
        """Track the most-recently sent command for diagnostics."""
        self._last_command = command
