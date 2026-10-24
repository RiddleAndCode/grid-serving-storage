"""OpenADR 3.1 Virtual End Node (VEN) Simulator.

Simulates a HEMS device connecting to the VTN via OpenADR 3.1 REST API.
Registers with the VTN, polls for events, and submits status/forecast reports.

Matches the reference implementation structure (home-wetzlas-ven pattern):
  - OAuth 2.0 client credentials authentication
  - Self-registration with resources
  - Periodic status reports (per-resource + aggregate, every 5 min → accelerated to 10s for demo)
  - Hourly forecast reports (24h ahead → accelerated to 30s for demo)
  - Event polling every 15s → accelerated to 5s for demo
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

log = logging.getLogger("openadr-ven")

# ── Simulated Device State ───────────────────────────────────────────────────

RESOURCES = [
    {"resourceName": "pcc-meter", "type": "METER", "description": "Grid connection meter"},
    {"resourceName": "fronius-inverter", "type": "PV_INVERTER", "description": "Fronius Symo 10.0"},
    {"resourceName": "battery-01", "type": "BATTERY", "description": "BYD HVS 10.2 kWh"},
    {"resourceName": "heatpump", "type": "HEAT_PUMP", "description": "Heat pump smart plug"},
    {"resourceName": "floor-heating", "type": "CONTROLLABLE_LOAD", "description": "Floor heating circuit"},
]


class DeviceState:
    """Simulated state for one resource."""

    def __init__(self, name: str, res_type: str):
        self.name = name
        self.res_type = res_type
        self.reading_kw = 0.0
        self.soc = 0.0  # 0-1 fraction (for battery)
        self.usable_capacity_kwh = 0.0
        self.max_discharge_kw = 0.0
        self.operating_state = "NORMAL"
        self.data_quality = "ESTIMATED"
        self._init_state()

    def _init_state(self):
        if self.res_type == "METER":
            self.reading_kw = random.uniform(2.0, 8.0)  # net grid import
        elif self.res_type == "PV_INVERTER":
            self.reading_kw = -random.uniform(0, 8.0)  # negative = generation
        elif self.res_type == "BATTERY":
            self.soc = random.uniform(0.3, 0.9)
            self.usable_capacity_kwh = 10.2
            self.max_discharge_kw = 5.0
            self.reading_kw = random.uniform(-2, 2)  # charge/discharge
        elif self.res_type == "HEAT_PUMP":
            self.reading_kw = random.uniform(0.5, 3.0)
        elif self.res_type == "CONTROLLABLE_LOAD":
            self.reading_kw = random.uniform(0.5, 2.0)

    def drift(self):
        """Small random drift."""
        if self.res_type == "METER":
            self.reading_kw = max(0, self.reading_kw + random.uniform(-0.5, 0.5))
        elif self.res_type == "PV_INVERTER":
            self.reading_kw = min(0, self.reading_kw + random.uniform(-0.3, 0.3))
        elif self.res_type == "BATTERY":
            self.soc = max(0.1, min(0.95, self.soc + random.uniform(-0.02, 0.02)))
            self.reading_kw += random.uniform(-0.3, 0.3)
        elif self.res_type in ("HEAT_PUMP", "CONTROLLABLE_LOAD"):
            self.reading_kw = max(0, self.reading_kw + random.uniform(-0.3, 0.3))

    @property
    def load_shed_available_kw(self) -> float:
        """How much this resource can shed."""
        if self.res_type == "BATTERY":
            return self.max_discharge_kw * max(0, self.soc - 0.15)
        elif self.res_type in ("HEAT_PUMP", "CONTROLLABLE_LOAD"):
            return max(0, self.reading_kw * 0.8)
        return 0.0

    def apply_dispatch(self, direction: str, limit_kw: float | None = None):
        """React to a dispatch event."""
        if direction == "down":
            if self.res_type == "BATTERY" and self.soc > 0.2:
                self.reading_kw = -min(self.max_discharge_kw, self.soc * self.usable_capacity_kwh)
                self.operating_state = "RUNNING_HEIGHTENED"
            elif self.res_type in ("HEAT_PUMP", "CONTROLLABLE_LOAD"):
                self.reading_kw = max(0, self.reading_kw * 0.3)
                self.operating_state = "RUNNING_CURTAILED"
        elif direction == "up":
            if self.res_type == "BATTERY" and self.soc < 0.85:
                self.reading_kw = min(self.max_discharge_kw, (1 - self.soc) * self.usable_capacity_kwh)
                self.operating_state = "RUNNING_HEIGHTENED"

    def reset_dispatch(self):
        self.operating_state = "NORMAL"
        self._init_state()


class VENSimulator:
    """OpenADR 3.1 VEN that communicates with a VTN via REST."""

    def __init__(self, vtn_url: str, client_id: str = "ven-home",
                 ven_name: str = "demo-hems-ven"):
        self.vtn_url = vtn_url.rstrip("/")
        self.client_id = client_id
        self.ven_name = ven_name
        self.ven_id: str | None = None
        self.token: str | None = None
        self.devices: dict[str, DeviceState] = {}
        self.active_events: dict[str, dict] = {}
        self.report_interval_id = 0

        # Initialize device states
        for res in RESOURCES:
            self.devices[res["resourceName"]] = DeviceState(
                res["resourceName"], res["type"]
            )

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _get(self, path: str) -> Any:
        resp = httpx.get(f"{self.vtn_url}{path}", headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> Any:
        resp = httpx.post(f"{self.vtn_url}{path}", json=body, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def authenticate(self):
        """Obtain OAuth 2.0 token."""
        resp = httpx.post(
            f"{self.vtn_url}/auth/token",
            json={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": "demo"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self.token = data["access_token"]
        log.info(f"Authenticated with VTN (client_id={self.client_id})")

    def register(self):
        """Register VEN and its resources."""
        ven = self._post("/vens", {
            "venName": self.ven_name,
            "attributes": [{"type": "DESCRIPTION", "values": ["Demo HEMS VEN — grid-serving storage"]}],
        })
        self.ven_id = ven["id"]
        log.info(f"VEN registered: {self.ven_name} (id={self.ven_id})")

        for res in RESOURCES:
            self._post(f"/vens/{self.ven_id}/resources", {
                "resourceName": res["resourceName"],
                "attributes": [{"type": "DESCRIPTION", "values": [res["description"]]}],
            })
            log.info(f"  Resource registered: {res['resourceName']}")

    def discover_programs(self) -> list[dict]:
        """Discover available programs."""
        progs = self._get("/programs")
        log.info(f"Discovered {len(progs)} programs: {[p['programName'] for p in progs]}")
        return progs

    def poll_events(self) -> list[dict]:
        """Poll for new/updated events."""
        all_events = self._get("/events")
        new_events = []
        for evt in all_events:
            evt_id = evt["id"]
            if evt_id not in self.active_events:
                self.active_events[evt_id] = evt
                new_events.append(evt)
                log.info(
                    f"New event: {evt.get('eventName', evt_id)} "
                    f"(program={evt.get('programID', 'none')})"
                )
                self._react_to_event(evt)
        return new_events

    def _react_to_event(self, event: dict):
        """React to an event by adjusting device state."""
        intervals = event.get("intervals", [])
        for interval in intervals:
            for payload in interval.get("payloads", []):
                ptype = payload.get("type", "")
                values = payload.get("values", [])
                if ptype == "IMPORT_CAPACITY_LIMIT" and values:
                    limit_kw = values[0]
                    log.info(f"  Applying import limit: {limit_kw} kW")
                    for dev in self.devices.values():
                        dev.apply_dispatch("down", limit_kw)

    def submit_status_report(self):
        """Submit per-resource status report (every 5 min → accelerated)."""
        self.report_interval_id += 1
        now = datetime.now(timezone.utc)

        resource_reports = []
        total_reading = 0.0
        total_shed_available = 0.0

        for name, dev in self.devices.items():
            dev.drift()
            payloads = [
                {"type": "OPERATING_STATE", "values": [dev.operating_state]},
                {"type": "DATA_QUALITY", "values": [dev.data_quality]},
                {"type": "READING", "values": [round(dev.reading_kw, 3)]},
                {"type": "LOAD_SHED_DELTA_AVAILABLE", "values": [round(dev.load_shed_available_kw, 3)]},
            ]
            if dev.res_type == "BATTERY":
                payloads.extend([
                    {"type": "STORAGE_CHARGE_LEVEL", "values": [round(dev.soc, 4)]},
                    {"type": "STORAGE_USABLE_CAPACITY", "values": [dev.usable_capacity_kwh]},
                    {"type": "STORAGE_MAX_DISCHARGE_POWER", "values": [dev.max_discharge_kw]},
                ])

            resource_reports.append({
                "resourceName": name,
                "intervals": [{
                    "id": self.report_interval_id,
                    "intervalPeriod": {
                        "start": now.isoformat(timespec="seconds"),
                        "duration": "PT0S",
                    },
                    "payloads": payloads,
                }],
            })
            total_reading += dev.reading_kw
            total_shed_available += dev.load_shed_available_kw

        # Aggregate report
        resource_reports.append({
            "resourceName": "AGGREGATED_REPORT",
            "intervals": [{
                "id": self.report_interval_id,
                "intervalPeriod": {
                    "start": now.isoformat(timespec="seconds"),
                    "duration": "PT0S",
                },
                "payloads": [
                    {"type": "OPERATING_STATE", "values": [self._aggregate_state()]},
                    {"type": "DATA_QUALITY", "values": ["ESTIMATED"]},
                    {"type": "READING", "values": [round(total_reading, 3)]},
                    {"type": "LOAD_SHED_DELTA_AVAILABLE", "values": [round(total_shed_available, 3)]},
                ],
            }],
        })

        report = {
            "programID": "prg-flex-readiness",
            "eventID": "evt-status-and-flex-per-resource",
            "clientName": self.ven_name,
            "resources": resource_reports,
        }
        self._post("/reports", report)
        log.info(
            f"Status report submitted: net={total_reading:.1f}kW, "
            f"shed_available={total_shed_available:.1f}kW"
        )

    def submit_forecast_report(self):
        """Submit 24h forecast (hourly intervals)."""
        now = datetime.now(timezone.utc)
        base_hour = now.replace(minute=0, second=0, microsecond=0)
        battery = self.devices.get("battery-01")
        soc = battery.soc if battery else 0.5

        intervals = []
        for h in range(24):
            hour_start = base_hour + timedelta(hours=h)
            # Simple sinusoidal forecast
            hour_of_day = (hour_start.hour + 1) % 24
            usage = 4.0 + 3.0 * math.sin((hour_of_day - 6) * math.pi / 12)
            shed = max(0, 8.0 + 4.0 * (soc - 0.3))
            dispatch_forecast = max(0, 3.0 * soc)
            projected_soc = max(0.1, soc - h * 0.02)

            intervals.append({
                "id": hour_start.hour,
                "intervalPeriod": {
                    "start": hour_start.isoformat(timespec="seconds"),
                    "duration": "PT1H",
                },
                "payloads": [
                    {"type": "USAGE_FORECAST", "values": [round(usage, 3)]},
                    {"type": "LOAD_SHED_DELTA_AVAILABLE", "values": [round(shed, 3)]},
                    {"type": "STORAGE_DISPATCH_FORECAST", "values": [round(dispatch_forecast, 3)]},
                    {"type": "STORAGE_CHARGE_LEVEL", "values": [round(projected_soc, 4)]},
                ],
            })

        report = {
            "programID": "prg-flex-readiness",
            "eventID": "evt-site-forecast",
            "clientName": self.ven_name,
            "resources": [{
                "resourceName": "AGGREGATED_REPORT",
                "intervals": intervals,
            }],
        }
        self._post("/reports", report)
        log.info(f"Forecast report submitted: {len(intervals)} hourly intervals")

    def _aggregate_state(self) -> str:
        """Determine aggregate operating state."""
        states = [d.operating_state for d in self.devices.values()]
        if any(s == "RUNNING_CURTAILED" for s in states):
            return "RUNNING_CURTAILED"
        if any(s == "RUNNING_HEIGHTENED" for s in states):
            return "RUNNING_HEIGHTENED"
        return "NORMAL"


def run_ven(vtn_url: str = "http://localhost:8088",
            client_id: str = "ven-home",
            ven_name: str = "demo-hems-ven",
            status_interval: float = 10.0,
            forecast_interval: float = 30.0,
            poll_interval: float = 5.0):
    """Run the VEN simulator."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    ven = VENSimulator(vtn_url, client_id, ven_name)

    # Wait for VTN to be ready
    for attempt in range(30):
        try:
            resp = httpx.get(f"{vtn_url}/", timeout=5)
            if resp.status_code == 200:
                log.info(f"VTN reachable at {vtn_url}")
                break
        except httpx.ConnectError:
            pass
        log.info(f"Waiting for VTN at {vtn_url}... (attempt {attempt + 1})")
        time.sleep(2)
    else:
        log.error(f"VTN not reachable at {vtn_url} after 60s")
        return

    # Phase 1: Authenticate + Register
    ven.authenticate()
    ven.register()
    ven.discover_programs()

    # Phase 2: Main loop — poll events + submit reports
    last_status = 0.0
    last_forecast = 0.0
    last_poll = 0.0

    log.info(f"VEN running: status every {status_interval}s, forecast every {forecast_interval}s, poll every {poll_interval}s")

    try:
        while True:
            now = time.time()

            if now - last_poll >= poll_interval:
                try:
                    ven.poll_events()
                except Exception as e:
                    log.warning(f"Event poll failed: {e}")
                last_poll = now

            if now - last_status >= status_interval:
                try:
                    ven.submit_status_report()
                except Exception as e:
                    log.warning(f"Status report failed: {e}")
                last_status = now

            if now - last_forecast >= forecast_interval:
                try:
                    ven.submit_forecast_report()
                except Exception as e:
                    log.warning(f"Forecast report failed: {e}")
                last_forecast = now

            time.sleep(1)

    except KeyboardInterrupt:
        log.info("VEN shutting down")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OpenADR 3.1 VEN Simulator")
    parser.add_argument("--vtn-url", default="http://localhost:8088", help="VTN base URL")
    parser.add_argument("--client-id", default="ven-home", help="OAuth client ID")
    parser.add_argument("--ven-name", default="demo-hems-ven", help="VEN name")
    args = parser.parse_args()
    run_ven(vtn_url=args.vtn_url, client_id=args.client_id, ven_name=args.ven_name)
