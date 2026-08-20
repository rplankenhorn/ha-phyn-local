"""Valve entity for the Phyn Local integration."""

from __future__ import annotations

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PhynConfigEntry
from .api import PhynValveState
from .coordinator import PhynEntity


class PhynMainValve(PhynEntity, ValveEntity):
    """Main shutoff valve entity for Phyn Local integration."""

    _attr_device_class = ValveDeviceClass.WATER
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    _attr_reports_position = False
    _attr_name = None

    @property
    def is_closed(self) -> bool | None:
        """Return the terminal valve position, or unknown if non-final."""
        valve_open = self.coordinator.data.valve_open
        return None if valve_open is None else not valve_open

    @property
    def is_opening(self) -> bool:
        """Return whether the device reports that the valve is opening."""
        return self.coordinator.data.valve_state is PhynValveState.OPENING

    @property
    def is_closing(self) -> bool:
        """Return whether the device reports that the valve is closing."""
        return self.coordinator.data.valve_state is PhynValveState.CLOSING

    async def async_open_valve(self) -> None:
        """Open the valve."""
        await self.coordinator.async_open_valve()

    async def async_close_valve(self) -> None:
        """Close the valve."""
        await self.coordinator.async_close_valve()


async def async_setup_entry(
    hass: HomeAssistant, entry: PhynConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up valve entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [PhynMainValve(coordinator, "valve")],
        update_before_add=True,
    )
