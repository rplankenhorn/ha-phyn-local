"""Shared fixtures for the Phyn Local test suite.

All device data here is fake/anonymized. The attribute/get fixture mirrors the
field names of a real Phyn Plus firmware 4.9.x dump but every identifying
value (serial, MAC, SSID, IPs) is replaced with test placeholders.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.phyn_local.api import PhynDeviceInfo, PhynDeviceState

TEST_HOST = "192.0.2.10"
TEST_SERIAL = "TESTSERIAL001"
TEST_MAC = "AA:BB:CC:DD:EE:FF"
TEST_DEVICE_NAME = "Phyn.Plus.999"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


@pytest.fixture
def device_info_output() -> dict:
    """Mock JNAP core/GetDeviceInfo output dict."""
    return {
        "deviceID": TEST_MAC,
        "deviceName": TEST_DEVICE_NAME,
        "productCode": "PP2",
        "serialNumber": TEST_SERIAL,
        "firmwareVersion": "test_fw_1",
    }


@pytest.fixture
def attribute_get_output() -> dict:
    """Mock JNAP attribute/get output dict.

    Mirrors the system/product/stats group structure and field names of a
    real device dump, with anonymized identifying values.
    """
    return {
        "system": {
            "app_version": "<unset>",
            "cloud_api_url": "api.phyn.com",
            "fw_image_current": "image_a",
            "fw_name": "Phyn_WaterDevice_release_4_9_0_23_locked",
            "fw_version": 40900023,
            "hw_description": "Phyn Plus Smart Water Assistant + Shutoff",
            "hw_id": "AABBCCDDEEFF",
            "hw_mac": TEST_MAC,
            "hw_manufacturer": "Phyn LLC",
            "hw_model": "PHYPF001",
            "hw_name": TEST_DEVICE_NAME,
            "hw_platform": 2,
            "hw_product": "PP2",
            "hw_serial": TEST_SERIAL,
            "hw_version": "0",
            "led_state": "connected",
            "localization_time_zone": "America/New_York",
            "wifi_ap_ssid": TEST_DEVICE_NAME,
            "wifi_country": "US",
            "wifi_sta_channel": 6,
            "wifi_sta_security": "WPA2-Personal",
            "wifi_sta_ssid": "TestNetwork-Devices",
        },
        "product": {
            "alert_notifier_fp_state": 0,
            "alert_notifier_fp_state_str": "normal",
            "alert_notifier_fp_alert_id": "<unset>",
            "alert_notifier_fp_active_alerts": 0,
            "cloud_time_zone": "America/New_York",
            "consumption_total": 99980.780680,
            "demo_mode": False,
            "external_ip": "203.0.113.5",
            "ml_oor_flow_state": 0,
            "ml_oor_pressure_state": 0,
            "ml_oor_pressure_win_average": 66.286819,
            "ml_oor_temperature_state": "<unset>",
            "ml_oor_temperature_win_average": "<unset>",
            "partner_name": "phyn",
            "pic_fw_version": "0.143",
            "product_has_button": True,
            "product_has_flow_sensor": True,
            "product_has_pressure_temperature_sensor_1": True,
            "product_has_pressure_temperature_sensor_2": False,
            "product_has_sov": True,
            "sensor_flow": -0.010442,
            "sensor_flow_state": "off",
            "sensor_pressure_1": 66.235718,
            "sensor_temperature_1": 76.121094,
            "sov_close_count": 357,
            "sov_pic_state_str": "opened",
            "sov_plumbing_check_in_progress": False,
            "sov_state": 1,
            "sov_state_str": "opened",
            "weather_data_temperature_f": "<unset>",
        },
        "stats": {
            "ble_connected": False,
            "ble_state_str": "power_off",
            "connection_state_str": "iot_streaming",
            "device_mem_free_kb": 101076,
            "device_reboot_count": 27,
            "device_up_time_sec": 310,
            "ethernet_connected": False,
            "ethernet_ip": "<unset>",
            "net_connected": True,
            "sov_pic_state": 1,
            "wifi_connected": True,
            "wifi_rssi_avg": -50,
            "wifi_sta_ip": TEST_HOST,
            "wifi_sta_rssi": -50,
        },
    }


@pytest.fixture
def mock_device_info(device_info_output) -> PhynDeviceInfo:
    """Parsed PhynDeviceInfo matching device_info_output."""
    return PhynDeviceInfo.from_jnap(device_info_output)


@pytest.fixture
def mock_device_state(attribute_get_output) -> PhynDeviceState:
    """Parsed PhynDeviceState matching attribute_get_output."""
    return PhynDeviceState.from_jnap(attribute_get_output)


@pytest.fixture
def mock_client(mock_device_info, mock_device_state):
    """Patch PhynLocalClient network methods with AsyncMocks.

    Yields an object with .get_device_info / .get_state / .set_valve_state
    AsyncMocks so tests can adjust return values or side effects.
    """
    with (
        patch(
            "custom_components.phyn_local.api.PhynLocalClient.get_device_info",
            new_callable=AsyncMock,
            return_value=mock_device_info,
        ) as get_device_info,
        patch(
            "custom_components.phyn_local.api.PhynLocalClient.get_state",
            new_callable=AsyncMock,
            return_value=mock_device_state,
        ) as get_state,
        patch(
            "custom_components.phyn_local.api.PhynLocalClient.set_valve_state",
            new_callable=AsyncMock,
        ) as set_valve_state,
    ):

        class MockedClient:
            pass

        mocked = MockedClient()
        mocked.get_device_info = get_device_info
        mocked.get_state = get_state
        mocked.set_valve_state = set_valve_state
        yield mocked
