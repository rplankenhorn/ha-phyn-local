"""Local JNAP API client for the Phyn Plus."""

from __future__ import annotations

import asyncio
import base64
import json as json_module
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Optional

from .const import (
    JNAP_ACTION_ATTRIBUTE_GET,
    JNAP_ACTION_GET_DEVICE_INFO,
    JNAP_ACTION_SET_SHUTOFF_VALVE_STATE,
    JNAP_PASSWORD,
    JNAP_USERNAME,
)

JNAP_PORT = 80
JNAP_TIMEOUT = 10
MAX_HEADER_BYTES = 64 * 1024
MAX_BODY_BYTES = 1024 * 1024


class PhynError(Exception):
    """Base error for the Phyn local API."""


class PhynConnectionError(PhynError):
    """Raised when the device cannot be reached or the request fails at the transport level."""


class PhynValveState(StrEnum):
    """Normalized shutoff valve states reported by the device."""

    OPEN = "open"
    CLOSED = "closed"
    OPENING = "opening"
    CLOSING = "closing"
    UNKNOWN = "unknown"


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
            output.get("deviceID") or output.get("macAddress") or output.get("hw_mac")
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
            firmware_version=str(firmware_version)
            if firmware_version is not None
            else None,
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

    valve_state: PhynValveState
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
    pressure_oor: Optional[bool] = None
    flow_oor: Optional[bool] = None
    leak_test_running: Optional[bool] = None
    offline_leak_protection: Optional[bool] = None
    active_alerts: Optional[int] = None

    @classmethod
    def from_jnap(cls, output: dict[str, Any]) -> "PhynDeviceState":
        """Parse an attribute/get {} output dict (groups: system, product, stats) defensively."""
        product = output.get("product") or {}
        stats = output.get("stats") or {}

        valve_state = _parse_valve_state(
            product.get("sov_state_str"), product.get("sov_pic_state_str")
        )

        flow_gpm = _as_float(product.get("sensor_flow"))
        if flow_gpm is not None and flow_gpm < 0:
            flow_gpm = 0.0

        alert_state = product.get("alert_notifier_fp_state_str")
        leak_alert = alert_state is not None and alert_state != "normal"

        freeze_risk = _parse_freeze_risk(product.get("ml_oor_temperature_state"))

        return cls(
            valve_state=valve_state,
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
            pressure_oor=_parse_oor_state(product.get("ml_oor_pressure_state")),
            flow_oor=_parse_oor_state(product.get("ml_oor_flow_state")),
            leak_test_running=product.get("sov_plumbing_check_in_progress"),
            offline_leak_protection=product.get("ml_offline_leak_detector_enabled"),
            active_alerts=_as_int(product.get("alert_notifier_fp_active_alerts")),
        )

    @property
    def valve_open(self) -> Optional[bool]:
        """Return the terminal open state, or None for any non-final state."""
        if self.valve_state is PhynValveState.OPEN:
            return True
        if self.valve_state is PhynValveState.CLOSED:
            return False
        return None


def _normalize_valve_state(raw: Any) -> PhynValveState:
    """Normalize one firmware valve state string."""
    if not isinstance(raw, str):
        return PhynValveState.UNKNOWN

    normalized = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"open", "opened"}:
        return PhynValveState.OPEN
    if normalized in {"close", "closed"}:
        return PhynValveState.CLOSED
    if normalized == "opening":
        return PhynValveState.OPENING
    if normalized == "closing":
        return PhynValveState.CLOSING
    return PhynValveState.UNKNOWN


def _parse_valve_state(primary_raw: Any, pic_raw: Any) -> PhynValveState:
    """Resolve the primary and PIC valve state fields conservatively.

    Some firmware omits the PIC state. In that case a recognized primary
    state is useful on its own. When both fields are present they must agree;
    disagreement and unrecognized/partial values are non-final and unknown.
    """
    primary = _normalize_valve_state(primary_raw)
    if pic_raw is None:
        return primary

    pic = _normalize_valve_state(pic_raw)
    if primary is pic and primary is not PhynValveState.UNKNOWN:
        return primary
    return PhynValveState.UNKNOWN


