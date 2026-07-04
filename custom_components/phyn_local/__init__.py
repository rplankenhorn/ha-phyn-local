"""The Phyn Local integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PhynConnectionError, PhynDeviceInfo, PhynLocalClient
from .coordinator import PhynCoordinator

PLATFORMS: list[Platform] = [Platform.VALVE, Platform.SENSOR, Platform.BINARY_SENSOR]


@dataclass
class PhynData:
    """Runtime data stored on the config entry."""

    client: PhynLocalClient
    coordinator: PhynCoordinator
    device_info: PhynDeviceInfo


# Typing alias for a Phyn Local config entry with typed runtime_data.
# (Equivalent to the PEP 695 `type PhynConfigEntry = ConfigEntry[PhynData]`
# statement, spelled so it also compiles on pre-3.12 interpreters.)
PhynConfigEntry = ConfigEntry[PhynData]


async def async_setup_entry(hass: HomeAssistant, entry: PhynConfigEntry) -> bool:
    """Set up Phyn Local from a config entry."""
    host = entry.data[CONF_HOST]
    session = async_get_clientsession(hass)
    client = PhynLocalClient(host, session)

    try:
        device_info = await client.get_device_info()
    except PhynConnectionError as err:
        raise ConfigEntryNotReady(
            f"Unable to connect to Phyn device at {host}"
        ) from err

    coordinator = PhynCoordinator(hass, client, device_info)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = PhynData(
        client=client, coordinator=coordinator, device_info=device_info
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: PhynConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
