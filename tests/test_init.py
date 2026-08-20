"""Tests for integration setup, entity states, and coordinator failure handling."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, call

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.phyn_local import coordinator as coordinator_module
from custom_components.phyn_local.api import PhynConnectionError, PhynValveState
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


@pytest.mark.parametrize(
    ("valve_state", "expected"),
    [
        (PhynValveState.OPENING, "opening"),
        (PhynValveState.CLOSING, "closing"),
        (PhynValveState.UNKNOWN, "unknown"),
    ],
)
async def test_valve_exposes_nonterminal_states(
    hass: HomeAssistant, mock_client, mock_device_state, valve_state, expected
) -> None:
    """The valve entity exposes transitions and uncertainty honestly."""
    mock_client.get_state.return_value = replace(
        mock_device_state, valve_state=valve_state
    )
    await setup_integration(hass)
    assert hass.states.get("valve.phyn_plus_999").state == expected


async def test_wan_offline_does_not_make_entities_unavailable(
    hass: HomeAssistant, mock_client, mock_device_state
) -> None:
    """Successful LAN polling remains available without upstream WAN access."""
    mock_client.get_state.return_value = replace(
        mock_device_state, net_connected=False, wifi_connected=True
    )
    await setup_integration(hass)
    pressure = hass.states.get("sensor.phyn_plus_999_water_pressure")
    valve = hass.states.get("valve.phyn_plus_999")
    assert pressure.state != STATE_UNAVAILABLE
    assert valve.state == "open"


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
    assert (
        hass.states.get("sensor.phyn_plus_999_water_pressure").state
        != STATE_UNAVAILABLE
    )

    mock_client.get_state.side_effect = PhynConnectionError("device went away")
    async_fire_time_changed(
        hass, dt_util.utcnow() + DEFAULT_SCAN_INTERVAL + timedelta(seconds=5)
    )
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

    client = PhynLocalClient(TEST_HOST)
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


async def test_open_succeeds_without_retry(
    hass: HomeAssistant, mock_client, mock_device_state
) -> None:
    """A fully-open first verification does not send a second command."""
    entry = await setup_integration(hass)
    mock_client.set_valve_state.reset_mock()
    mock_client.get_state.reset_mock(return_value=True, side_effect=True)
    mock_client.get_state.return_value = mock_device_state

    await entry.runtime_data.coordinator.async_open_valve()

    mock_client.set_valve_state.assert_awaited_once_with(True)
    mock_client.get_state.assert_awaited_once()


async def test_partial_open_retries_once_then_succeeds(
    hass: HomeAssistant, mock_client, mock_device_state, monkeypatch
) -> None:
    """One partial verification causes one retry, followed by success."""
    entry = await setup_integration(hass)
    coordinator = entry.runtime_data.coordinator
    partial = replace(mock_device_state, valve_state=PhynValveState.UNKNOWN)
    mock_client.set_valve_state.reset_mock()
    mock_client.get_state.reset_mock(return_value=True, side_effect=True)
    mock_client.get_state.side_effect = [partial, mock_device_state]
    monkeypatch.setattr(coordinator_module, "OPEN_VERIFY_TIMEOUT", 0)

    await coordinator.async_open_valve()

    assert mock_client.set_valve_state.await_args_list == [call(True), call(True)]


async def test_persistent_partial_open_raises_and_creates_repair(
    hass: HomeAssistant, mock_client, mock_device_state, monkeypatch
) -> None:
    """A partial state after the bounded retry becomes unknown and a Repair."""
    entry = await setup_integration(hass)
    coordinator = entry.runtime_data.coordinator
    partial = replace(mock_device_state, valve_state=PhynValveState.UNKNOWN)
    mock_client.set_valve_state.reset_mock()
    mock_client.get_state.reset_mock(return_value=True, side_effect=True)
    mock_client.get_state.return_value = partial
    monkeypatch.setattr(coordinator_module, "OPEN_VERIFY_TIMEOUT", 0)

    with pytest.raises(HomeAssistantError, match="after one retry"):
        await coordinator.async_open_valve()

    assert mock_client.set_valve_state.await_args_list == [call(True), call(True)]
    assert coordinator.data.valve_state is PhynValveState.UNKNOWN
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"partial_open_{TEST_SERIAL}")
    assert issue is not None
    assert issue.is_persistent is True
    assert issue.translation_key == "partial_open"


@pytest.mark.parametrize(
    ("state", "message"),
    [
        (PhynValveState.CLOSED, "remained fully closed"),
        (PhynValveState.UNKNOWN, "active leak"),
    ],
)
async def test_closed_or_leak_does_not_retry(
    hass: HomeAssistant,
    mock_client,
    mock_device_state,
    state,
    message,
) -> None:
    """A confirmed close or active leak prevents an automatic Open retry."""
    entry = await setup_integration(hass)
    reported = replace(
        mock_device_state,
        valve_state=state,
        leak_alert=message == "active leak",
    )
    mock_client.set_valve_state.reset_mock()
    mock_client.get_state.reset_mock(return_value=True, side_effect=True)
    mock_client.get_state.return_value = reported

    with pytest.raises(HomeAssistantError, match=message):
        await entry.runtime_data.coordinator.async_open_valve()

    mock_client.set_valve_state.assert_awaited_once_with(True)


async def test_close_supersedes_pending_open_verification(
    hass: HomeAssistant, mock_client, mock_device_state, monkeypatch
) -> None:
    """A newer Close prevents an older Open task from issuing its retry."""
    entry = await setup_integration(hass)
    coordinator = entry.runtime_data.coordinator
    partial = replace(mock_device_state, valve_state=PhynValveState.UNKNOWN)
    closed = replace(mock_device_state, valve_state=PhynValveState.CLOSED)
    first_open_poll = asyncio.Event()
    refresh_count = 0

    async def refresh_state():
        nonlocal refresh_count
        refresh_count += 1
        if refresh_count == 1:
            first_open_poll.set()
            return partial
        return closed

    monkeypatch.setattr(coordinator_module, "OPEN_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(
        coordinator,
        "_async_refresh_command_state",
        AsyncMock(side_effect=refresh_state),
    )
    mock_client.set_valve_state.reset_mock()

    open_task = asyncio.create_task(coordinator.async_open_valve())
    await first_open_poll.wait()
    await coordinator.async_close_valve()
    await open_task

    assert mock_client.set_valve_state.await_args_list == [call(True), call(False)]


async def test_later_open_poll_clears_partial_open_repair(
    hass: HomeAssistant, mock_client, mock_device_state, monkeypatch
) -> None:
    """A later fully-open passive poll removes the persistent Repair."""
    entry = await setup_integration(hass)
    coordinator = entry.runtime_data.coordinator
    partial = replace(mock_device_state, valve_state=PhynValveState.UNKNOWN)
    mock_client.get_state.reset_mock(return_value=True, side_effect=True)
    mock_client.get_state.return_value = partial
    monkeypatch.setattr(coordinator_module, "OPEN_VERIFY_TIMEOUT", 0)

    with pytest.raises(HomeAssistantError):
        await coordinator.async_open_valve()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"partial_open_{TEST_SERIAL}")
        is not None
    )

    mock_client.get_state.return_value = mock_device_state
    await coordinator.async_refresh()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"partial_open_{TEST_SERIAL}")
        is None
    )


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
