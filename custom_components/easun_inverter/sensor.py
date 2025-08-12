# File: custom_components/easun_inverter/sensor.py

"""All Easun sensors grouped under one device, static and dynamic (QPIRI/QPIWS)."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import (
    UnitOfElectricPotential,
    UnitOfElectricCurrent,
    UnitOfPower,
    UnitOfApparentPower,
    UnitOfFrequency,
    UnitOfTemperature,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from easunpy.async_isolar import AsyncISolar
from easunpy.async_ascii_isolar import AsyncAsciiISolar
from easunpy.models import MODEL_CONFIGS
from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Route any model ending in SMW_8K/11K to ASCII
ASCII_MODELS = {m for m in MODEL_CONFIGS if m.endswith("SMW_8K") or m.endswith("SMW_11K")}

# Friendly names for QPIRI
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
    def __init__(self, client: AsyncISolar | AsyncAsciiISolar) -> None:
        self.client = client
        self._data: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._sensors: list[SensorEntity] = []
        _LOGGER.info(f"DataCollector initialized with model {client.model}")

    def register_sensor(self, sensor: SensorEntity) -> None:
        self._sensors.append(sensor)

    async def update_data(self) -> None:
        if self._lock.locked():
            return
        await self._lock.acquire()
        try:
            battery, pv, grid, output, status = await self.client.get_all_data()
            self._data = {
                "battery": battery,
                "pv": pv,
                "grid": grid,
                "output": output,
                "system": status,
            }
            for s in self._sensors:
                s.update_from_collector()
        except Exception as e:
            _LOGGER.error("Failed to fetch Easun data: %s", e)
        finally:
            self._lock.release()

    def get_data(self, key: str) -> Any:
        return self._data.get(key)

class EasunSensor(SensorEntity):
    def __init__(
        self,
        collector: DataCollector,
        sensor_id: str,
        name: str,
        unit: str | None,
        data_type: str,
        data_attr: str,
        conv: callable | None = None,
    ) -> None:
        super().__init__()
        self.collector = collector
        self._id = sensor_id
        self._name = name
        self._unit = unit
        self._data_type = data_type
        self._data_attr = data_attr
        self._conv = conv
        self._state: Any = None
        self._available = True

        inv = collector.client
        self._device_info = {
            "identifiers": {(DOMAIN, inv.inverter_ip)},
            "name": f"Easun Inverter {inv.inverter_ip}",
            "manufacturer": "Easun",
            "model": inv.model,
            "configuration_url": f"http://{inv.inverter_ip}",
        }
        collector.register_sensor(self)

    def update_from_collector(self) -> None:
        data = self.collector.get_data(self._data_type)
        if data is None:
            self._available = False
            return
        val = getattr(data, self._data_attr)
        if self._conv:
            val = self._conv(val)
        self._state = val
        self._available = True

    @property
    def name(self) -> str:
        return f"Easun {self._name}"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_{self._id}"

    @property
    def state(self) -> Any:
        return self._state

    @property
    def unit_of_measurement(self) -> str | None:
        return self._unit

    @property
    def available(self) -> bool:
        return self._available

    @property
    def should_poll(self) -> bool:
        return False

    def update(self) -> None:
        pass

    @property
    def device_info(self) -> dict:
        return self._device_info

class InverterInfoSensor(SensorEntity):
    def __init__(self, collector: DataCollector, field: str) -> None:
        super().__init__()
        self.collector = collector
        self._field = field
        self._state: Any = None
        self._available = True

        inv = collector.client
        self._device_info = {
            "identifiers": {(DOMAIN, inv.inverter_ip)},
            "name": f"Easun Inverter {inv.inverter_ip}",
            "manufacturer": "Easun",
            "model": inv.model,
            "configuration_url": f"http://{inv.inverter_ip}",
        }
        collector.register_sensor(self)

    def update_from_collector(self) -> None:
        status = self.collector.get_data("system")
        if not status or not status.inverter_info:
            self._state = None
            self._available = False
            return
        self._state = status.inverter_info.get(self._field)
        self._available = True

    @property
    def name(self) -> str:
        return f"Easun {self._field}"

    @property
    def unique_id(self) -> str:
        key = self._field.lower().replace(" ", "_")
        return f"{DOMAIN}_info_{key}"

    @property
    def state(self) -> Any:
        return self._state

    @property
    def unit_of_measurement(self) -> str | None:
        if "Voltage" in self._field:
            return UnitOfElectricPotential.VOLT
        if "Current" in self._field and "AC Output" not in self._field:
            return UnitOfElectricCurrent.AMPERE
        if "Frequency" in self._field:
            return UnitOfFrequency.HERTZ
        if "Apparent Power" in self._field:
            return UnitOfApparentPower.VOLT_AMPERE
        if "Active Power" in self._field:
            return UnitOfPower.WATT
        return None

    @property
    def available(self) -> bool:
        return self._available

    @property
    def should_poll(self) -> bool:
        return False

    def update(self) -> None:
        pass

    @property
    def device_info(self) -> dict:
        return self._device_info

class InverterWarningsSensor(SensorEntity):
    def __init__(self, collector: DataCollector) -> None:
        super().__init__()
        self.collector = collector
        self._state: Any = None
        self._available = True

        inv = collector.client
        self._device_info = {
            "identifiers": {(DOMAIN, inv.inverter_ip)},
            "name": f"Easun Inverter {inv.inverter_ip}",
            "manufacturer": "Easun",
            "model": inv.model,
            "configuration_url": f"http://{inv.inverter_ip}",
        }
        collector.register_sensor(self)

    def update_from_collector(self) -> None:
        status = self.collector.get_data("system")
        if not status or status.warnings is None:
            self._state = None
            self._available = False
            return
        self._state = ", ".join(status.warnings)
        self._available = True

    @property
    def name(self) -> str:
        return "Easun Inverter Warnings"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_warnings"

    @property
    def state(self) -> Any:
        return self._state

    @property
    def available(self) -> bool:
        return self._available

    @property
    def should_poll(self) -> bool:
        return False

    def update(self) -> None:
        pass

    @property
    def device_info(self) -> dict:
        return self._device_info

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    _LOGGER.debug("Setting up Easun Inverter sensors")
    interval = config_entry.options.get("scan_interval", config_entry.data.get("scan_interval", 30))
    inv_ip = config_entry.data.get("inverter_ip")
    local_ip = config_entry.data.get("local_ip")
    model  = config_entry.data.get("model")

    if not inv_ip or not local_ip:
        _LOGGER.error("Missing inverter_ip or local_ip")
        return

    if model in ASCII_MODELS:
        client = AsyncAsciiISolar(inverter_ip=inv_ip, local_ip=local_ip, model=model)
    else:
        client = AsyncISolar(inverter_ip=inv_ip, local_ip=local_ip, model=model)

    collector = DataCollector(client)
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = collector

    def freq(v): return v / 100 if v is not None else None

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
        EasunSensor(collector, "grid_frequency", "Grid Frequency", UnitOfFrequency.HERTZ, "grid", "frequency", freq),
        EasunSensor(collector, "output_voltage", "Output Voltage", UnitOfElectricPotential.VOLT, "output", "voltage"),
        EasunSensor(collector, "output_current", "Output Current", UnitOfElectricCurrent.AMPERE, "output", "current"),
        EasunSensor(collector, "output_power", "Output Power", UnitOfPower.WATT, "output", "power"),
        EasunSensor(collector, "output_apparent", "Output Apparent Power", UnitOfApparentPower.VOLT_AMPERE, "output", "apparent_power"),
        EasunSensor(collector, "output_load", "Output Load %", PERCENTAGE, "output", "load_percentage"),
        EasunSensor(collector, "output_frequency", "Output Frequency", UnitOfFrequency.HERTZ, "output", "frequency", freq),
        EasunSensor(collector, "operating_mode", "Operating Mode", None, "system", "mode_name"),
        EasunSensor(collector, "inverter_time", "Inverter Time", None, "system", "inverter_time"),
    ]

    # dynamic QPIRI/QPIWS for ASCII models
    if model in ASCII_MODELS:
        for f in QPIRI_FIELDS:
            entities.append(InverterInfoSensor(collector, f))
        entities.append(InverterWarningsSensor(collector))

    add_entities(entities, True)

    async def _update(now):
        await collector.update_data()

    async_track_time_interval(hass, _update, timedelta(seconds=interval))
