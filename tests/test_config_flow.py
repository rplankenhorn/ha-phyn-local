"""Tests for the Phyn Local config flow."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from custom_components.phyn_local.api import PhynConnectionError, PhynDeviceInfo
from custom_components.phyn_local.const import DOMAIN

from .conftest import TEST_DEVICE_NAME, TEST_HOST, TEST_SERIAL


async def test_user_flow_happy_path(hass: HomeAssistant, mock_client) -> None:
    """A user-entered host creates an entry keyed by serial number."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: TEST_HOST}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TEST_DEVICE_NAME
    assert result["data"] == {CONF_HOST: TEST_HOST}
    assert result["result"].unique_id == TEST_SERIAL


async def test_user_flow_cannot_connect(hass: HomeAssistant, mock_client) -> None:
    """A connection error shows the form again with cannot_connect."""
    mock_client.get_device_info.side_effect = PhynConnectionError("boom")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: TEST_HOST}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    # Recovers once the device is reachable again.
    mock_client.get_device_info.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: TEST_HOST}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_missing_serial_errors(
    hass: HomeAssistant, mock_client
) -> None:
    """A device that reports no serial number errors with cannot_connect."""
    mock_client.get_device_info.return_value = PhynDeviceInfo(
        device_id="AA:BB:CC:DD:EE:FF",
        serial_number=None,
        device_name=TEST_DEVICE_NAME,
        product_code="PP2",
        firmware_version="test_fw_1",
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: TEST_HOST}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_duplicate_serial_aborts(
    hass: HomeAssistant, mock_client
) -> None:
    """A second user flow for the same serial aborts as already_configured."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=TEST_SERIAL,
        data={CONF_HOST: TEST_HOST},
        title=TEST_DEVICE_NAME,
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.99"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_dhcp_flow_confirm_creates_entry(
    hass: HomeAssistant, mock_client
) -> None:
    """DHCP discovery of a new device shows the confirm step, then creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(
            ip=TEST_HOST,
            hostname="phyn-plus-999",
            macaddress="aabbccddeeff",
        ),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TEST_DEVICE_NAME
    assert result["data"] == {CONF_HOST: TEST_HOST}
    assert result["result"].unique_id == TEST_SERIAL


async def test_dhcp_flow_updates_host_of_existing_entry(
    hass: HomeAssistant, mock_client
) -> None:
    """DHCP discovery of an already-configured serial updates CONF_HOST and aborts."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=TEST_SERIAL,
        data={CONF_HOST: "192.0.2.50"},
        title=TEST_DEVICE_NAME,
    )
    entry.add_to_hass(hass)

    new_ip = "192.0.2.77"
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(
            ip=new_ip,
            hostname="phyn-plus-999",
            macaddress="aabbccddeeff",
        ),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == new_ip


async def test_dhcp_flow_cannot_connect_aborts(
    hass: HomeAssistant, mock_client
) -> None:
    """DHCP discovery aborts when the device cannot be validated."""
    mock_client.get_device_info.side_effect = PhynConnectionError("boom")

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(
            ip=TEST_HOST,
            hostname="phyn-plus-999",
            macaddress="aabbccddeeff",
        ),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_dhcp_flow_missing_serial_aborts(
    hass: HomeAssistant, mock_client
) -> None:
    """DHCP discovery aborts when the device reports no serial number."""
    mock_client.get_device_info.return_value = PhynDeviceInfo(
        device_id="AA:BB:CC:DD:EE:FF",
        serial_number=None,
        device_name=TEST_DEVICE_NAME,
        product_code="PP2",
        firmware_version="test_fw_1",
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(
            ip=TEST_HOST,
            hostname="phyn-plus-999",
            macaddress="aabbccddeeff",
        ),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
