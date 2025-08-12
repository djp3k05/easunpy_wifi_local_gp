# File: easunpy/models.py

from dataclasses import dataclass, field
from enum import Enum
import datetime
from typing import Dict, Optional, Callable, Any

@dataclass
class BatteryData:
    voltage: float
    current: float
    power: int
    soc: int
    temperature: int

@dataclass
class PVData:
    total_power: int
    charging_power: int
    charging_current: int
    temperature: int
    pv1_voltage: float
    pv1_current: int
    pv1_power: int
    pv2_voltage: float
    pv2_current: int
    pv2_power: int
    pv_generated_today: int
    pv_generated_total: int

@dataclass
class GridData:
    voltage: float
    power: int
    frequency: int

@dataclass
class OutputData:
    voltage: float
    current: float
    power: int
    apparent_power: int
    load_percentage: int
    frequency: int

class OperatingMode(Enum):
    SUB = 2
    SBU = 3

@dataclass
class SystemStatus:
    operating_mode: Optional[int]
    mode_name: str
    inverter_time: datetime.datetime

@dataclass
class ModelConfig:
    name: str
    registers: Dict[str, Any]
    scan: bool = True
    register_decoder: Optional[Callable[[bytes], Any]] = None
    scan_interval: int = 30

# Predefined model configurations for Modbus-based clients
MODEL_CONFIGS: Dict[str, ModelConfig] = {
    "ISOLAR_SMG_II_11K": ModelConfig(
        name="iSolar SMG II 11K",
        registers={
            "QPIRI": (201, 1),
            "QPIGS": (277, 5),
            "QMOD": (302, 3),
            "QPIWS": (351, 3),
            "QPIPower": (600, 9),
        },
        scan=True,
    ),
    "ISOLAR_SMG_II_8K": ModelConfig(
        name="iSolar SMG II 8K",
        registers={
            "QPIRI": (201, 1),
            "QPIGS": (277, 5),
            "QMOD": (302, 3),
            "QPIWS": (351, 3),
            "QPIPower": (600, 9),
        },
        scan=True,
    ),
    # Add other Modbus-supported models here...
}

# ASCII protocol responses for QPIRI command
ASCII_QPIRI_FIELDS = [
    "pv1_voltage", "pv1_voltage_max",
    "pv2_voltage", "pv2_voltage_max",
    "ac_out_voltage", "ac_out_voltage_max",
    "charge_voltage", "battery_voltage",
    "battery_capacity", "battery_type",
    "battery_charge_current", "battery_charge_current_max",
    "hostname", "serial_number",
    "firmware_version"
]

# ASCII protocol responses for QPIGS command
ASCII_QPIGS_FIELDS = [
    "grid_voltage", "grid_frequency",
    "output_voltage", "output_frequency",
    "apparent_power", "active_power",
    "load_percent", "bus_voltage",
    "battery_voltage", "battery_current",
    "battery_soc", "battery_temp",
    "pv_current", "pv_voltage",
    "pv_power", "pv1_voltage", "pv1_current",
    "pv1_power", "pv2_voltage", "pv2_current",
    "pv2_power"
]

# Decoder for ASCII QPIRI
def decode_ascii_qpiri(raw: str) -> Dict[str, Any]:
    # raw: "(230.0 47.8 230.0 50.0 47.8 11000 ... )"
    values = raw.strip("()").split()
    return {
        ASCII_QPIRI_FIELDS[i]: (
            float(values[i]) if "." in values[i] else int(values[i])
        )
        for i in range(min(len(values), len(ASCII_QPIRI_FIELDS)))
    }

# Decoder for ASCII QPIGS
def decode_ascii_qpigs(raw: str) -> Dict[str, Any]:
    values = raw.strip("()").split()
    data = {}
    for i, field in enumerate(ASCII_QPIGS_FIELDS):
        val = values[i]
        data[field] = float(val) if "." in val else int(val)
    return data

# Sample usage of decoders within a higher-level ASCII client
@dataclass
class ASCIIModelConfig:
    name: str
    commands: Dict[str, Callable[[str], Dict[str, Any]]] = field(default_factory=dict)
    scan: bool = True
    scan_interval: int = 30

ASCII_MODEL_CONFIGS: Dict[str, ASCIIModelConfig] = {
    "EASUN_SMW_8K": ASCIIModelConfig(
        name="EASUN SMW 8K",
        commands={
            "QPIRI": decode_ascii_qpiri,
            "QPIGS": decode_ascii_qpigs,
            "QPIGS2": decode_ascii_qpigs,  # reuse same decoder
            "QMOD": lambda r: {"mode": r.strip("()")},
        },
    ),
    "EASUN_SMW_11K": ASCIIModelConfig(
        name="EASUN SMW 11K",
        commands={
            "QPIRI": decode_ascii_qpiri,
            "QPIGS": decode_ascii_qpigs,
            "QPIGS2": decode_ascii_qpigs,
            "QMOD": lambda r: {"mode": r.strip("()")},
        },
    ),
}

