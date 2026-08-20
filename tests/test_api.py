"""Pure-unit tests for JNAP parsing in api.py (no Home Assistant, no network)."""

from __future__ import annotations

import asyncio
import copy
import json

import pytest

from custom_components.phyn_local import api
from custom_components.phyn_local.api import (
    MAX_BODY_BYTES,
    PhynConnectionError,
    PhynDeviceInfo,
    PhynDeviceState,
    PhynError,
    PhynLocalClient,
    PhynValveState,
)


def _http_response(
    body: bytes,
    *,
    status: str = "200 OK",
    extra_headers: tuple[str, ...] = (),
    content_length: str | None = None,
) -> bytes:
    """Build a raw HTTP response for the socket transport tests."""
    headers = [f"HTTP/1.1 {status}", *extra_headers]
    if content_length is not None:
        headers.append(f"Content-Length: {content_length}")
    return ("\r\n".join(headers) + "\r\n\r\n").encode() + body


async def _serve_response(monkeypatch, response: bytes) -> PhynLocalClient:
    """Serve one raw response and point the client at its loopback port."""

    async def handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(api, "JNAP_PORT", port)
    monkeypatch.setattr(api, "JNAP_TIMEOUT", 1)
    client = PhynLocalClient("127.0.0.1")
    client._test_server = server  # type: ignore[attr-defined]
    return client


async def _close_test_server(client: PhynLocalClient) -> None:
    """Close the loopback server attached by _serve_response."""
    server = client._test_server  # type: ignore[attr-defined]
    server.close()
    await server.wait_closed()


class TestJnapSocketTransport:
    """Raw HTTP framing behavior for PhynLocalClient._jnap."""

    pytestmark = pytest.mark.usefixtures("socket_enabled")

    async def test_normal_response(self, monkeypatch):
        body = json.dumps({"result": "OK", "output": {"value": 1}}).encode()
        client = await _serve_response(
            monkeypatch, _http_response(body, content_length=str(len(body)))
        )
        try:
            assert await client._jnap("test/action", {}) == {"value": 1}
        finally:
            await _close_test_server(client)

    async def test_debug_header_is_tolerated(self, monkeypatch):
        body = b'{"result":"OK","output":{"value":2}}'
        client = await _serve_response(
            monkeypatch,
            _http_response(
                body,
                extra_headers=(
                    "GetDataFromDaemon: Thread 25736 calling WASP_Init",
                    "Content-Type: application/json",
                ),
                content_length=str(len(body)),
            ),
        )
        try:
            assert await client._jnap("test/action", {}) == {"value": 2}
        finally:
            await _close_test_server(client)

    async def test_appended_second_response_is_ignored(self, monkeypatch):
        body = b'{"result":"OK","output":{"value":3}}'
        trailing = _http_response(b"{}", content_length="2")
        client = await _serve_response(
            monkeypatch,
            _http_response(body, content_length=str(len(body))) + trailing,
        )
        try:
            assert await client._jnap("test/action", {}) == {"value": 3}
        finally:
            await _close_test_server(client)

    @pytest.mark.parametrize(
        "response",
        [
            _http_response(b"{}"),
            _http_response(b"{}", content_length="nope"),
            _http_response(b"{}", content_length="2", extra_headers=("Broken",)),
            _http_response(b"", content_length=str(MAX_BODY_BYTES + 1)),
        ],
        ids=("missing-length", "invalid-length", "malformed-header", "oversized"),
    )
    async def test_invalid_framing(self, monkeypatch, response):
        client = await _serve_response(monkeypatch, response)
        try:
            with pytest.raises(PhynConnectionError):
                await client._jnap("test/action", {})
        finally:
            await _close_test_server(client)

    async def test_truncated_body(self, monkeypatch):
        client = await _serve_response(
            monkeypatch, _http_response(b"{}", content_length="20")
        )
        try:
            with pytest.raises(PhynConnectionError):
                await client._jnap("test/action", {})
        finally:
            await _close_test_server(client)

    async def test_invalid_json(self, monkeypatch):
        body = b"not json"
        client = await _serve_response(
            monkeypatch, _http_response(body, content_length=str(len(body)))
        )
        try:
            with pytest.raises(PhynConnectionError, match="Invalid JSON"):
                await client._jnap("test/action", {})
        finally:
            await _close_test_server(client)

    async def test_http_error(self, monkeypatch):
        body = b'{"result":"error"}'
        client = await _serve_response(
            monkeypatch,
            _http_response(body, status="500 Error", content_length=str(len(body))),
        )
        try:
            with pytest.raises(PhynError, match="status 500"):
                await client._jnap("test/action", {})
        finally:
            await _close_test_server(client)

    async def test_jnap_error_envelope(self, monkeypatch):
        body = b'{"result":"_ErrorInvalidInput","error":"bad"}'
        client = await _serve_response(
            monkeypatch, _http_response(body, content_length=str(len(body)))
        )
        try:
            with pytest.raises(PhynError, match="JNAP request failed"):
                await client._jnap("test/action", {})
        finally:
            await _close_test_server(client)

    async def test_timeout(self, monkeypatch):
        async def timeout(*args, **kwargs):
            raise asyncio.TimeoutError

        monkeypatch.setattr(asyncio, "open_connection", timeout)
        with pytest.raises(PhynConnectionError, match="Timed out"):
            await PhynLocalClient("127.0.0.1")._jnap("test/action", {})

    async def test_refused_connection(self, monkeypatch):
        async def refused(*args, **kwargs):
            raise ConnectionRefusedError("refused")

        monkeypatch.setattr(asyncio, "open_connection", refused)
        with pytest.raises(PhynConnectionError, match="Error connecting"):
            await PhynLocalClient("127.0.0.1")._jnap("test/action", {})


