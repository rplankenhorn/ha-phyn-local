"""Local JNAP API client for the Phyn Plus."""

from __future__ import annotations

import asyncio
import base64
import json as json_module
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

from .const import (
    JNAP_ACTION_ATTRIBUTE_GET,
    JNAP_ACTION_GET_DEVICE_INFO,
    JNAP_ACTION_SET_SHUTOFF_VALVE_STATE,
    JNAP_PASSWORD,
    JNAP_USERNAME,
)

JNAP_TIMEOUT = aiohttp.ClientTimeout(total=10)


class PhynError(Exception):
    """Base error for the Phyn local API."""


class PhynConnectionError(PhynError):
    """Raised when the device cannot be reached or the request fails at the transport level."""


def _basic_auth_header() -> str:
    """Build the JNAP Basic auth header value from the fixed admin:admin credentials."""
    token = base64.b64encode(f"{JNAP_USERNAME}:{JNAP_PASSWORD}".encode()).decode()
    return f"Basic {token}"


@dataclass
class PhynDeviceInfo:
    """Static device identity, parsed from core/GetDeviceInfo."""

    device_id: Optional[str]  # MAC address
    serial_number: Optional[str]
    device_name: Optional[str]
    product_code: Optional[str]
    firmware_version: Optional[str]

    @classmethod
    def from_jnap(cls, output: dict[str, Any]) -> "PhynDeviceInfo":
        """Parse a core/GetDeviceInfo output dict defensively."""
        device_id = (
            output.get("deviceID")
            or output.get("macAddress")
            or output.get("hw_mac")
        )
        serial_number = (
            output.get("serialNumber")
            or output.get("serial")
            or output.get("hw_serial")
        )
        device_name = (
            output.get("deviceName")
            or output.get("modelDescription")
            or output.get("hw_name")
        )
        product_code = (
            output.get("modelNumber")
            or output.get("productCode")
            or output.get("hw_product")
        )
        firmware_version = (
            output.get("firmwareVersion")
            or output.get("fw_version")
            or output.get("fw_name")
        )
        return cls(
            device_id=device_id,
            serial_number=serial_number,
            device_name=device_name,
            product_code=product_code,
            firmware_version=str(firmware_version) if firmware_version is not None else None,
        )


def _as_float(value: Any) -> Optional[float]:
    """Best-effort float conversion, returning None for missing/unusable values."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    """Best-effort int conversion, returning None for missing/unusable values."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class PhynDeviceState:
    """Live device state, parsed from attribute/get output groups system/product/stats."""

    valve_open: bool
    pressure_psi: Optional[float] = None
    temperature_f: Optional[float] = None
    flow_gpm: Optional[float] = None
    flow_state: Optional[str] = None
    consumption_total_gal: Optional[float] = None
    sov_close_count: Optional[int] = None
    wifi_rssi: Optional[int] = None
    uptime_sec: Optional[int] = None
    net_connected: Optional[bool] = None
    wifi_connected: Optional[bool] = None
    leak_alert: bool = False
    freeze_risk: Optional[bool] = None

    @classmethod
    def from_jnap(cls, output: dict[str, Any]) -> "PhynDeviceState":
        """Parse an attribute/get {} output dict (groups: system, product, stats) defensively."""
        product = output.get("product") or {}
        stats = output.get("stats") or {}

        sov_state_str = product.get("sov_state_str")
        valve_open = sov_state_str == "opened"

        flow_gpm = _as_float(product.get("sensor_flow"))
        if flow_gpm is not None and flow_gpm < 0:
            flow_gpm = 0.0

        alert_state = product.get("alert_notifier_fp_state_str")
        leak_alert = alert_state is not None and alert_state != "normal"

        freeze_risk = _parse_freeze_risk(product.get("ml_oor_temperature_state"))

        return cls(
            valve_open=valve_open,
            pressure_psi=_as_float(product.get("sensor_pressure_1")),
            temperature_f=_as_float(product.get("sensor_temperature_1")),
            flow_gpm=flow_gpm,
            flow_state=product.get("sensor_flow_state"),
            consumption_total_gal=_as_float(product.get("consumption_total")),
            sov_close_count=_as_int(product.get("sov_close_count")),
            wifi_rssi=_as_int(stats.get("wifi_sta_rssi")),
            uptime_sec=_as_int(stats.get("device_up_time_sec")),
            net_connected=stats.get("net_connected"),
            wifi_connected=stats.get("wifi_connected"),
            leak_alert=leak_alert,
            freeze_risk=freeze_risk,
        )


def _parse_freeze_risk(raw: Any) -> Optional[bool]:
    """Interpret product.ml_oor_temperature_state.

    On the live device captured for this integration, this field was the
    sentinel string "<unset>" (the device only has the primary
    pressure/temperature sensor; a second sensor position exists in the
    firmware's schema but is unpopulated). There is no accompanying
    "..._state_str" field to key off of, unlike sov_state/sov_state_str.
    We treat "<unset>"/None as "unknown" (None) rather than guessing, and
    treat any resolved non-zero numeric state as an out-of-range/freeze
    condition (0 mirrors the "normal" convention used by the sibling
    ml_oor_pressure_state/ml_oor_flow_state fields on this device).
    """
    if raw is None or raw == "<unset>":
        return None
    state = _as_int(raw)
    if state is None:
        return None
    return state != 0


class PhynLocalClient:
    """Minimal async client for the Phyn Plus local JNAP API."""

    def __init__(self, host: str, session: aiohttp.ClientSession) -> None:
        self._host = host
        self._session = session

    @property
    def host(self) -> str:
        """Return the configured device host (IP or hostname)."""
        return self._host

    async def _jnap(self, action_urn: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST a JNAP action to the device and return its "output" dict."""
        url = f"http://{self._host}/JNAP/"
        headers = {
            "X-JNAP-Authorization": _basic_auth_header(),
            "X-JNAP-Action": action_urn,
            "Content-Type": "application/json",
        }
        try:
            async with self._session.post(
                url,
                headers=headers,
                data=json_module.dumps(body),
                timeout=JNAP_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise PhynConnectionError(f"Timed out connecting to {self._host}") from err
        except aiohttp.ClientError as err:
            raise PhynConnectionError(f"Error connecting to {self._host}: {err}") from err

        if not isinstance(data, dict) or data.get("result") != "OK":
            raise PhynError(f"JNAP request failed: {data}")

        return data.get("output", data)

    async def get_device_info(self) -> PhynDeviceInfo:
        """Fetch static device identity via core/GetDeviceInfo."""
        output = await self._jnap(JNAP_ACTION_GET_DEVICE_INFO, {})
        return PhynDeviceInfo.from_jnap(output)

    async def get_state(self) -> PhynDeviceState:
        """Fetch live device state via attribute/get.

        Critical: the body MUST be an empty dict. A non-empty body (e.g.
        specifying attribute names) returns an error from this firmware.
        """
        output = await self._jnap(JNAP_ACTION_ATTRIBUTE_GET, {})
        return PhynDeviceState.from_jnap(output)

    async def set_valve_state(self, open: bool) -> None:  # noqa: A002 - matches domain vocabulary
        """Open or close the shutoff valve. Actuates a real water valve."""
        state = "Open" if open else "Close"
        await self._jnap(JNAP_ACTION_SET_SHUTOFF_VALVE_STATE, {"state": state})
