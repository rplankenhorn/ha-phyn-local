"""DataUpdateCoordinator and base entity for the Phyn Local integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from enum import StrEnum

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    PhynConnectionError,
    PhynDeviceInfo,
    PhynDeviceState,
    PhynError,
    PhynLocalClient,
    PhynValveState,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

OPEN_POLL_INTERVAL = 2.0
OPEN_VERIFY_TIMEOUT = 15.0


class _OpenVerificationResult(StrEnum):
    """Possible outcomes from one bounded open verification pass."""

    OPEN = "open"
    CLOSED = "closed"
    LEAK = "leak"
    NONFINAL = "nonfinal"
    NO_RESPONSE = "no_response"
    SUPERSEDED = "superseded"


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
        self._command_generation = 0
        self._command_lock = asyncio.Lock()
        self._partial_open_issue_id = (
            f"partial_open_{device_info.serial_number or 'device'}"
        )

    async def _async_update_data(self) -> PhynDeviceState:
        """Fetch the latest device state."""
        try:
            state = await self.client.get_state()
        except PhynConnectionError as err:
            raise UpdateFailed(f"Error communicating with device: {err}") from err
        except PhynError as err:
            raise UpdateFailed(f"Device reported an error: {err}") from err
        self._clear_partial_open_issue_if_recovered(state)
        return state

    async def async_open_valve(self) -> None:
        """Open, verify, and once retry a user-requested valve operation."""
        self._command_generation += 1
        generation = self._command_generation

        try:
            if not await self._async_send_valve_command(True, generation):
                return
        except PhynError as err:
            raise HomeAssistantError(
                f"Unable to send the open command to the Phyn valve: {err}"
            ) from err

        result = await self._async_verify_open(generation)
        if result is _OpenVerificationResult.OPEN:
            return
        if result is _OpenVerificationResult.SUPERSEDED:
            return
        if result is not _OpenVerificationResult.NONFINAL:
            self._raise_open_verification_error(result)

        # The explicit Open request left the valve in a non-final state. One
        # retry is allowed, but only if a newer command has not superseded it.
        try:
            if not await self._async_send_valve_command(True, generation):
                return
        except PhynError as err:
            self._mark_partial_open_failure()
            raise HomeAssistantError(
                f"Unable to retry the open command for the Phyn valve: {err}"
            ) from err

        result = await self._async_verify_open(generation)
        if result is _OpenVerificationResult.OPEN:
            return
        if result is _OpenVerificationResult.SUPERSEDED:
            return
        if result in (
            _OpenVerificationResult.NONFINAL,
            _OpenVerificationResult.NO_RESPONSE,
        ):
            self._mark_partial_open_failure()
        self._raise_open_verification_error(result)

    async def async_close_valve(self) -> None:
        """Close once and refresh, superseding any pending Open verification."""
        self._command_generation += 1
        generation = self._command_generation
        try:
            await self._async_send_valve_command(False, generation)
        except PhynError as err:
            raise HomeAssistantError(
                f"Unable to send the close command to the Phyn valve: {err}"
            ) from err
        await self._async_refresh_command_state()

    async def _async_send_valve_command(
        self, open_valve: bool, generation: int
    ) -> bool:
        """Serialize one write and skip it if a newer command won."""
        async with self._command_lock:
            if generation != self._command_generation:
                return False
            await self.client.set_valve_state(open_valve)
            return True

    async def _async_verify_open(self, generation: int) -> _OpenVerificationResult:
        """Poll until fully open or until one bounded verification pass ends."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + OPEN_VERIFY_TIMEOUT
        saw_nonfinal = False

        while True:
            if generation != self._command_generation:
                return _OpenVerificationResult.SUPERSEDED

            state = await self._async_refresh_command_state()
            if generation != self._command_generation:
                return _OpenVerificationResult.SUPERSEDED
            if state is not None:
                if state.valve_state is PhynValveState.OPEN:
                    return _OpenVerificationResult.OPEN
                if state.valve_state is PhynValveState.CLOSED:
                    return _OpenVerificationResult.CLOSED
                if state.leak_alert:
                    return _OpenVerificationResult.LEAK
                saw_nonfinal = True

            remaining = deadline - loop.time()
            if remaining <= 0:
                return (
                    _OpenVerificationResult.NONFINAL
                    if saw_nonfinal
                    else _OpenVerificationResult.NO_RESPONSE
                )
            await asyncio.sleep(min(OPEN_POLL_INTERVAL, remaining))

    async def _async_refresh_command_state(self) -> PhynDeviceState | None:
        """Fetch and publish a command verification state without raising."""
        try:
            state = await self.client.get_state()
        except PhynError as err:
            _LOGGER.debug("Unable to verify Phyn valve command: %s", err)
            return None
        self.async_set_updated_data(state)
        self._clear_partial_open_issue_if_recovered(state)
        return state

    def _mark_partial_open_failure(self) -> None:
        """Publish unknown valve state and create a persistent Repairs issue."""
        if self.data is not None:
            self.async_set_updated_data(
                replace(self.data, valve_state=PhynValveState.UNKNOWN)
            )

        serial = self.device_info.serial_number or "unknown"
        device_name = self.device_info.device_name or "Phyn Plus"
        issue_data: dict[str, str] = {"serial_number": serial}
        device = dr.async_get(self.hass).async_get_device(
            identifiers={(DOMAIN, serial)}
        )
        if device is not None:
            issue_data["device_id"] = device.id

        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._partial_open_issue_id,
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="partial_open",
            translation_placeholders={"device": device_name},
            data=issue_data,
        )

    def _clear_partial_open_issue_if_recovered(self, state: PhynDeviceState) -> None:
        """Clear the Repairs issue only after a poll confirms fully open."""
        if state.valve_state is PhynValveState.OPEN:
            ir.async_delete_issue(self.hass, DOMAIN, self._partial_open_issue_id)

    @staticmethod
    def _raise_open_verification_error(result: _OpenVerificationResult) -> None:
        """Raise a clear service error for a failed Open operation."""
        if result is _OpenVerificationResult.CLOSED:
            message = "The Phyn valve remained fully closed after the open command"
        elif result is _OpenVerificationResult.LEAK:
            message = (
                "The Phyn valve did not fully open and an active leak condition "
                "prevented an automatic retry"
            )
        elif result is _OpenVerificationResult.NO_RESPONSE:
            message = "Unable to verify the Phyn valve state after the open command"
        else:
            message = (
                "The Phyn valve did not reach the fully open position after one retry"
            )
        raise HomeAssistantError(message)


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
