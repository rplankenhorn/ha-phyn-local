"""Config flow for the Phyn Local integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
except ImportError:  # pragma: no cover - fallback for older HA cores
    from homeassistant.components.dhcp import DhcpServiceInfo

from .api import PhynConnectionError, PhynDeviceInfo, PhynLocalClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


async def _get_device_info(hass: HomeAssistant, host: str) -> PhynDeviceInfo:
    """Validate we can talk to the device at host, returning its device info."""
    session = async_get_clientsession(hass)
    client = PhynLocalClient(host, session)
    return await client.get_device_info()


class PhynLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Phyn Local."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_host: str | None = None
        self._discovered_info: PhynDeviceInfo | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step, prompting for a host."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            try:
                info = await _get_device_info(self.hass, host)
            except PhynConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Unexpected error validating Phyn device at %s", host
                )
                errors["base"] = "unknown"
            else:
                if not info.serial_number:
                    errors["base"] = "cannot_connect"
                    return self.async_show_form(
                        step_id="user",
                        data_schema=STEP_USER_DATA_SCHEMA,
                        errors=errors,
                    )
                await self.async_set_unique_id(info.serial_number)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=info.device_name or "Phyn Plus",
                    data={CONF_HOST: host},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle discovery via DHCP."""
        host = discovery_info.ip

        try:
            info = await _get_device_info(self.hass, host)
        except PhynConnectionError:
            return self.async_abort(reason="cannot_connect")
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "Unexpected error validating discovered Phyn device at %s", host
            )
            return self.async_abort(reason="cannot_connect")

        if not info.serial_number:
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(info.serial_number)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._discovered_host = host
        self._discovered_info = info

        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a DHCP-discovered device before creating the entry."""
        assert self._discovered_host is not None
        assert self._discovered_info is not None

        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_info.device_name or "Phyn Plus",
                data={CONF_HOST: self._discovered_host},
            )

        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": self._discovered_info.device_name or "Phyn Plus",
                "host": self._discovered_host,
            },
        )
