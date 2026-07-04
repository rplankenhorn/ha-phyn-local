"""DataUpdateCoordinator and base entity for the Phyn Local integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import PhynConnectionError, PhynDeviceInfo, PhynDeviceState, PhynError, PhynLocalClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class PhynCoordinator(DataUpdateCoordinator[PhynDeviceState]):
    """Coordinator that polls attribute/get once per cycle for a Phyn Plus device."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: PhynLocalClient,
        device_info: PhynDeviceInfo,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self.device_info = device_info

    async def _async_update_data(self) -> PhynDeviceState:
        """Fetch the latest device state."""
        try:
            return await self.client.get_state()
        except PhynConnectionError as err:
            raise UpdateFailed(f"Error communicating with device: {err}") from err
        except PhynError as err:
            raise UpdateFailed(f"Device reported an error: {err}") from err


class PhynEntity(CoordinatorEntity[PhynCoordinator]):
    """Base entity for Phyn Local entities, wiring up shared DeviceInfo."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PhynCoordinator, key: str) -> None:
        super().__init__(coordinator)
        info = coordinator.device_info
        self._key = key
        self._attr_unique_id = f"{info.serial_number}_{key}"

        connections = set()
        if info.device_id:
            connections.add((dr.CONNECTION_NETWORK_MAC, dr.format_mac(info.device_id)))

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, info.serial_number)},
            connections=connections,
            manufacturer="Phyn",
            model="Phyn Plus",
            name=info.device_name or "Phyn Plus",
            sw_version=info.firmware_version,
            configuration_url=f"http://{coordinator.client.host}",
        )