class TestDeviceInfoParsing:
    """PhynDeviceInfo.from_jnap."""

    def test_getdeviceinfo_keys(self, device_info_output):
        info = PhynDeviceInfo.from_jnap(device_info_output)
        assert info.device_id == "AA:BB:CC:DD:EE:FF"
        assert info.serial_number == "TESTSERIAL001"
        assert info.device_name == "Phyn.Plus.999"
        assert info.product_code == "PP2"
        assert info.firmware_version == "test_fw_1"

    def test_hw_fallback_keys(self):
        info = PhynDeviceInfo.from_jnap(
            {
                "hw_mac": "AA:BB:CC:DD:EE:FF",
                "hw_serial": "TESTSERIAL001",
                "hw_name": "Phyn.Plus.999",
                "hw_product": "PP2",
                "fw_version": 40900023,
            }
        )
        assert info.device_id == "AA:BB:CC:DD:EE:FF"
        assert info.serial_number == "TESTSERIAL001"
        assert info.device_name == "Phyn.Plus.999"
        assert info.product_code == "PP2"
        # Numeric firmware versions are stringified.
        assert info.firmware_version == "40900023"

    def test_empty_output(self):
        info = PhynDeviceInfo.from_jnap({})
        assert info.device_id is None
        assert info.serial_number is None
        assert info.device_name is None
        assert info.product_code is None
        assert info.firmware_version is None


