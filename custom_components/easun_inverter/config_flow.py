"""Config flow for Easun Inverter integration."""
from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from easunpy.discover import discover_device
from easunpy.utils import get_local_ip
from easunpy.models import MODEL_CONFIGS

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL = 30
MODEL_KEYS = list(MODEL_CONFIGS.keys())

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(
            "inverter_ip", default=discover_device() or ""
        ): str,
        vol.Required(
            "local_ip", default=get_local_ip() or ""
        ): str,
        vol.Required(
            "model", default=MODEL_KEYS[0]
        ): vol.In(MODEL_KEYS),
        vol.Required(
            "scan_interval", default=DEFAULT_SCAN_INTERVAL
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
    }
)


class EasunInverterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration of the Easun Inverter."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        """Show the setup form and create the config entry."""
        errors: dict[str, str] = {}
        _LOGGER.debug("async_step_user: %s", user_input)

        if user_input is not None:
            inv_ip = user_input["inverter_ip"]
            loc_ip = user_input["local_ip"]
            if not inv_ip or not loc_ip:
                errors["base"] = "missing_ip"
            else:
                _LOGGER.info("Creating Easun Inverter entry for %s", inv_ip)
                return self.async_create_entry(
                    title=f"Easun @ {inv_ip}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return EasunInverterOptionsFlow(config_entry)


class EasunInverterOptionsFlow(config_entries.OptionsFlow):
    """Handle changes to the integration options."""

    def __init__(self, config_entry):
        self.config_entry = config_entry
        _LOGGER.debug("OptionsFlow init for %s", config_entry.entry_id)

    async def async_step_init(self, user_input=None):
        """Show the options form and save the updated options."""
        _LOGGER.debug("async_step_init: %s", user_input)

        if user_input is not None:
            _LOGGER.info("Updating Easun options: %s", user_input)
            return self.async_create_entry(title="", options=user_input)

        # Pre‐populate form with existing data + options
        data = self.config_entry.data
        opts = self.config_entry.options

        schema = vol.Schema(
            {
                vol.Required(
                    "inverter_ip", default=data["inverter_ip"]
                ): str,
                vol.Required(
                    "local_ip", default=data["local_ip"]
                ): str,
                vol.Required(
                    "model", default=data["model"]
                ): vol.In(MODEL_KEYS),
                vol.Required(
                    "scan_interval",
                    default=opts.get("scan_interval", data.get("scan_interval", DEFAULT_SCAN_INTERVAL))
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
