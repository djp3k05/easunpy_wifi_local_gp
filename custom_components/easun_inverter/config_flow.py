# File: custom_components/easun_inverter/config_flow.py

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

# Initial setup form
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(
            "inverter_ip",
            default=discover_device() or ""
        ): str,
        vol.Required(
            "local_ip",
            default=get_local_ip() or ""
        ): str,
        vol.Required(
            "model",
            default=MODEL_KEYS[0]
        ): vol.In(MODEL_KEYS),
        vol.Required(
            "scan_interval",
            default=DEFAULT_SCAN_INTERVAL
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
    }
)


class EasunInverterConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle the initial config flow for Easun Inverter."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        """Initial step: collect inverter_ip, local_ip, model & scan_interval."""
        errors: dict[str, str] = {}
        _LOGGER.debug("async_step_user user_input=%s", user_input)

        if user_input is not None:
            if not user_input["inverter_ip"] or not user_input["local_ip"]:
                errors["base"] = "missing_ip"
            else:
                _LOGGER.info("Creating Easun entry @ %s", user_input["inverter_ip"])
                return self.async_create_entry(
                    title=f"Easun @{user_input['inverter_ip']}",
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
        """Return the options flow handler (only scan_interval)."""
        return EasunInverterOptionsFlow(config_entry)


class EasunInverterOptionsFlow(config_entries.OptionsFlow):
    """Manage the options, i.e. only scan_interval."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry
        _LOGGER.debug("OptionsFlow init for %s", config_entry.entry_id)

    async def async_step_init(self, user_input=None):
        """Show or handle the scan_interval options form."""
        _LOGGER.debug("async_step_init user_input=%s", user_input)

        if user_input is not None:
            _LOGGER.info("Updating scan_interval to %s", user_input["scan_interval"])
            # This stores scan_interval in config_entry.options
            return self.async_create_entry(title="", options=user_input)

        # Pre-fill with existing scan_interval (options override data)
        current = self.config_entry.data
        opts = self.config_entry.options
        default_interval = opts.get("scan_interval", current.get("scan_interval", DEFAULT_SCAN_INTERVAL))

        schema = vol.Schema(
            {
                vol.Required(
                    "scan_interval",
                    default=default_interval
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600))
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