class TestDeviceStateParsing:
    """PhynDeviceState.from_jnap."""

    def test_full_dump(self, attribute_get_output):
        state = PhynDeviceState.from_jnap(attribute_get_output)
        assert state.valve_open is True
        assert state.pressure_psi == 66.235718
        assert state.temperature_f == 76.121094
        assert state.flow_state == "off"
        assert state.consumption_total_gal == 99980.780680
        assert state.sov_close_count == 357
        assert state.wifi_rssi == -50
        assert state.uptime_sec == 310
        assert state.net_connected is True
        assert state.wifi_connected is True

    def test_valve_open_mapping_opened(self, attribute_get_output):
        attribute_get_output["product"]["sov_state_str"] = "opened"
        state = PhynDeviceState.from_jnap(attribute_get_output)
        assert state.valve_state is PhynValveState.OPEN
        assert state.valve_open is True

    def test_valve_open_mapping_closed(self, attribute_get_output):
        attribute_get_output["product"]["sov_state_str"] = "closed"
        attribute_get_output["product"]["sov_pic_state_str"] = "closed"
        state = PhynDeviceState.from_jnap(attribute_get_output)
        assert state.valve_state is PhynValveState.CLOSED
        assert state.valve_open is False

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("opening", PhynValveState.OPENING), ("closing", PhynValveState.CLOSING)],
    )
    def test_valve_transitional_states(self, attribute_get_output, raw, expected):
        attribute_get_output["product"]["sov_state_str"] = raw
        attribute_get_output["product"]["sov_pic_state_str"] = raw
        state = PhynDeviceState.from_jnap(attribute_get_output)
        assert state.valve_state is expected
        assert state.valve_open is None

    def test_valve_partial_state_is_unknown(self, attribute_get_output):
        attribute_get_output["product"]["sov_state_str"] = "partial_open"
        attribute_get_output["product"]["sov_pic_state_str"] = "partial_open"
        assert (
            PhynDeviceState.from_jnap(attribute_get_output).valve_state
            is PhynValveState.UNKNOWN
        )

    def test_valve_pic_disagreement_is_unknown(self, attribute_get_output):
        attribute_get_output["product"]["sov_state_str"] = "opened"
        attribute_get_output["product"]["sov_pic_state_str"] = "closed"
        assert (
            PhynDeviceState.from_jnap(attribute_get_output).valve_state
            is PhynValveState.UNKNOWN
        )

    def test_valve_primary_only_firmware(self, attribute_get_output):
        del attribute_get_output["product"]["sov_pic_state_str"]
        assert (
            PhynDeviceState.from_jnap(attribute_get_output).valve_state
            is PhynValveState.OPEN
        )

    def test_valve_open_mapping_missing(self, attribute_get_output):
        del attribute_get_output["product"]["sov_state_str"]
        state = PhynDeviceState.from_jnap(attribute_get_output)
        assert state.valve_state is PhynValveState.UNKNOWN
        assert state.valve_open is None

    def test_negative_flow_clamped_to_zero(self, attribute_get_output):
        # The real device idles at a slightly negative flow reading.
        assert attribute_get_output["product"]["sensor_flow"] < 0
        state = PhynDeviceState.from_jnap(attribute_get_output)
        assert state.flow_gpm == 0.0

    def test_positive_flow_passthrough(self, attribute_get_output):
        attribute_get_output["product"]["sensor_flow"] = 1.25
        state = PhynDeviceState.from_jnap(attribute_get_output)
        assert state.flow_gpm == 1.25

    def test_missing_fields_are_none(self, attribute_get_output):
        output = copy.deepcopy(attribute_get_output)
        for key in (
            "sensor_pressure_1",
            "sensor_temperature_1",
            "sensor_flow",
            "sensor_flow_state",
            "consumption_total",
            "sov_close_count",
        ):
            del output["product"][key]
        for key in (
            "wifi_sta_rssi",
            "device_up_time_sec",
            "net_connected",
            "wifi_connected",
        ):
            del output["stats"][key]
        state = PhynDeviceState.from_jnap(output)
        assert state.pressure_psi is None
        assert state.temperature_f is None
        assert state.flow_gpm is None
        assert state.flow_state is None
        assert state.consumption_total_gal is None
        assert state.sov_close_count is None
        assert state.wifi_rssi is None
        assert state.uptime_sec is None
        assert state.net_connected is None
        assert state.wifi_connected is None

    def test_unset_sentinel_values_are_none(self, attribute_get_output):
        attribute_get_output["product"]["sensor_pressure_1"] = "<unset>"
        attribute_get_output["product"]["sensor_flow"] = "<unset>"
        state = PhynDeviceState.from_jnap(attribute_get_output)
        assert state.pressure_psi is None
        assert state.flow_gpm is None

    def test_empty_output_groups(self):
        state = PhynDeviceState.from_jnap({})
        assert state.valve_state is PhynValveState.UNKNOWN
        assert state.valve_open is None
        assert state.pressure_psi is None
        assert state.leak_alert is False
        assert state.freeze_risk is None

    def test_leak_alert_normal(self, attribute_get_output):
        attribute_get_output["product"]["alert_notifier_fp_state_str"] = "normal"
        assert PhynDeviceState.from_jnap(attribute_get_output).leak_alert is False

    def test_leak_alert_not_normal(self, attribute_get_output):
        attribute_get_output["product"]["alert_notifier_fp_state_str"] = "warning"
        assert PhynDeviceState.from_jnap(attribute_get_output).leak_alert is True

    def test_leak_alert_missing(self, attribute_get_output):
        del attribute_get_output["product"]["alert_notifier_fp_state_str"]
        assert PhynDeviceState.from_jnap(attribute_get_output).leak_alert is False

    def test_freeze_risk_unset_sentinel_is_none(self, attribute_get_output):
        assert attribute_get_output["product"]["ml_oor_temperature_state"] == "<unset>"
        assert PhynDeviceState.from_jnap(attribute_get_output).freeze_risk is None

    def test_freeze_risk_zero_is_false(self, attribute_get_output):
        attribute_get_output["product"]["ml_oor_temperature_state"] = 0
        assert PhynDeviceState.from_jnap(attribute_get_output).freeze_risk is False

    def test_freeze_risk_nonzero_is_true(self, attribute_get_output):
        attribute_get_output["product"]["ml_oor_temperature_state"] = 2
        assert PhynDeviceState.from_jnap(attribute_get_output).freeze_risk is True

    def test_freeze_risk_missing_is_none(self, attribute_get_output):
        del attribute_get_output["product"]["ml_oor_temperature_state"]
        assert PhynDeviceState.from_jnap(attribute_get_output).freeze_risk is None

    def test_pressure_oor_zero_is_false(self, attribute_get_output):
        assert attribute_get_output["product"]["ml_oor_pressure_state"] == 0
        assert PhynDeviceState.from_jnap(attribute_get_output).pressure_oor is False

    def test_pressure_oor_nonzero_is_true(self, attribute_get_output):
        attribute_get_output["product"]["ml_oor_pressure_state"] = 1
        assert PhynDeviceState.from_jnap(attribute_get_output).pressure_oor is True

    def test_pressure_oor_unset_is_none(self, attribute_get_output):
        attribute_get_output["product"]["ml_oor_pressure_state"] = "<unset>"
        assert PhynDeviceState.from_jnap(attribute_get_output).pressure_oor is None

    def test_pressure_oor_missing_is_none(self, attribute_get_output):
        del attribute_get_output["product"]["ml_oor_pressure_state"]
        assert PhynDeviceState.from_jnap(attribute_get_output).pressure_oor is None

    def test_flow_oor_zero_is_false(self, attribute_get_output):
        assert attribute_get_output["product"]["ml_oor_flow_state"] == 0
        assert PhynDeviceState.from_jnap(attribute_get_output).flow_oor is False

    def test_flow_oor_nonzero_is_true(self, attribute_get_output):
        attribute_get_output["product"]["ml_oor_flow_state"] = 3
        assert PhynDeviceState.from_jnap(attribute_get_output).flow_oor is True

    def test_flow_oor_missing_is_none(self, attribute_get_output):
        del attribute_get_output["product"]["ml_oor_flow_state"]
        assert PhynDeviceState.from_jnap(attribute_get_output).flow_oor is None

    def test_leak_test_running_passthrough(self, attribute_get_output):
        attribute_get_output["product"]["sov_plumbing_check_in_progress"] = True
        assert PhynDeviceState.from_jnap(attribute_get_output).leak_test_running is True
        attribute_get_output["product"]["sov_plumbing_check_in_progress"] = False
        assert (
            PhynDeviceState.from_jnap(attribute_get_output).leak_test_running is False
        )

    def test_leak_test_running_missing_is_none(self, attribute_get_output):
        del attribute_get_output["product"]["sov_plumbing_check_in_progress"]
        assert PhynDeviceState.from_jnap(attribute_get_output).leak_test_running is None

    def test_offline_leak_protection_passthrough(self, attribute_get_output):
        assert (
            PhynDeviceState.from_jnap(attribute_get_output).offline_leak_protection
            is True
        )
        attribute_get_output["product"]["ml_offline_leak_detector_enabled"] = False
        assert (
            PhynDeviceState.from_jnap(attribute_get_output).offline_leak_protection
            is False
        )

    def test_offline_leak_protection_missing_is_none(self, attribute_get_output):
        del attribute_get_output["product"]["ml_offline_leak_detector_enabled"]
        assert (
            PhynDeviceState.from_jnap(attribute_get_output).offline_leak_protection
            is None
        )

    def test_active_alerts_int(self, attribute_get_output):
        attribute_get_output["product"]["alert_notifier_fp_active_alerts"] = 2
        assert PhynDeviceState.from_jnap(attribute_get_output).active_alerts == 2

    def test_active_alerts_missing_is_none(self, attribute_get_output):
        del attribute_get_output["product"]["alert_notifier_fp_active_alerts"]
        assert PhynDeviceState.from_jnap(attribute_get_output).active_alerts is None
