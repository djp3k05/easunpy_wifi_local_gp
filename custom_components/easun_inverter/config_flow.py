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
        vol.Optional(
            "scan_interval", default=DEFAULT_SCAN_INTERVAL
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
    }
)


class EasunInverterConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle a config flow for Easun Inverter."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        """Initial setup: ask for inverter and local IP, model, scan interval."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input["inverter_ip"] or not user_input["local_ip"]:
                errors["base"] = "missing_ip"
            else:
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
        """Return options flow handler."""
        return EasunInverterOptionsFlow(config_entry)


class EasunInverterOptionsFlow(config_entries.OptionsFlow):
    """Handle updates to the integration options."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Show and handle the options form."""
        if user_input is not None:
            # Save only in options; HA will merge with .data
            return self.async_create_entry(title="", options=user_input)

        # Pre-fill form from existing data/opts
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
