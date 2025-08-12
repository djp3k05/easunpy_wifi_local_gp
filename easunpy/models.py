# File: easunpy/models.py

from dataclasses import dataclass, field
from enum import Enum
import datetime
from typing import Dict, Optional, Callable, Any, List

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
    """Extended to include QPIRI‐info and QPIWS‐warnings."""
    operating_mode: Optional[int]
    mode_name: str
    inverter_time: datetime.datetime
    # new fields:
    inverter_info: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str]        = field(default_factory=list)

@dataclass
class RegisterConfig:
    """Configuration for a single register."""
    address: int
    scale_factor: float = 1.0
    processor: Optional[Callable[[int], Any]] = None

@dataclass
class ModelConfig:
    name: str
    register_map: Dict[str, RegisterConfig] = field(default_factory=dict)

    def get_address(self, register_name: str) -> Optional[int]:
        cfg = self.register_map.get(register_name)
        return cfg.address if cfg else None

    def get_scale_factor(self, register_name: str) -> float:
        cfg = self.register_map.get(register_name)
        return cfg.scale_factor if cfg else 1.0

    def process_value(self, register_name: str, value: int) -> Any:
        cfg = self.register_map.get(register_name)
        if not cfg:
            return value
        if cfg.processor:
            return cfg.processor(value)
        return value * cfg.scale_factor

# … your existing Modbus‐ModelConfig definitions here …

# ASCII‐only (no registers) so we can detect model name
EASUN_SMW_8K  = ModelConfig(name="EASUN_SMW_8K",  register_map={})
EASUN_SMW_11K = ModelConfig(name="EASUN_SMW_11K", register_map={})

MODEL_CONFIGS: Dict[str, ModelConfig] = {
    "ISOLAR_SMG_II_11K": ISOLAR_SMG_II_11K,
    "ISOLAR_SMG_II_6K":  ISOLAR_SMG_II_6K,
    "EASUN_SMW_8K":      EASUN_SMW_8K,
    "EASUN_SMW_11K":     EASUN_SMW_11K,
}
