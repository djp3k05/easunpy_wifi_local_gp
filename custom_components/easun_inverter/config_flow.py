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
    """Handle a config flow for Easun Inverter."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        """Initial setup: ask for inverter_ip, local_ip, model, scan_interval."""
        _LOGGER.debug("async_step_user, user_input=%s", user_input)
        errors: dict[str, str] = {}

        if user_input is not None:
            inv_ip = user_input.get("inverter_ip", "")
            loc_ip = user_input.get("local_ip", "")
            if not inv_ip or not loc_ip:
                errors["base"] = "missing_ip"
                _LOGGER.debug("Missing inverter_ip or local_ip")
            else:
                _LOGGER.info("Creating config entry for Easun @ %s", inv_ip)
                return self.async_create_entry(
                    title=f"Easun @{inv_ip}",
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
        """Get the options flow for this integration."""
        return EasunInverterOptionsFlow(config_entry)


class EasunInverterOptionsFlow(config_entries.OptionsFlow):
    """Handle updates to the integration options."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry
        _LOGGER.debug("Initialized OptionsFlow for entry %s", config_entry.entry_id)

    async def async_step_init(self, user_input=None):
        """Show and handle the options form."""
        _LOGGER.debug("async_step_init, user_input=%s", user_input)
        errors: dict[str, str] = {}

        try:
            if user_input is not None:
                _LOGGER.info("Updating options: %s", user_input)
                # Return options only; HA merges into config_entry.options
                return self.async_create_entry(title="", options=user_input)

            # Pre-fill form from existing data + options
            data = self.config_entry.data
            opts = self.config_entry.options

            schema = vol.Schema(
                {
                    vol.Required(
                        "inverter_ip", default=data.get("inverter_ip", "")
                    ): str,
                    vol.Required(
                        "local_ip", default=data.get("local_ip", "")
                    ): str,
                    vol.Required(
                        "model", default=data.get("model", MODEL_KEYS[0])
                    ): vol.In(MODEL_KEYS),
                    vol.Required(
                        "scan_interval",
                        default=opts.get(
                            "scan_interval", data.get("scan_interval", DEFAULT_SCAN_INTERVAL)
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
                }
            )

            return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

        except Exception as exc:
            _LOGGER.exception("Error in OptionsFlow")
            errors["base"] = "unknown"
            # Fallback to minimal schema on error
            return self.async_show_form(
                step_id="init",
                data_schema=STEP_USER_DATA_SCHEMA,
                errors=errors,
            )
