"""Sensor entities for the Phyn Local integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import PhynConfigEntry
from .api import PhynDeviceState
from .coordinator import PhynEntity


@dataclass
class PhynSensorEntityDescription(SensorEntityDescription):
    """Describes a Phyn sensor entity."""

    value_fn: Callable[[PhynDeviceState], StateType] = None


SENSOR_DESCRIPTIONS: list[PhynSensorEntityDescription] = [
    PhynSensorEntityDescription(
        key="pressure",
        translation_key="pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PSI,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.pressure_psi,
    ),
    PhynSensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.temperature_f,
    ),
    PhynSensorEntityDescription(
        key="flow_rate",
        translation_key="flow_rate",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.GALLONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.flow_gpm,
    ),
    PhynSensorEntityDescription(
        key="consumption_total",
        translation_key="consumption_total",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda state: state.consumption_total_gal,
    ),
    PhynSensorEntityDescription(
        key="flow_state",
        translation_key="flow_state",
        device_class=SensorDeviceClass.ENUM,
        options=["off", "low", "medium", "high"],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: _map_flow_state(state.flow_state),
    ),
    PhynSensorEntityDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: state.wifi_rssi,
    ),
    PhynSensorEntityDescription(
        key="valve_close_count",
        translation_key="valve_close_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.sov_close_count,
    ),
    PhynSensorEntityDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: state.uptime_sec,
    ),
]


def _map_flow_state(raw_value: str | None) -> str | None:
    """Map raw flow state value to enum option, lowercased."""
    if raw_value is None:
        return None
    mapped = raw_value.lower()
    # Normalize "med" to "medium" if needed
    if mapped == "med":
        mapped = "medium"
    valid_options = ["off", "low", "medium", "high"]
    return mapped if mapped in valid_options else None


class PhynSensor(PhynEntity, SensorEntity):
    """Sensor entity for Phyn Local integration."""

    entity_description: PhynSensorEntityDescription

    def __init__(
        self, coordinator, description: PhynSensorEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)


async def async_setup_entry(
    hass: HomeAssistant, entry: PhynConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensor entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [PhynSensor(coordinator, description) for description in SENSOR_DESCRIPTIONS],
        update_before_add=True,
    )
