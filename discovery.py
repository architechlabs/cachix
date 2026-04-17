"""UDP multicast discovery for Global Caché devices.

Global Caché devices broadcast an AMXB-formatted beacon on multicast
group 239.255.250.250 port 9131.  This module listens for those beacons
and returns a dictionary of discovered devices keyed by UUID.
"""
from __future__ import annotations

import asyncio
import logging
import re
import socket
import struct
from typing import Any

from .const import DISCOVERY_MULTICAST_GROUP, DISCOVERY_PORT

_LOGGER = logging.getLogger(__name__)

# Matches "<-Key=Value>" pairs inside an AMXB beacon.
_BEACON_RE = re.compile(r"<-(\w+)=([^>]*)>")


def parse_beacon(data: str) -> dict[str, str]:
    """Parse an AMXB beacon string into a ``{key: value}`` dictionary."""
    return dict(_BEACON_RE.findall(data))


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """Protocol handler that collects discovered device beacons."""

    def __init__(self, devices: dict[str, dict[str, Any]]) -> None:
        self._devices = devices

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Process a single incoming beacon datagram."""
        try:
            message = data.decode("ascii", errors="replace")
            if "AMXB" not in message:
                return

            info = parse_beacon(message)
            device_uuid = info.get("UUID", "")
            if not device_uuid:
                return

            host = addr[0]
            config_url = info.get("Config-URL", f"http://{host}")

            # Prefer the IP embedded in Config-URL (it may differ from sender).
            url_match = re.search(r"https?://([^:/]+)", config_url)
            if url_match:
                host = url_match.group(1)

            self._devices[device_uuid] = {
                "uuid": device_uuid,
                "host": host,
                "model": info.get("Model", "Unknown"),
                "make": info.get("Make", "Global Caché"),
                "revision": info.get("Revision", ""),
                "config_url": config_url,
                "sdk_class": info.get("SDKClass", ""),
                "status": info.get("Status", ""),
            }
            _LOGGER.debug(
                "Discovered Global Caché device %s (%s) at %s",
                device_uuid,
                info.get("Model", "?"),
                host,
            )
        except Exception:
            _LOGGER.debug("Failed to parse beacon from %s", addr, exc_info=True)

    def error_received(self, exc: Exception) -> None:  # pragma: no cover
        _LOGGER.debug("Discovery socket error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:  # pragma: no cover
        pass


class GlobalCacheDiscovery:
    """Discover Global Caché devices via UDP multicast beacon."""

    def __init__(self) -> None:
        self._devices: dict[str, dict[str, Any]] = {}

    async def discover(self, timeout: float = 5.0) -> dict[str, dict[str, Any]]:
        """Listen for beacons for *timeout* seconds and return found devices.

        Returns a dict keyed by device UUID.
        """
        self._devices = {}
        loop = asyncio.get_running_loop()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # SO_REUSEPORT is not available on Windows.
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

        sock.bind(("", DISCOVERY_PORT))

        # Join the multicast group on all interfaces.
        group = socket.inet_aton(DISCOVERY_MULTICAST_GROUP)
        mreq = struct.pack("4sL", group, socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.setblocking(False)

        transport, _ = await loop.create_datagram_endpoint(
            lambda: _DiscoveryProtocol(self._devices),
            sock=sock,
        )

        try:
            await asyncio.sleep(timeout)
        finally:
            transport.close()

        _LOGGER.info("Discovery finished – found %d device(s)", len(self._devices))
        return dict(self._devices)
