# File: easunpy/async_ascii_isolar.py

import asyncio
import socket
import logging
from datetime import datetime
from .models import BatteryData, PVData, GridData, OutputData, SystemStatus

class AsyncAsciiISolar:
    """Async client for EASUN ASCII‐protocol inverters (QPIGS/QPIRI/QMOD/QPIWS/QPIGS2)."""

    ASCII_MODELS = {"EASUN_SMW_8K", "EASUN_SMW_11K"}

    def __init__(self, inverter_ip: str, local_ip: str, model: str = "EASUN_SMW_8K"):
        self.inverter_ip = inverter_ip
        self.local_ip = local_ip
        self.model = model
        self._trans_id = 0
        self.server_port = 502
        self.discovery_port = 58899
        self.commands = ["QPIGS", "QPIRI", "QMOD", "QPIWS", "QPIGS2"]
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._server: asyncio.base_events.Server | None = None
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"AsyncAsciiISolar initialized for model {model}")

    def _compute_crc_xmodem(self, data: bytes) -> int:
        crc = 0
        for b in data:
            crc ^= (b << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
        return crc

    def _adjust_crc_byte(self, byte: int) -> int:
        if byte in (0x0A, 0x0D, 0x28):
            return (byte + 1) & 0xFF
        return byte

    def _build_packet(self, command: str, trans_id: int) -> bytes:
        cmd = command.encode("ascii")
        crc = self._compute_crc_xmodem(cmd)
        hi = self._adjust_crc_byte((crc >> 8) & 0xFF)
        lo = self._adjust_crc_byte(crc & 0xFF)
        payload = cmd + bytes([hi, lo, 0x0D])
        length = len(payload) + 2
        hdr = bytes([
            (trans_id >> 8) & 0xFF, trans_id & 0xFF,
            0x00, 0x01,
            (length >> 8) & 0xFF, length & 0xFF,
            0xFF, 0x04
        ])
        return hdr + payload

    async def _start_server_and_discover(self):
        # UDP discovery
        msg = f"set>server={self.local_ip}:{self.server_port};".encode("ascii")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.sendto(msg, (self.inverter_ip, self.discovery_port))

        # start TCP listener
        self._server = await asyncio.start_server(
            self._handle_client, host=self.local_ip, port=self.server_port
        )
        self.logger.debug(f"Listening on {self.local_ip}:{self.server_port}")
        while self._reader is None:
            await asyncio.sleep(0.1)

    async def _handle_client(self, reader, writer):
        if self._reader is None:
            self._reader = reader
            self._writer = writer
            self.logger.info("Inverter connected back via TCP (ASCII mode)")
        else:
            writer.close()
            await writer.wait_closed()

    async def _ensure_connection(self):
        async with self._lock:
            if not self._reader:
                await self._start_server_and_discover()

    async def _send_command(self, cmd: str) -> str:
        await self._ensure_connection()
        pkt = self._build_packet(cmd, self._trans_id)
        self._trans_id = (self._trans_id + 1) & 0xFFFF
        assert self._writer is not None
        self._writer.write(pkt)
        await self._writer.drain()

        hdr = await asyncio.wait_for(self._reader.readexactly(6), timeout=5)
        length = int.from_bytes(hdr[4:6], "big")
        data = await asyncio.wait_for(self._reader.readexactly(length), timeout=5)
        raw = data[:-3].decode("ascii", errors="ignore")

        # strip any leading garbage up to '('
        idx = raw.find('(')
        raw = raw[idx:].strip() if idx != -1 else raw.strip()
        self.logger.debug(f"Raw {cmd}: {raw!r}")
        return raw

    def _parse_qpigs(self, raw: str) -> dict:
        f = raw.strip("()").split()
        return {
            "grid_voltage":     float(f[0]),
            "grid_frequency":   float(f[1]),
            "output_voltage":   float(f[2]),
            "output_frequency": float(f[3]),
            "apparent_power":   int(float(f[4])),
            "active_power":     int(float(f[5])),
            "load_percent":     int(f[6]),
            "bus_voltage":      float(f[7]),
            "battery_voltage":  float(f[8]),
            "battery_current":  float(f[9]),
            "battery_soc":      int(f[10]),
            "battery_temp":     int(float(f[11])),
            "pv_current":       float(f[12]),
            "pv_voltage":       float(f[13]),
            "pv_charge_power":  int(float(f[19])),
        }

    def _parse_qpigs2(self, raw: str) -> dict:
        f = raw.strip("()").split()
        return {
            "pv2_current": float(f[0]),
            "pv2_voltage": float(f[1]),
            "pv2_power":   int(float(f[2])),
        }

    def _parse_qmod(self, raw: str) -> str:
        code = raw.strip("()")
        return {
            "P": "Power On Mode",
            "S": "Standby Mode",
            "L": "Line Mode",
            "B": "Battery Mode",
            "F": "Fault Mode",
            "H": "Power Saving Mode",
        }.get(code, code)

    def _parse_qpiri(self, raw: str) -> dict:
        """Device rating info with friendly names."""
        f = raw.strip("()").split()
        if len(f) < 27:
            return {"error": "Invalid QPIRI response"}
        # helpers
        btype = {"0": "AGM", "1": "Flooded", "2": "User"}.get(f[12], f[12])
        irange = {"0": "Appliance", "1": "UPS"}.get(f[15], f[15])
        osp    = {"0": "UtilitySolarBat", "1": "SolarUtilityBat", "2": "SolarBatUtility"}.get(f[16], f[16])
        csp    = {"1": "Solar first", "2": "Solar + Utility", "3": "Only solar charging permitted"}.get(f[17], f[17])
        mtype  = {"00": "Grid tie", "01": "Off Grid", "10": "Hybrid"}.get(f[19], f[19])
        topo   = {"0": "transformerless", "1": "transformer"}.get(f[20], f[20])
        omode  = {
            "00": "single machine output", "01": "parallel output",
            "02": "Phase 1 of 3 Phase output", "03": "Phase 2 of 3 Phase output",
            "04": "Phase 3 of 3 Phase output", "05": "Phase 1 of 2 Phase output",
            "06": "Phase 2 of 2 Phase output (120°)", "07": "Phase 2 of 2 Phase output (180°)",
        }.get(f[21], f[21])

        return {
            "Grid Rating Voltage":         f"{f[0]} V",
            "Grid Rating Current":         f"{f[1]} A",
            "AC Output Rating Voltage":    f"{f[2]} V",
            "AC Output Rating Frequency":  f"{f[3]} Hz",
            "AC Output Rating Current":    f"{f[4]} A",
            "AC Output Rating Apparent Power": f"{f[5]} VA",
            "AC Output Rating Active Power":   f"{f[6]} W",
            "Battery Rating Voltage":      f"{f[7]} V",
            "Battery Re-Charge Voltage":   f"{f[8]} V",
            "Battery Under Voltage":       f"{f[9]} V",
            "Battery Bulk Voltage":        f"{f[10]} V",
            "Battery Float Voltage":       f"{f[11]} V",
            "Battery Type":                btype,
            "Max AC Charging Current":     f"{f[13]} A",
            "Max Charging Current":        f"{f[14]} A",
            "Input Voltage Range":         irange,
            "Output Source Priority":      osp,
            "Charger Source Priority":     csp,
            "Parallel Max Num":            f[18],
            "Machine Type":                mtype,
            "Topology":                    topo,
            "Output Mode":                 omode,
            "Battery Re-Discharge Voltage": f"{f[22]} V",
            "PV OK Condition":             f[23],
            "PV Power Balance":            f"{f[24]}",
            "Max Charging Time at CV Stage": f"{f[25]} min",
            "Max Discharging Current":      f"{f[26]} A",
        }

    def _parse_qpiws(self, raw: str) -> list[str]:
        """Parse bitwise warnings and return list of friendly strings."""
        bits = list(raw.strip("()"))
        if len(bits) < 32:
            return ["Invalid QPIWS response"]
        warn_map = {
            0:  "Reserved",
            1:  "Inverter fault",
            2:  "Bus over",
            3:  "Bus under",
            4:  "Bus soft fail",
            5:  "Line fail",
            6:  "OPV short",
            7:  "Inverter voltage low",
            8:  "Inverter voltage high",
            9:  "Inverter soft fail",
            10: "Inverter over current",
            11: "Inverter over load",
            12: "Inverter over temperature",
            13: "Fan locked",
            14: "Battery voltage high",
            15: "Battery low alarm",
            17: "Battery under shutdown",
            19: "Over load",
            20: "EEPROM fault",
            21: "Inverter over current",
            22: "Inverter soft fail",
            23: "Self test fail",
            24: "OP DC voltage over",
            25: "Battery open",
            26: "Current sensor fail",
            27: "Battery short",
            28: "Power limit",
            29: "PV voltage high",
            30: "MPPT overload fault",
            31: "MPPT overload warning",
            32: "Battery too low to charge",
        }
        warnings = [name for idx, name in warn_map.items()
                    if idx < len(bits) and bits[idx] == '1']
        return warnings or ["No warnings"]

    async def get_all_data(self):
        """Poll all ASCII commands, parse them and return five data classes."""
        raw = {}
        for cmd in self.commands:
            raw[cmd] = await self._send_command(cmd)
            await asyncio.sleep(0.3)

        # clean up connection
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        p1 = self._parse_qpigs(raw["QPIGS"])
        p2 = self._parse_qpigs2(raw["QPIGS2"])
        mode_name = self._parse_qmod(raw["QMOD"])
        info = self._parse_qpiri(raw["QPIRI"])
        warns = self._parse_qpiws(raw["QPIWS"])

        battery = BatteryData(
            voltage=p1["battery_voltage"],
            current=p1["battery_current"],
            power=int(p1["battery_voltage"] * p1["battery_current"]),
            soc=p1["battery_soc"],
            temperature=p1["battery_temp"],
        )
        pv = PVData(
            total_power=p1["pv_charge_power"],
            charging_power=p1["pv_charge_power"],
            charging_current=p1["pv_current"],
            temperature=0.0,
            pv1_voltage=p1["pv_voltage"],
            pv1_current=p1["pv_current"],
            pv1_power=int(p1["pv_voltage"] * p1["pv_current"]),
            pv2_voltage=p2["pv2_voltage"],
            pv2_current=p2["pv2_current"],
            pv2_power=p2["pv2_power"],
            pv_generated_today=0.0,
            pv_generated_total=0.0,
        )
        grid = GridData(
            voltage=p1["grid_voltage"],
            power=p1["active_power"],
            frequency=int(p1["grid_frequency"] * 100),
        )
        output = OutputData(
            voltage=p1["output_voltage"],
            current=(p1["active_power"] / p1["output_voltage"] if p1["output_voltage"] else 0.0),
            power=p1["active_power"],
            apparent_power=p1["apparent_power"],
            load_percentage=p1["load_percent"],
            frequency=int(p1["output_frequency"] * 100),
        )
        status = SystemStatus(
            operating_mode=None,
            mode_name=mode_name,
            inverter_time=datetime.utcnow(),
            inverter_info=info,
            warnings=warns,
        )

        return battery, pv, grid, output, status