def _parse_oor_state(raw: Any) -> Optional[bool]:
    """Interpret a product.ml_oor_*_state out-of-range detector field.

    These integers use 0 = "normal"; any non-zero value signals an
    out-of-range condition. The specific non-zero encodings (e.g. high vs
    low) are not yet known, so we collapse to a single boolean here. The
    sentinel string "<unset>"/None means the detector position is
    unpopulated on this device, which we surface as "unknown" (None)
    rather than guessing.
    """
    if raw is None or raw == "<unset>":
        return None
    state = _as_int(raw)
    if state is None:
        return None
    return state != 0


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
    return _parse_oor_state(raw)


class PhynLocalClient:
    """Minimal async client for the Phyn Plus local JNAP API."""

    def __init__(self, host: str) -> None:
        self._host = host

    @property
    def host(self) -> str:
        """Return the configured device host (IP or hostname)."""
        return self._host

    async def _jnap(self, action_urn: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST a JNAP action to the device and return its "output" dict."""
        request_body = json_module.dumps(body, separators=(",", ":")).encode()
        request = (
            "POST /JNAP/ HTTP/1.1\r\n"
            f"Host: {self._host}\r\n"
            f"X-JNAP-Authorization: {_basic_auth_header()}\r\n"
            f"X-JNAP-Action: {action_urn}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(request_body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii") + request_body

        writer: asyncio.StreamWriter | None = None
        try:
            async with asyncio.timeout(JNAP_TIMEOUT):
                reader, writer = await asyncio.open_connection(self._host, JNAP_PORT)
                writer.write(request)
                await writer.drain()
                header_block = await reader.readuntil(b"\r\n\r\n")
                status, content_length = _parse_response_headers(header_block)
                response_body = await reader.readexactly(content_length)
        except asyncio.TimeoutError as err:
            raise PhynConnectionError(f"Timed out connecting to {self._host}") from err
        except (OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as err:
            raise PhynConnectionError(
                f"Error connecting to {self._host}: {err}"
            ) from err
        finally:
            if writer is not None:
                writer.close()

        if not 200 <= status < 300:
            raise PhynError(f"JNAP HTTP request failed with status {status}")

        try:
            data = json_module.loads(response_body)
        except (UnicodeDecodeError, json_module.JSONDecodeError) as err:
            raise PhynConnectionError(
                f"Invalid JSON response from {self._host}"
            ) from err

        if not isinstance(data, dict) or data.get("result") != "OK":
            raise PhynError(f"JNAP request failed: {data}")

        output = data.get("output", data)
        if not isinstance(output, dict):
            raise PhynError(f"JNAP response contained invalid output: {data}")
        return output

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


def _parse_response_headers(header_block: bytes) -> tuple[int, int]:
    """Parse the first response status and Content-Length leniently."""
    if len(header_block) > MAX_HEADER_BYTES:
        raise PhynConnectionError("JNAP response headers are too large")

    try:
        lines = header_block[:-4].decode("latin-1").split("\r\n")
        version, status_text, *_ = lines[0].split(" ")
        status = int(status_text)
    except (IndexError, ValueError) as err:
        raise PhynConnectionError("Invalid JNAP HTTP status line") from err

    if not version.startswith("HTTP/") or not 100 <= status <= 599:
        raise PhynConnectionError("Invalid JNAP HTTP status line")

    lengths: list[str] = []
    for line in lines[1:]:
        if ":" not in line:
            # Be lenient only for the PP2 firmware debug print known to leak
            # into attribute/get response headers.
            if line.startswith("GetDataFromDaemon:"):
                continue
            raise PhynConnectionError("Malformed JNAP HTTP response header")
        name, value = line.split(":", 1)
        if name.strip().lower() == "content-length":
            lengths.append(value.strip())

    if len(lengths) != 1:
        raise PhynConnectionError(
            "JNAP response has missing or duplicate Content-Length"
        )
    if not lengths[0].isascii() or not lengths[0].isdigit():
        raise PhynConnectionError("JNAP response has invalid Content-Length")
    content_length = int(lengths[0])
    if content_length < 0 or content_length > MAX_BODY_BYTES:
        raise PhynConnectionError("JNAP response body length is invalid or too large")
    return status, content_length
