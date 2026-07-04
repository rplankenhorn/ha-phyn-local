"""Valve entity for the Phyn Local integration."""

from __future__ import annotations

from homeassistant.components.valve import ValveDeviceClass, ValveEntity, ValveEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PhynConfigEntry
from .coordinator import PhynEntity


class PhynMainValve(PhynEntity, ValveEntity):
    """Main shutoff valve entity for Phyn Local integration."""

    _attr_device_class = ValveDeviceClass.WATER
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    _attr_reports_position = False
    _attr_name = None

    @property
    def is_closed(self) -> bool:
        """Return True if the valve is closed."""
        return not self.coordinator.data.valve_open

    async def async_open_valve(self) -> None:
        """Open the valve."""
        await self.coordinator.client.set_valve_state(True)
        await self.coordinator.async_request_refresh()

    async def async_close_valve(self) -> None:
        """Close the valve."""
        await self.coordinator.client.set_valve_state(False)
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant, entry: PhynConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up valve entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [PhynMainValve(coordinator, "valve")],
        update_before_add=True,
    )
