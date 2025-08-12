# File: easunpy/async_ascii_isolar.py

import asyncio
import socket
import logging
from datetime import datetime
from .models import BatteryData, PVData, GridData, OutputData, SystemStatus

class AsyncAsciiISolar:
    """Async client for EASUN ASCII‐protocol inverters (QPIGS/QPIRI/etc)."""

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
        # avoid reserved chars: 0x0A, 0x0D, 0x28
        if byte in (0x0A, 0x0D, 0x28):
            return (byte + 1) & 0xFF
        return byte

    def _build_packet(self, command: str, trans_id: int) -> bytes:
        cmd_bytes = command.encode("ascii")
        crc = self._compute_crc_xmodem(cmd_bytes)
        high = self._adjust_crc_byte((crc >> 8) & 0xFF)
        low = self._adjust_crc_byte(crc & 0xFF)
        data = cmd_bytes + bytes([high, low, 0x0D])
        # length = data length + 2 (unit + function)
        length = len(data) + 2
        header = bytes([
            (trans_id >> 8) & 0xFF, trans_id & 0xFF,  # Trans ID
            0x00, 0x01,                                # Protocol ID
            (length >> 8) & 0xFF, length & 0xFF,      # Length
            0xFF,                                      # Unit ID
            0x04                                       # Function code
        ])
        return header + data

    async def _start_server_and_discover(self):
        # UDP discovery
        msg = f"set>server={self.local_ip}:{self.server_port};".encode("ascii")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.sendto(msg, (self.inverter_ip, self.discovery_port))

        # start TCP listener
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self.local_ip,
            port=self.server_port
        )
        self.logger.debug(f"Listening for inverter TCP on {self.local_ip}:{self.server_port}")
        # wait until inverter connects back
        while self._reader is None:
            await asyncio.sleep(0.1)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
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

    async def _send_command(self, command: str) -> str:
        await self._ensure_connection()
        packet = self._build_packet(command, self._trans_id)
        self._trans_id = (self._trans_id + 1) & 0xFFFF

        assert self._writer is not None
        self._writer.write(packet)
        await self._writer.drain()

        # read Modbus‐style header
        header = await asyncio.wait_for(self._reader.readexactly(6), timeout=5)
        length = int.from_bytes(header[4:6], "big")
        payload = await asyncio.wait_for(self._reader.readexactly(length), timeout=5)
        # strip CRC (2 bytes) + CR
        raw = payload[:-3].decode("ascii", errors="ignore")
        return raw

    def _parse_qpigs(self, raw: str) -> dict:
        fields = raw.strip("()").split()
        return {
            "grid_voltage":      float(fields[0]),
            "grid_frequency":    float(fields[1]),
            "output_voltage":    float(fields[2]),
            "output_frequency":  float(fields[3]),
            "apparent_power":    int(float(fields[4])),
            "active_power":      int(float(fields[5])),
            "load_percent":      int(fields[6]),
            "bus_voltage":       float(fields[7]),
            "battery_voltage":   float(fields[8]),
            "battery_current":   float(fields[9]),
            "battery_soc":       int(fields[10]),
            "battery_temp":      int(float(fields[11])),
            "pv_current":        float(fields[12]),
            "pv_voltage":        float(fields[13]),
            "pv_charge_power":   int(float(fields[19])),
        }

    def _parse_qpigs2(self, raw: str) -> dict:
        fields = raw.strip("()").split()
        return {
            "pv2_current": float(fields[0]),
            "pv2_voltage": float(fields[1]),
            "pv2_power":   int(float(fields[2])),
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
        }.get(code, f"Unknown Mode: {code}")

    async def get_all_data(
        self
    ) -> tuple[BatteryData, PVData, GridData, OutputData, SystemStatus]:
        """Poll all ASCII commands and assemble dataclasses."""
        # fire off each command
        r = {}
        for cmd in self.commands:
            raw = await self._send_command(cmd)
            r[cmd] = raw
            await asyncio.sleep(0.5)

        # close after polling
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        # parse
        p1 = self._parse_qpigs(r["QPIGS"])
        p2 = self._parse_qpigs2(r["QPIGS2"])
        mode_name = self._parse_qmod(r["QMOD"])

        # BatteryData
        bat_voltage = p1["battery_voltage"]
        bat_current = p1["battery_current"]
        battery = BatteryData(
            voltage=bat_voltage,
            current=bat_current,
            power=int(bat_voltage * bat_current),
            soc=p1["battery_soc"],
            temperature=p1["battery_temp"],
        )

        # PVData
        pv1_v = p1["pv_voltage"]
        pv1_i = p1["pv_current"]
        pv2_v = p2["pv2_voltage"]
        pv2_i = p2["pv2_current"]
        pv = PVData(
            total_power=p1["pv_charge_power"],
            charging_power=p1["pv_charge_power"],
            charging_current=p1["pv_current"],
            temperature=0.0,  # not provided
            pv1_voltage=pv1_v,
            pv1_current=pv1_i,
            pv1_power=int(pv1_v * pv1_i),
            pv2_voltage=pv2_v,
            pv2_current=pv2_i,
            pv2_power=p2["pv2_power"],
            pv_generated_today=0.0,
            pv_generated_total=0.0,
        )

        # GridData
        grid = GridData(
            voltage=p1["grid_voltage"],
            power=p1["active_power"],
            frequency=int(p1["grid_frequency"] * 100),  # centi‐Hz for sensor conversion
        )

        # OutputData
        out_voltage = p1["output_voltage"]
        out_power = p1["active_power"]
        out_current = (
            out_power / out_voltage if out_voltage else 0.0
        )
        output = OutputData(
            voltage=out_voltage,
            current=out_current,
            power=out_power,
            apparent_power=p1["apparent_power"],
            load_percentage=p1["load_percent"],
            frequency=int(p1["output_frequency"] * 100),
        )

        # SystemStatus
        status = SystemStatus(
            operating_mode=None,
            mode_name=mode_name,
            inverter_time=datetime.utcnow(),
        )

        return battery, pv, grid, output, status
