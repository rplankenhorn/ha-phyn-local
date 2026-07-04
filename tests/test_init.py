"""Tests for integration setup, entity states, and coordinator failure handling."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.phyn_local.api import PhynConnectionError
from custom_components.phyn_local.const import DEFAULT_SCAN_INTERVAL, DOMAIN
from custom_components.phyn_local.coordinator import PhynCoordinator

from .conftest import TEST_DEVICE_NAME, TEST_HOST, TEST_SERIAL


async def setup_integration(hass: HomeAssistant) -> MockConfigEntry:
    """Add a mock config entry and set it up.

    Uses US customary units so sensor states stay in the device's native
    units (psi, degF, gal, gpm) instead of being metric-converted.
    """
    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=TEST_SERIAL,
        data={CONF_HOST: TEST_HOST},
        title=TEST_DEVICE_NAME,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_entry_creates_entities(hass: HomeAssistant, mock_client) -> None:
    """Setup succeeds with a mocked client and entities expose device data."""
    entry = await setup_integration(hass)
    assert entry.state is ConfigEntryState.LOADED

    all_states = {s.entity_id: s.state for s in hass.states.async_all()}
    # Entity ids derive from the device name "Phyn.Plus.999".
    assert all(eid.split(".", 1)[1].startswith("phyn_plus_999") for eid in all_states)

    pressure = hass.states.get("sensor.phyn_plus_999_water_pressure")
    assert pressure is not None
    assert float(pressure.state) == pytest.approx(66.235718)

    temperature = hass.states.get("sensor.phyn_plus_999_water_temperature")
    assert temperature is not None
    assert float(temperature.state) == pytest.approx(76.121094)

    # Idle negative raw flow is clamped to 0.
    flow = hass.states.get("sensor.phyn_plus_999_water_flow_rate")
    assert flow is not None
    assert float(flow.state) == 0.0

    consumption = hass.states.get("sensor.phyn_plus_999_total_water_consumption")
    assert consumption is not None
    assert float(consumption.state) == pytest.approx(99980.78068)

    flow_state = hass.states.get("sensor.phyn_plus_999_flow_state")
    assert flow_state is not None
    assert flow_state.state == "off"

    close_count = hass.states.get("sensor.phyn_plus_999_valve_close_count")
    assert close_count is not None
    assert int(close_count.state) == 357

    valve = hass.states.get("valve.phyn_plus_999")
    assert valve is not None
    assert valve.state == "open"

    leak = hass.states.get("binary_sensor.phyn_plus_999_leak_detected")
    assert leak is not None
    assert leak.state == "off"

    # Freeze risk is unknown when the device reports the "<unset>" sentinel.
    freeze = hass.states.get("binary_sensor.phyn_plus_999_freeze_risk")
    assert freeze is not None
    assert freeze.state == "unknown"


async def test_setup_entry_not_ready_on_connection_error(
    hass: HomeAssistant, mock_client
) -> None:
    """Setup retries when the device is unreachable."""
    mock_client.get_device_info.side_effect = PhynConnectionError("boom")

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=TEST_SERIAL,
        data={CONF_HOST: TEST_HOST},
        title=TEST_DEVICE_NAME,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_entities_unavailable_on_refresh_failure(
    hass: HomeAssistant, mock_client
) -> None:
    """Entities go unavailable when a refresh raises PhynConnectionError."""
    await setup_integration(hass)
    assert hass.states.get("sensor.phyn_plus_999_water_pressure").state != STATE_UNAVAILABLE

    mock_client.get_state.side_effect = PhynConnectionError("device went away")
    async_fire_time_changed(hass, dt_util.utcnow() + DEFAULT_SCAN_INTERVAL + timedelta(seconds=5))
    await hass.async_block_till_done()

    assert (
        hass.states.get("sensor.phyn_plus_999_water_pressure").state
        == STATE_UNAVAILABLE
    )
    assert hass.states.get("valve.phyn_plus_999").state == STATE_UNAVAILABLE

    # And recovers on the next successful refresh.
    mock_client.get_state.side_effect = None
    async_fire_time_changed(
        hass, dt_util.utcnow() + 2 * DEFAULT_SCAN_INTERVAL + timedelta(seconds=10)
    )
    await hass.async_block_till_done()
    assert (
        hass.states.get("sensor.phyn_plus_999_water_pressure").state
        != STATE_UNAVAILABLE
    )


async def test_coordinator_raises_update_failed(
    hass: HomeAssistant, mock_client, mock_device_info
) -> None:
    """The coordinator wraps client errors in UpdateFailed."""
    from custom_components.phyn_local.api import PhynLocalClient

    client = PhynLocalClient(TEST_HOST, session=None)
    coordinator = PhynCoordinator(hass, client, mock_device_info)

    mock_client.get_state.side_effect = PhynConnectionError("boom")
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_valve_open_close_services(hass: HomeAssistant, mock_client) -> None:
    """Valve services call the client with the right state and refresh."""
    await setup_integration(hass)

    await hass.services.async_call(
        "valve",
        "close_valve",
        {"entity_id": "valve.phyn_plus_999"},
        blocking=True,
    )
    mock_client.set_valve_state.assert_awaited_with(False)

    await hass.services.async_call(
        "valve",
        "open_valve",
        {"entity_id": "valve.phyn_plus_999"},
        blocking=True,
    )
    mock_client.set_valve_state.assert_awaited_with(True)
    # The follow-up coordinator refresh is debounced, so we don't assert on
    # get_state call counts here.


async def test_unload_entry(hass: HomeAssistant, mock_client) -> None:
    """The entry unloads cleanly."""
    entry = await setup_integration(hass)
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert (
        hass.states.get("sensor.phyn_plus_999_water_pressure").state
        == STATE_UNAVAILABLE
    )
