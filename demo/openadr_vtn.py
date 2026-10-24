"""OpenADR 3.1 Virtual Top Node (VTN).

Lightweight REST/JSON implementation of the OpenADR 3.1 VTN API.
Runs as a FastAPI server, providing the device-facing interface of the HEMS Backend.

Implements:
  - OAuth 2.0 client credentials (simplified)
  - VEN + resource registration
  - Programs (AT-flex-readiness, AT-grid-capacity, AT-awattar-spot)
  - Events (capacity limits, price signals, report requests)
  - Reports (telemetry, forecasts from VENs)
  - Subscriptions (optional)
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Header
from pydantic import BaseModel

log = logging.getLogger("openadr-vtn")

app = FastAPI(title="OpenADR 3.1 VTN", version="3.1.0")

# ── In-Memory Store ──────────────────────────────────────────────────────────

tokens: dict[str, dict] = {}  # token -> {client_id, expires}
vens: dict[str, dict] = {}    # ven_id -> ven object
resources: dict[str, list[dict]] = {}  # ven_id -> [resource objects]
programs: dict[str, dict] = {}   # program_id -> program object
events: dict[str, dict] = {}    # event_id -> event object
reports: list[dict] = []         # all submitted reports
subscriptions: dict[str, dict] = {}  # sub_id -> subscription object

# ── Pre-configured Programs (matching AT reference implementation) ──────────

_DEFAULT_PROGRAMS = [
    {
        "id": "prg-flex-readiness",
        "programName": "AT-flex-readiness",
        "programType": "FLEX_READINESS",
        "country": "AT",
        "description": "Flex readiness reporting: VEN submits status, capability, and forecast reports",
    },
    {
        "id": "prg-grid-capacity",
        "programName": "AT-grid-capacity",
        "programType": "GRID_CAPACITY",
        "country": "AT",
        "description": "Grid capacity limits: VTN sends import/export limits to VEN",
    },
    {
        "id": "prg-awattar-spot",
        "programName": "AT-awattar-spot",
        "programType": "ELECTRICITY_PRICE",
        "country": "AT",
        "description": "Day-ahead spot prices from aWATTar",
    },
]


def _init_programs():
    for p in _DEFAULT_PROGRAMS:
        programs[p["id"]] = p


def _init_default_events():
    """Seed standing events that external VENs can poll at startup."""
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = (today + timedelta(days=1)).isoformat(timespec="seconds")
    now_iso = now.isoformat(timespec="seconds")

    default_events = [
        # ── Report request: status every 5 min, per resource ──
        {
            "id": "evt-status-and-flex-per-resource",
            "programID": "prg-flex-readiness",
            "eventName": "status-and-flex-per-resource",
            "priority": 10,
            "intervalPeriod": {"start": now_iso, "duration": "PT5M"},
            "reportDescriptors": [
                {"payloadType": "OPERATING_STATE", "startInterval": 0, "numIntervals": 1, "historical": False, "frequency": 1, "repeat": -1},
                {"payloadType": "DATA_QUALITY", "startInterval": 0, "numIntervals": 1, "historical": False, "frequency": 1, "repeat": -1},
                {"payloadType": "READING", "startInterval": 0, "numIntervals": 1, "historical": False, "frequency": 1, "repeat": -1},
                {"payloadType": "LOAD_SHED_DELTA_AVAILABLE", "startInterval": 0, "numIntervals": 1, "historical": False, "frequency": 1, "repeat": -1},
                {"payloadType": "STORAGE_CHARGE_LEVEL", "startInterval": 0, "numIntervals": 1, "historical": False, "frequency": 1, "repeat": -1},
                {"payloadType": "STORAGE_USABLE_CAPACITY", "startInterval": 0, "numIntervals": 1, "historical": False, "frequency": 1, "repeat": -1},
                {"payloadType": "STORAGE_MAX_CHARGE_POWER", "startInterval": 0, "numIntervals": 1, "historical": False, "frequency": 1, "repeat": -1},
                {"payloadType": "STORAGE_MAX_DISCHARGE_POWER", "startInterval": 0, "numIntervals": 1, "historical": False, "frequency": 1, "repeat": -1},
            ],
        },
        # ── Report request: 24h forecast, hourly ──
        {
            "id": "evt-site-forecast",
            "programID": "prg-flex-readiness",
            "eventName": "site-forecast",
            "priority": 10,
            "intervalPeriod": {"start": now_iso, "duration": "PT1H"},
            "reportDescriptors": [
                {"payloadType": "USAGE_FORECAST", "units": "KWH", "readingType": "FORECAST", "aggregate": True,
                 "startInterval": -1, "numIntervals": 24, "historical": False, "frequency": 1, "repeat": -1},
                {"payloadType": "LOAD_SHED_DELTA_AVAILABLE", "units": "KW", "readingType": "FORECAST", "aggregate": True,
                 "startInterval": -1, "numIntervals": 24, "historical": False, "frequency": 1, "repeat": -1},
                {"payloadType": "STORAGE_DISPATCH_FORECAST", "units": "KW", "readingType": "FORECAST", "aggregate": True,
                 "startInterval": -1, "numIntervals": 24, "historical": False, "frequency": 1, "repeat": -1},
                {"payloadType": "STORAGE_CHARGE_LEVEL", "readingType": "FORECAST", "aggregate": True,
                 "startInterval": -1, "numIntervals": 24, "historical": False, "frequency": 1, "repeat": -1},
            ],
        },
        # ── Day-ahead prices (24 hourly slots, simulated) ──
        {
            "id": "evt-day-ahead-prices",
            "programID": "prg-awattar-spot",
            "eventName": f"day-ahead-{(today + timedelta(days=1)).strftime('%Y-%m-%d')}",
            "priority": 10,
            "payloadDescriptors": [
                {"objectType": "EVENT_PAYLOAD_DESCRIPTOR", "payloadType": "PRICE", "units": "KWH", "currency": "EUR"},
                {"objectType": "EVENT_PAYLOAD_DESCRIPTOR", "payloadType": "SIMPLE"},
            ],
            "intervalPeriod": {"start": tomorrow_start, "duration": "PT1H"},
            "intervals": _generate_price_intervals(),
        },
        # ── Default import capacity limit (standing, low priority) ──
        {
            "id": "evt-default-import-limit",
            "programID": "prg-grid-capacity",
            "eventName": "default-import-limit",
            "priority": 100,
            "payloadDescriptors": [
                {"objectType": "EVENT_PAYLOAD_DESCRIPTOR", "payloadType": "IMPORT_CAPACITY_LIMIT", "units": "KW"},
            ],
            "intervalPeriod": {"start": now_iso, "duration": "P9999Y"},
            "intervals": [{"id": 0, "payloads": [{"type": "IMPORT_CAPACITY_LIMIT", "values": [8.0]}]}],
        },
        # ── Default export capacity limit (standing, low priority) ──
        {
            "id": "evt-default-export-limit",
            "programID": "prg-grid-capacity",
            "eventName": "default-export-limit",
            "priority": 100,
            "payloadDescriptors": [
                {"objectType": "EVENT_PAYLOAD_DESCRIPTOR", "payloadType": "EXPORT_CAPACITY_LIMIT", "units": "KW"},
            ],
            "intervalPeriod": {"start": now_iso, "duration": "P9999Y"},
            "intervals": [{"id": 0, "payloads": [{"type": "EXPORT_CAPACITY_LIMIT", "values": [3.0]}]}],
        },
    ]

    for evt in default_events:
        evt.setdefault("createdDateTime", now.isoformat(timespec="seconds"))
        evt.setdefault("modificationDateTime", now.isoformat(timespec="seconds"))
        events[evt["id"]] = evt


def _generate_price_intervals() -> list[dict]:
    """Generate 24 hourly price intervals with realistic Austrian day-ahead shape."""
    import random as _rnd
    # Typical Austrian autumn price curve (€/kWh): low overnight, peaks at 8h and 18h
    base_prices = [
        0.08, 0.07, 0.06, 0.06, 0.07, 0.09,   # 00–05: overnight low
        0.12, 0.16, 0.19, 0.17, 0.15, 0.14,     # 06–11: morning ramp + peak
        0.13, 0.12, 0.13, 0.15, 0.18, 0.22,     # 12–17: midday dip, evening ramp
        0.24, 0.20, 0.16, 0.13, 0.10, 0.08,     # 18–23: evening peak, wind down
    ]
    intervals = []
    for h, base in enumerate(base_prices):
        price = round(base + _rnd.uniform(-0.01, 0.01), 4)
        # SIMPLE: 0=cheap, 1=normal, 2=expensive, 3=critical
        if price < 0.09:
            simple = 0
        elif price < 0.15:
            simple = 1
        elif price < 0.20:
            simple = 2
        else:
            simple = 3
        intervals.append({
            "id": h,
            "payloads": [
                {"type": "PRICE", "values": [price]},
                {"type": "SIMPLE", "values": [simple]},
            ],
        })
    return intervals


_init_programs()
_init_default_events()


# ── Auth ─────────────────────────────────────────────────────────────────────


class TokenRequest(BaseModel):
    grant_type: str = "client_credentials"
    client_id: str
    client_secret: str = ""


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600


def _verify_token(authorization: str = Header(None)) -> str:
    """Simplified token verification."""
    if not authorization:
        raise HTTPException(401, "Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(401, "Invalid Authorization header")
    token = parts[1]
    if token not in tokens:
        raise HTTPException(401, "Invalid or expired token")
    info = tokens[token]
    if info["expires"] < time.time():
        del tokens[token]
        raise HTTPException(401, "Token expired")
    return info["client_id"]


@app.get("/auth/server")
def auth_server():
    """OAuth 2.0 server discovery (OpenADR 3.1 §6.2)."""
    return {"tokenURL": "/auth/token"}


@app.post("/auth/token", response_model=TokenResponse)
def create_token(req: TokenRequest):
    """OAuth 2.0 client credentials grant (simplified)."""
    token = str(uuid.uuid4())
    tokens[token] = {
        "client_id": req.client_id,
        "expires": time.time() + 3600,
    }
    log.info(f"Token issued for client_id={req.client_id}")
    return TokenResponse(access_token=token)


# ── VENs ─────────────────────────────────────────────────────────────────────


@app.get("/vens")
def list_vens(_client: str = Depends(_verify_token)):
    return list(vens.values())


@app.post("/vens", status_code=201)
def register_ven(body: dict, _client: str = Depends(_verify_token)):
    ven_id = f"ven-{str(uuid.uuid4())[:8]}"
    ven = {
        "id": ven_id,
        "createdDateTime": datetime.now(timezone.utc).isoformat(),
        "modificationDateTime": datetime.now(timezone.utc).isoformat(),
        **body,
    }
    vens[ven_id] = ven
    resources[ven_id] = []
    log.info(f"VEN registered: {ven.get('venName', ven_id)} (id={ven_id})")
    return ven


@app.get("/vens/{ven_id}")
def get_ven(ven_id: str, _client: str = Depends(_verify_token)):
    if ven_id not in vens:
        raise HTTPException(404, f"VEN {ven_id} not found")
    return vens[ven_id]


# ── Resources ────────────────────────────────────────────────────────────────


@app.get("/vens/{ven_id}/resources")
def list_resources(ven_id: str, _client: str = Depends(_verify_token)):
    if ven_id not in vens:
        raise HTTPException(404, f"VEN {ven_id} not found")
    return resources.get(ven_id, [])


@app.post("/vens/{ven_id}/resources", status_code=201)
def register_resource(ven_id: str, body: dict, _client: str = Depends(_verify_token)):
    if ven_id not in vens:
        raise HTTPException(404, f"VEN {ven_id} not found")
    res_id = f"res-{str(uuid.uuid4())[:8]}"
    resource = {
        "id": res_id,
        "createdDateTime": datetime.now(timezone.utc).isoformat(),
        "venID": ven_id,
        **body,
    }
    resources[ven_id].append(resource)
    log.info(f"Resource registered: {resource.get('resourceName', res_id)} for VEN {ven_id}")
    return resource


# ── Programs ─────────────────────────────────────────────────────────────────


@app.get("/programs")
def list_programs(_client: str = Depends(_verify_token)):
    return list(programs.values())


@app.get("/programs/{program_id}")
def get_program(program_id: str, _client: str = Depends(_verify_token)):
    if program_id not in programs:
        raise HTTPException(404, f"Program {program_id} not found")
    return programs[program_id]


# ── Events ───────────────────────────────────────────────────────────────────


@app.get("/events")
def list_events(
    programID: str | None = None,
    _client: str = Depends(_verify_token),
):
    result = list(events.values())
    if programID:
        result = [e for e in result if e.get("programID") == programID]
    return result


@app.post("/events", status_code=201)
def create_event(body: dict, _client: str = Depends(_verify_token)):
    event_id = f"evt-{str(uuid.uuid4())[:8]}"
    event = {
        "id": event_id,
        "createdDateTime": datetime.now(timezone.utc).isoformat(),
        "modificationDateTime": datetime.now(timezone.utc).isoformat(),
        **body,
    }
    events[event_id] = event
    log.info(
        f"Event created: {event.get('eventName', event_id)} "
        f"(program={event.get('programID', 'none')})"
    )
    return event


@app.get("/events/{event_id}")
def get_event(event_id: str, _client: str = Depends(_verify_token)):
    if event_id not in events:
        raise HTTPException(404, f"Event {event_id} not found")
    return events[event_id]


@app.put("/events/{event_id}")
def update_event(event_id: str, body: dict, _client: str = Depends(_verify_token)):
    if event_id not in events:
        raise HTTPException(404, f"Event {event_id} not found")
    events[event_id].update(body)
    events[event_id]["modificationDateTime"] = datetime.now(timezone.utc).isoformat()
    return events[event_id]


@app.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: str, _client: str = Depends(_verify_token)):
    if event_id not in events:
        raise HTTPException(404, f"Event {event_id} not found")
    del events[event_id]
    log.info(f"Event deleted: {event_id}")


# ── Reports ──────────────────────────────────────────────────────────────────


@app.get("/reports")
def list_reports(
    programID: str | None = None,
    _client: str = Depends(_verify_token),
):
    result = reports
    if programID:
        result = [r for r in result if r.get("programID") == programID]
    return result[-100:]  # last 100 reports


@app.post("/reports", status_code=201)
def create_report(body: dict, _client: str = Depends(_verify_token)):
    report_id = f"rpt-{str(uuid.uuid4())[:8]}"
    report = {
        "id": report_id,
        "createdDateTime": datetime.now(timezone.utc).isoformat(),
        **body,
    }
    reports.append(report)
    log.info(
        f"Report received: {report.get('programID', 'unknown')} "
        f"from {report.get('clientName', 'unknown')} "
        f"({len(report.get('resources', []))} resources)"
    )
    return report


# ── Subscriptions ────────────────────────────────────────────────────────────


@app.get("/subscriptions")
def list_subscriptions(_client: str = Depends(_verify_token)):
    return list(subscriptions.values())


@app.post("/subscriptions", status_code=201)
def create_subscription(body: dict, _client: str = Depends(_verify_token)):
    sub_id = f"sub-{str(uuid.uuid4())[:8]}"
    sub = {"id": sub_id, **body}
    subscriptions[sub_id] = sub
    log.info(f"Subscription created: {sub_id}")
    return sub


# ── Health / Info ────────────────────────────────────────────────────────────


@app.get("/")
def root():
    return {
        "name": "Grid-Serving Storage VTN",
        "version": "3.1.0",
        "spec": "OpenADR 3.1",
        "programs": len(programs),
        "vens": len(vens),
        "events": len(events),
    }


# ── Internal API (for HEMS Backend integration) ─────────────────────────────

@app.get("/internal/state")
def internal_state():
    """Debug endpoint: full VTN state (no auth)."""
    return {
        "vens": vens,
        "resources": resources,
        "programs": programs,
        "events": events,
        "reports_count": len(reports),
        "last_reports": reports[-5:] if reports else [],
    }


# ── Entry Point ──────────────────────────────────────────────────────────────


def run_vtn(host: str = "0.0.0.0", port: int = 8088):
    """Run the VTN server."""
    import uvicorn
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )
    log.info(f"OpenADR 3.1 VTN starting on {host}:{port}")
    log.info(f"Programs: {[p['programName'] for p in programs.values()]}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OpenADR 3.1 VTN")
    parser.add_argument("--host", default="0.0.0.0", help="Listen address")
    parser.add_argument("--port", type=int, default=8088, help="Listen port")
    args = parser.parse_args()
    run_vtn(host=args.host, port=args.port)
