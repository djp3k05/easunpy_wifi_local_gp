# File: custom_components/easun_inverter/sensor.py

"""Support for Easun Inverter sensors, including dynamic QPIRI and QPIWS sensors."""
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
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_time_interval

from . import DOMAIN
from easunpy.async_isolar import AsyncISolar
from easunpy.async_ascii_isolar import AsyncAsciiISolar
from easunpy.models import MODEL_CONFIGS

_LOGGER = logging.getLogger(__name__)

# Any model key that ends with SMW_8K or SMW_11K uses ASCII protocol
ASCII_MODELS = {
    key for key in MODEL_CONFIGS if key.endswith("SMW_8K") or key.endswith("SMW_11K")
}

# Friendly names for QPIRI fields as returned in SystemStatus.inverter_info
QPIRI_FIELDS = [
    "Grid Rating Voltage",
    "Grid Rating Current",
    "AC Output Rating Voltage",
    "AC Output Rating Frequency",
    "AC Output Rating Current",
    "AC Output Rating Apparent Power",
    "AC Output Rating Active Power",
    "Battery Rating Voltage",
    "Battery Re-Charge Voltage",
    "Battery Under Voltage",
    "Battery Bulk Voltage",
    "Battery Float Voltage",
    "Battery Type",
    "Max AC Charging Current",
    "Max Charging Current",
    "Input Voltage Range",
    "Output Source Priority",
    "Charger Source Priority",
    "Parallel Max Num",
    "Machine Type",
    "Topology",
    "Output Mode",
    "Battery Re-Discharge Voltage",
    "PV OK Condition",
    "PV Power Balance",
    "Max Charging Time at CV Stage",
    "Max Discharging Current",
]


class DataCollector:
    """Centralized data collector for Easun Inverter."""

    def __init__(self, isolar):
        self._isolar = isolar
        self._data: dict[str, any] = {}
        self._lock = asyncio.Lock()
        self._consecutive_failures = 0
        self._last_successful_update: datetime | None = None
        self._update_timeout = 30
        self._sensors: list[SensorEntity] = []
        _LOGGER.info(f"DataCollector initialized with model: {self._isolar.model}")

    def register_sensor(self, sensor: SensorEntity):
        """Register a sensor to be updated when data is refreshed."""
        self._sensors.append(sensor)
        _LOGGER.debug(f"Registered sensor: {sensor.name}")

    async def update_data(self):
        """Fetch all data from the inverter asynchronously using bulk request."""
        if not self._lock.locked():
            await self._lock.acquire()
        else:
            _LOGGER.warning("Update already in progress, skipping")
            return

        try:
            task = asyncio.create_task(self._do_update())
            await asyncio.wait_for(task, timeout=self._update_timeout)
            for sensor in self._sensors:
                sensor.update_from_collector()
            _LOGGER.debug("Updated all registered sensors")
        except asyncio.TimeoutError:
            _LOGGER.error("Update timed out; cancelling")
            task.cancel()
            raise
        finally:
            self._lock.release()

    async def _do_update(self):
        battery, pv, grid, output, status = await self._isolar.get_all_data()
        if all(x is None for x in (battery, pv, grid, output, status)):
            raise RuntimeError("No data received from inverter")
        self._data = {
            "battery": battery,
            "pv": pv,
            "grid": grid,
            "output": output,
            "system": status,
        }
        self._consecutive_failures = 0
        self._last_successful_update = datetime.now()
        _LOGGER.debug("DataCollector updated all data")

    def get_data(self, data_type: str):
        return self._data.get(data_type)


