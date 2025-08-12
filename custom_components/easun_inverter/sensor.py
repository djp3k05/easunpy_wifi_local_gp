# File: custom_components/easun_inverter/sensor.py

"""Support for Easun Inverter sensors."""
from datetime import datetime, timedelta
import logging
import asyncio

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import (
    UnitOfPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfFrequency,
    UnitOfApparentPower,
    UnitOfEnergy,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_time_interval

from . import DOMAIN  # Import DOMAIN from __init__.py
from easunpy.async_isolar import AsyncISolar
from easunpy.async_ascii_isolar import AsyncAsciiISolar

_LOGGER = logging.getLogger(__name__)

ASCII_MODELS = {"EASUN_SMW_8K", "EASUN_SMW_11K"}

# ... [rest of imports and DataCollector, EasunSensor, RegisterScanSensor, DeviceScanSensor unchanged] ...

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Easun Inverter sensors."""
    _LOGGER.debug("Setting up Easun Inverter sensors")
    
    scan_interval = config_entry.options.get(
        "scan_interval",
        config_entry.data.get("scan_interval", 30)
    )
    
    inverter_ip = config_entry.data.get("inverter_ip")
    local_ip = config_entry.data.get("local_ip")
    model = config_entry.data.get("model")
    
    _LOGGER.info(f"Setting up sensors with model: {model}")
    
    if not inverter_ip or not local_ip:
        _LOGGER.error("Missing inverter IP or local IP in config entry")
        return
    
    # Choose ASCII or Modbus client based on model
    if model in ASCII_MODELS:
        isolar = AsyncAsciiISolar(inverter_ip=inverter_ip, local_ip=local_ip, model=model)
    else:
        isolar = AsyncISolar(inverter_ip=inverter_ip, local_ip=local_ip, model=model)
    
    data_collector = DataCollector(isolar)
    
    # ... [rest of setup_entry unchanged] ...
