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

from . import DOMAIN
from easunpy.async_isolar import AsyncISolar
from easunpy.async_ascii_isolar import AsyncAsciiISolar

_LOGGER = logging.getLogger(__name__)

ASCII_MODELS = {"EASUN_SMW_8K", "EASUN_SMW_11K"}


class DataCollector:
    """Centralized data collector for Easun Inverter."""

    def __init__(self, isolar):
        self._isolar = isolar
        self._data = {}
        self._lock = asyncio.Lock()
        self._consecutive_failures = 0
        self._max_consecutive_failures = 5
        self._last_update_start = None
        self._last_successful_update = None
        self._update_timeout = 30
        self._sensors = []
        _LOGGER.info(f"DataCollector initialized with model: {self._isolar.model}")

    def register_sensor(self, sensor):
        """Register a sensor to be updated when data is refreshed."""
        self._sensors.append(sensor)
        _LOGGER.debug(f"Registered sensor: {sensor.name}")

    async def is_update_stuck(self) -> bool:
        if self._last_update_start is None:
            return False
        time_since_update = (datetime.now() - self._last_update_start).total_seconds()
        return time_since_update > self._update_timeout

    async def update_data(self):
        """Fetch all data from the inverter asynchronously using bulk request."""
        if not await self._lock.acquire():
            _LOGGER.warning("Could not acquire lock for update")
            return
        try:
            update_task = asyncio.create_task(self._do_update())
            try:
                await asyncio.wait_for(update_task, timeout=self._update_timeout)
                for sensor in self._sensors:
                    sensor.update_from_collector()
                _LOGGER.debug("Updated all registered sensors")
            except asyncio.TimeoutError:
                _LOGGER.error("Update timed out, cancelling task")
                update_task.cancel()
                try:
                    await update_task
                except asyncio.CancelledError:
                    _LOGGER.debug("Update task cancelled successfully")
                raise Exception("Update timed out")
        finally:
            self._lock.release()

    async def _do_update(self):
        try:
            _LOGGER.debug(f"Starting data update using model: {self._isolar.model}")
            battery, pv, grid, output, status = await self._isolar.get_all_data()
            if all(x is None for x in (battery, pv, grid, output, status)):
                raise Exception("No data received from inverter")

            self._data['battery'] = battery
            self._data['pv'] = pv
            self._data['grid'] = grid
            self._data['output'] = output
            self._data['system'] = status
            self._consecutive_failures = 0
            self._last_successful_update = datetime.now()
            _LOGGER.debug("DataCollector updated all data in bulk")
        except Exception as e:
            self._consecutive_failures += 1
            delay = min(30, 2 ** self._consecutive_failures)
            _LOGGER.error(f"Error updating data (attempt {self._consecutive_failures}): {e}")
            _LOGGER.warning(f"Retry in {delay} seconds")
            await asyncio.sleep(delay)
            raise

    def get_data(self, data_type):
        return self._data.get(data_type)

    @property
    def last_update(self):
        return self._last_successful_update

    async def update_model(self, model: str):
        _LOGGER.info(f"Updating inverter model to: {model}")
        self._isolar.update_model(model)


class EasunSensor(SensorEntity):
    """Representation of an Easun Inverter sensor."""

    def __init__(self, data_collector, id, name, unit, data_type, data_attr, value_converter=None):
        self._data_collector = data_collector
        self._id = id
        self._name = name
        self._unit = unit
        self._data_type = data_type
        self._data_attr = data_attr
        self._state = None
        self._value_converter = value_converter
        self._available = True
        self._force_update = True
        self._data_collector.register_sensor(self)

    def update_from_collector(self) -> None:
        try:
            data = self._data_collector.get_data(self._data_type)
            if data:
                if self._data_attr == "inverter_time":
                    value = data.inverter_time.isoformat() if data.inverter_time else None
                else:
                    value = getattr(data, self._data_attr)
                if self._value_converter:
                    value = self._value_converter(value)
                self._state = value
                self._available = True
                _LOGGER.debug(f"{self._name} updated: {self._state}")
            else:
                _LOGGER.warning(f"No {self._data_type} data available")
                self._available = False
        except Exception as e:
            _LOGGER.error(f"Error updating {self._name}: {e}")
            self._available = False
        self.async_write_ha_state()

    def update(self) -> None:
        pass

    @property
    def force_update(self) -> bool:
        return self._force_update

    @property
    def extra_state_attributes(self):
        return {
            'data_type': self._data_type,
            'data_attribute': self._data_attr,
        }

    @property
    def available(self) -> bool:
        return self._available

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def name(self):
        return f"Easun {self._name}"

    @property
    def unique_id(self):
        return f"easun_inverter_{self._id}"

    @property
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self):
        return self._unit


class RegisterScanSensor(SensorEntity):
    """Sensor that shows register scan results."""
    # (unchanged from original)


class DeviceScanSensor(SensorEntity):
    """Sensor that shows device scan results."""
    # (unchanged from original)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
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

    if model in ASCII_MODELS:
        isolar = AsyncAsciiISolar(inverter_ip=inverter_ip, local_ip=local_ip, model=model)
    else:
        isolar = AsyncISolar(inverter_ip=inverter_ip, local_ip=local_ip, model=model)

    data_collector = DataCollector(isolar)

    # Store the coordinator
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(config_entry.entry_id, {})
    hass.data[DOMAIN][config_entry.entry_id]["coordinator"] = data_collector

    # Create sensor entities (battery, PV, grid, output, system) as in your original file
    entities = [
        EasunSensor(data_collector, "battery_voltage", "Battery Voltage", UnitOfElectricPotential.VOLT, "battery", "voltage"),
        # ... all other EasunSensor(...) definitions ...
    ]

    add_entities(entities, True)

    async def _update(now):
        await data_collector.update_data()

    async_track_time_interval(hass, _update, timedelta(seconds=scan_interval))