class EasunSensor(SensorEntity):
    """Base sensor for static EasySun data (battery, pv, grid, output, system)."""

    def __init__(
        self,
        collector: DataCollector,
        sensor_id: str,
        name: str,
        unit: str | None,
        data_type: str,
        data_attr: str,
        converter=None,
    ):
        super().__init__()
        self._collector = collector
        self._sensor_id = sensor_id
        self._name = name
        self._unit = unit
        self._data_type = data_type
        self._data_attr = data_attr
        self._converter = converter
        self._state = None
        self._available = True
        self._force_update = True

        inv = collector._isolar
        self._inverter_ip = inv.inverter_ip
        self._model = inv.model

        collector.register_sensor(self)

    def update_from_collector(self):
        data = self._collector.get_data(self._data_type)
        if data is not None:
            val = getattr(data, self._data_attr)
            if self._converter:
                val = self._converter(val)
            self._state = val
            self._available = True
        else:
            self._available = False
        self.async_write_ha_state()

    @property
    def name(self):
        return f"Easun {self._name}"

    @property
    def unique_id(self):
        return f"easun_{self._sensor_id}"

    @property
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self):
        return self._unit

    @property
    def available(self):
        return self._available

    @property
    def should_poll(self):
        return False

    @property
    def force_update(self):
        return self._force_update

    @property
    def extra_state_attributes(self):
        return {"data_type": self._data_type, "attribute": self._data_attr}

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._inverter_ip)},
            "name": f"Easun Inverter {self._inverter_ip}",
            "manufacturer": "Easun",
            "model": self._model,
            "configuration_url": f"http://{self._inverter_ip}",
        }


class InverterInfoSensor(SensorEntity):
    """Dynamic sensor for each QPIRI field in SystemStatus.inverter_info."""

    def __init__(self, collector: DataCollector, field: str):
        super().__init__()
        self._collector = collector
        self._field = field
        self._state = None
        inv = collector._isolar
        self._inverter_ip = inv.inverter_ip
        self._model = inv.model
        collector.register_sensor(self)

    def update_from_collector(self):
        status = self._collector.get_data("system")
        if status and status.inverter_info:
            val = status.inverter_info.get(self._field)
            self._state = val
            self._available = True
        else:
            self._state = None
            self._available = False
        self.async_write_ha_state()

    @property
    def name(self):
        return f"Easun {self._field}"

    @property
    def unique_id(self):
        return f"easun_info_{self._field.lower().replace(' ', '_')}"

    @property
    def state(self):
        return self._state

    @property
    def available(self):
        return self._available

    @property
    def should_poll(self):
        return False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._inverter_ip)},
            "name": f"Easun Inverter {self._inverter_ip}",
            "manufacturer": "Easun",
            "model": self._model,
            "configuration_url": f"http://{self._inverter_ip}",
        }


