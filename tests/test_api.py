"""Pure-unit tests for JNAP parsing in api.py (no Home Assistant, no network)."""

from __future__ import annotations

import copy

from custom_components.phyn_local.api import PhynDeviceInfo, PhynDeviceState


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
        assert PhynDeviceState.from_jnap(attribute_get_output).valve_open is True

    def test_valve_open_mapping_closed(self, attribute_get_output):
        attribute_get_output["product"]["sov_state_str"] = "closed"
        assert PhynDeviceState.from_jnap(attribute_get_output).valve_open is False

    def test_valve_open_mapping_missing(self, attribute_get_output):
        del attribute_get_output["product"]["sov_state_str"]
        # Unknown/missing valve state parses as not-open (defensive default).
        assert PhynDeviceState.from_jnap(attribute_get_output).valve_open is False

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
        for key in ("wifi_sta_rssi", "device_up_time_sec", "net_connected", "wifi_connected"):
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
        assert state.valve_open is False
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
