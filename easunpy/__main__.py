# File: easunpy/__main__.py

#!/usr/bin/env python3
"""Command-line interface for EasunPy"""

import asyncio
import argparse
from rich.live import Live
from rich.table import Table
from rich.console import Console
from rich.layout import Layout
from rich.text import Text
from datetime import datetime
from .async_isolar import AsyncISolar
from .async_ascii_isolar import AsyncAsciiISolar
from .utils import get_local_ip
from .discover import discover_device
from .models import BatteryData, PVData, GridData, OutputData, SystemStatus, MODEL_CONFIGS
import logging

# any model ending in SMW_8K or SMW_11K uses ASCII
ASCII_MODELS = {
    key for key in MODEL_CONFIGS if key.endswith("SMW_8K") or key.endswith("SMW_11K")
}


class InverterData:
    def __init__(self):
        self.battery = None
        self.pv = None
        self.grid = None
        self.output = None
        self.system = None
        self._last = None

    def update(self, b, pv, g, out, sys):
        self.battery, self.pv, self.grid, self.output, self.system = b, pv, g, out, sys
        self._last = datetime.now()

    @property
    def last_update(self):
        return self._last


def create_dashboard(inverter_data: InverterData, status_message=""):
    layout = Layout()
    # [unchanged dashboard code]
    ...

def create_info_layout(inverter_ip, local_ip, serial, status_message=""):
    layout = Layout()
    # [unchanged info layout code]
    ...

async def main():
    parser = argparse.ArgumentParser(description="Easun Inverter Monitor")
    parser.add_argument("--inverter-ip")
    parser.add_argument("--local-ip")
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--model", choices=list(MODEL_CONFIGS), default=list(MODEL_CONFIGS)[0])
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    local_ip = args.local_ip or get_local_ip()
    if not local_ip:
        print("Could not determine local IP")
        return 1
    inverter_ip = args.inverter_ip or discover_device()
    if not inverter_ip:
        print("Could not discover inverter IP")
        return 1

    console = Console()
    try:
        # pick ASCII vs Modbus
        if args.model in ASCII_MODELS:
            client = AsyncAsciiISolar(inverter_ip, local_ip, model=args.model)
        else:
            client = AsyncISolar(inverter_ip, local_ip, model=args.model)
        data = InverterData()

        if args.continuous:
            with Live(console=console, refresh_per_second=1) as live:
                while True:
                    b, pv, g, out, sys = await client.get_all_data()
                    data.update(b, pv, g, out, sys)
                    live.update(create_dashboard(data))
                    await asyncio.sleep(args.interval)
        else:
            b, pv, g, out, sys = await client.get_all_data()
            data.update(b, pv, g, out, sys)
            console.print(create_info_layout(inverter_ip, local_ip, "", "OK"))
            # [print single update code unchanged]
            ...

        return 0
    except Exception as e:
        console.print(f"[red]Error: {e}")
        return 1


if __name__ == "__main__":
    asyncio.run(main())