class InverterWarningsSensor(SensorEntity):
    """Sensor for QPIWS warnings list."""

    def __init__(self, collector: DataCollector):
        super().__init__()
        self._collector = collector
        self._state = None
        inv = collector._isolar
        self._inverter_ip = inv.inverter_ip
        self._model = inv.model
        collector.register_sensor(self)

    def update_from_collector(self):
        status = self._collector.get_data("system")
        if status and status.warnings is not None:
            self._state = ", ".join(status.warnings)
            self._available = True
        else:
            self._state = None
            self._available = False
        self.async_write_ha_state()

    @property
    def name(self):
        return "Easun Inverter Warnings"

    @property
    def unique_id(self):
        return f"easun_warnings_{self._inverter_ip}"

    @property
    def state(self):
        return self._state

    @property
    def available(self):
        return self._available

    @property
    def should_poll(self):
        return False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._inverter_ip)},
            "name": f"Easun Inverter {self._inverter_ip}",
            "manufacturer": "Easun",
            "model": self._model,
            "configuration_url": f"http://{self._inverter_ip}",
        }


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Easun Inverter sensors."""
    _LOGGER.debug("Setting up Easun Inverter sensors")

    scan_interval = config_entry.options.get(
        "scan_interval", config_entry.data.get("scan_interval", 30)
    )
    inverter_ip = config_entry.data.get("inverter_ip")
    local_ip = config_entry.data.get("local_ip")
    model = config_entry.data.get("model")

    if not inverter_ip or not local_ip:
        _LOGGER.error("Missing inverter or local IP")
        return

    # Choose ASCII or Modbus client
    if model in ASCII_MODELS:
        client = AsyncAsciiISolar(inverter_ip=inverter_ip, local_ip=local_ip, model=model)
    else:
        client = AsyncISolar(inverter_ip=inverter_ip, local_ip=local_ip, model=model)

    collector = DataCollector(client)
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {"collector": collector}

    # Static sensors
    def freq_conv(v): return v / 100 if v is not None else None

    entities: list[SensorEntity] = [
        EasunSensor(collector, "battery_voltage", "Battery Voltage", UnitOfElectricPotential.VOLT, "battery", "voltage"),
        EasunSensor(collector, "battery_current", "Battery Current", UnitOfElectricCurrent.AMPERE, "battery", "current"),
        EasunSensor(collector, "battery_power", "Battery Power", UnitOfPower.WATT, "battery", "power"),
        EasunSensor(collector, "battery_soc", "Battery State of Charge", PERCENTAGE, "battery", "soc"),
        EasunSensor(collector, "battery_temp", "Battery Temperature", UnitOfTemperature.CELSIUS, "battery", "temperature"),
        EasunSensor(collector, "pv1_voltage", "PV1 Voltage", UnitOfElectricPotential.VOLT, "pv", "pv1_voltage"),
        EasunSensor(collector, "pv1_current", "PV1 Current", UnitOfElectricCurrent.AMPERE, "pv", "pv1_current"),
        EasunSensor(collector, "pv1_power", "PV1 Power", UnitOfPower.WATT, "pv", "pv1_power"),
        EasunSensor(collector, "pv2_voltage", "PV2 Voltage", UnitOfElectricPotential.VOLT, "pv", "pv2_voltage"),
        EasunSensor(collector, "pv2_current", "PV2 Current", UnitOfElectricCurrent.AMPERE, "pv", "pv2_current"),
        EasunSensor(collector, "pv2_power", "PV2 Power", UnitOfPower.WATT, "pv", "pv2_power"),
        EasunSensor(collector, "grid_voltage", "Grid Voltage", UnitOfElectricPotential.VOLT, "grid", "voltage"),
        EasunSensor(collector, "grid_power", "Grid Power", UnitOfPower.WATT, "grid", "power"),
        EasunSensor(collector, "grid_frequency", "Grid Frequency", UnitOfFrequency.HERTZ, "grid", "frequency", freq_conv),
        EasunSensor(collector, "output_voltage", "Output Voltage", UnitOfElectricPotential.VOLT, "output", "voltage"),
        EasunSensor(collector, "output_current", "Output Current", UnitOfElectricCurrent.AMPERE, "output", "current"),
        EasunSensor(collector, "output_power", "Output Power", UnitOfPower.WATT, "output", "power"),
        EasunSensor(collector, "output_apparent", "Output Apparent Power", UnitOfApparentPower.VOLT_AMPERE, "output", "apparent_power"),
        EasunSensor(collector, "output_load", "Output Load %", PERCENTAGE, "output", "load_percentage"),
        EasunSensor(collector, "output_frequency", "Output Frequency", UnitOfFrequency.HERTZ, "output", "frequency", freq_conv),
        EasunSensor(collector, "operating_mode", "Operating Mode", None, "system", "mode_name"),
        EasunSensor(collector, "inverter_time", "Inverter Time", None, "system", "inverter_time"),
    ]

    # Dynamic ASCII sensors
    if model in ASCII_MODELS:
        # QPIRI info
        for field in QPIRI_FIELDS:
            entities.append(InverterInfoSensor(collector, field))
        # QPIWS warnings
        entities.append(InverterWarningsSensor(collector))

    add_entities(entities, True)

    # Schedule periodic updates
    async def _update(now):
        await collector.update_data()

    async_track_time_interval(hass, _update, timedelta(seconds=scan_interval))
