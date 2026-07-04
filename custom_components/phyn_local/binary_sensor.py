"""Binary sensor entities for the Phyn Local integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PhynConfigEntry
from .api import PhynDeviceState
from .coordinator import PhynEntity


@dataclass
class PhynBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Phyn binary sensor entity."""

    is_on_fn: Callable[[PhynDeviceState], bool | None] = None


BINARY_SENSOR_DESCRIPTIONS: list[PhynBinarySensorEntityDescription] = [
    PhynBinarySensorEntityDescription(
        key="leak_alert",
        translation_key="leak_alert",
        device_class=BinarySensorDeviceClass.MOISTURE,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda state: state.leak_alert,
    ),
    PhynBinarySensorEntityDescription(
        key="freeze_risk",
        translation_key="freeze_risk",
        device_class=BinarySensorDeviceClass.COLD,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda state: state.freeze_risk,
    ),
    PhynBinarySensorEntityDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda state: _is_online(state),
    ),
]


def _is_online(state: PhynDeviceState) -> bool | None:
    """Determine if device is online based on network connectivity."""
    if state.net_connected is None and state.wifi_connected is None:
        return None
    # Online means both the Wi-Fi link and the upstream connection are up
    return (state.net_connected is True) and (state.wifi_connected is True)


class PhynBinarySensor(PhynEntity, BinarySensorEntity):
    """Binary sensor entity for Phyn Local integration."""

    entity_description: PhynBinarySensorEntityDescription

    def __init__(
        self, coordinator, description: PhynBinarySensorEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the binary sensor state."""
        return self.entity_description.is_on_fn(self.coordinator.data)


async def async_setup_entry(
    hass: HomeAssistant, entry: PhynConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up binary sensor entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            PhynBinarySensor(coordinator, description)
            for description in BINARY_SENSOR_DESCRIPTIONS
        ],
        update_before_add=True,
    )
