# Grid-Serving Storage Demo

Live simulation of the four-phase interoperability profile: **Observe → Plan → Dispatch → Settle**.

Three simulated HEMS backends publish state and flexibility offers over MQTT. A Technical Aggregator observes the portfolio, runs a MILP optimizer to allocate a grid obligation across backends, dispatches goals, and collects delivery reports. Each backend runs its own device-level MILP to distribute the received goal across simulated devices, logging the OpenADR interactions that would occur on the device interface.

## What It Demonstrates

| Phase | What happens | Protocol |
|---|---|---|
| **Observe** | HEMS Backends publish `SiteStateSnapshot` + `SiteFlexOffer` (power, SoC, flex envelope, constraints, reliability) | MQTT (bottom-up) |
| **Plan** | Aggregator runs portfolio-level MILP: meet 200 kW grid obligation, penalize unreliable backends, respect per-backend constraints | Internal (PuLP + HiGHS) |
| **Dispatch** | Aggregator publishes `AggregatorDispatch` per backend. Each backend runs device-level MILP, distributes across devices, logs simulated OpenADR `oadrDistributeEvent` per device, publishes `DispatchAck` | MQTT (top-down) + simulated OpenADR |
| **Settle** | Aggregator publishes `FlexRelease`. Backends generate `DeliveryReport` with requested vs. delivered kWh and delivery ratio | MQTT |

### Two-Level MILP (the AI angle)

The demo runs real optimization at two levels:

1. **Aggregator MILP** — treats each backend as an opaque flexibility envelope. Decides how much to request from each backend to meet a grid obligation while minimizing dispatch to unreliable backends.
2. **Backend MILP** — treats each device as a decision variable. Distributes the aggregator's goal across devices respecting per-device SoC, battery limits, and ramp rates.

Both use PuLP with the HiGHS solver — real mixed-integer linear programming, not random allocation.

## Prerequisites

- Python 3.12+
- An MQTT broker on `localhost:1883` (e.g., Mosquitto)

If you don't have a broker running, start one with Docker:

```bash
cd ..  # project root
docker compose up -d
```

## Setup

```bash
cd demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the Demo

### Full demo with dashboard

```bash
python3 run_demo.py
```

This starts a Rich terminal dashboard that shows all four phases live:

- **Portfolio panel** — per-backend state (devices, net power, flex down/up, confidence, reliability)
- **MQTT log** — color-coded messages (cyan=observe, yellow=plan/dispatch, magenta=execute, green=settle)
- **Dispatch panel** — MILP allocation per backend with ACK status
- **Settlement panel** — delivery ratio per backend after release

The demo runs through the full cycle in about 50 seconds (accelerated from real-world timescales):

| Demo phase | Duration | Real-world equivalent |
|---|---|---|
| Observe | 15s | Minutes to hours of continuous monitoring |
| Plan + Dispatch | ~2s | Seconds (MILP solve + MQTT publish) |
| Execute | 20s | 15–120 minutes of active flex delivery |
| Settle | ~3s | Post-event settlement |

### Running components separately

For debugging or to watch raw MQTT traffic:

**Terminal 1 — backends:**
```bash
python3 backend_simulator.py
```

**Terminal 2 — aggregator:**
```bash
python3 aggregator.py
```

**Terminal 3 — raw MQTT (optional):**
```bash
mosquitto_sub -t '#' -v
```

## Simulated Portfolio

| Backend | Type | Devices | Avg Battery | Avg PV |
|---|---|---|---|---|
| `kern-01` | Residential | 47 | 5 kW / 10 kWh | 8 kWp |
| `solar-02` | Commercial | 12 | 25 kW / 50 kWh | 40 kWp |
| `flex-03` | Mixed | 25 | 8 kW / 15 kWh | 12 kWp |

Each device has randomized SoC (25–90%), consumption, PV output, and prosumer-configured min/max SoC floors. Devices drift over time to simulate changing conditions.

## MQTT Topic Structure

```
agg-01/
├── observe/
│   └── {backend_id}/
│       ├── state              ← SiteStateSnapshot (periodic)
│       └── flex               ← SiteFlexOffer (periodic)
├── dispatch/
│   └── seg-LA-0142/
│       ├── request            ← AggregatorDispatch
│       ├── ack/{backend_id}   ← DispatchAck
│       ├── status/{backend_id}← FlexStatus (during execution)
│       └── release            ← FlexRelease
└── settle/
    └── {backend_id}/
        └── {dispatch_id}      ← DeliveryReport
```

## Configuration

Edit `config.py` to adjust:

- `OBSERVATION_WINDOW_S` — how long to observe before triggering (default: 15s)
- `DISPATCH_DURATION_S` — how long the dispatch lasts (default: 20s)
- `GRID_OBLIGATION_KW` — simulated grid obligation (default: 200 kW)
- `GRID_OBLIGATION_DIRECTION` — `"down"` (reduce) or `"up"` (increase)
- `BACKENDS` — add/remove/modify simulated backends

## File Overview

| File | Lines | Purpose |
|---|---|---|
| `config.py` | Config | Shared constants, topic patterns, backend definitions |
| `models.py` | Data | Dataclasses for all MQTT message types |
| `backend_simulator.py` | Sim | Simulates HEMS backends + devices, device-level MILP |
| `aggregator.py` | Core | Technical Aggregator with portfolio MILP |
| `run_demo.py` | UI | Orchestrator + Rich terminal dashboard |

## What's Real vs. Simulated

| Component | Status |
|---|---|
| MQTT broker + message flow | **Real** — live Mosquitto, real pub/sub |
| Aggregator MILP | **Real** — PuLP + HiGHS solver |
| Backend device MILP | **Real** — PuLP + HiGHS solver |
| Device state (SoC, power) | **Simulated** — randomized with realistic drift |
| OpenADR VTN→VEN events | **Simulated** — logged in-process, not real HTTP/XML |
| Flexibility envelopes | **Simulated** — computed from device state, not learned from historical data |
| Market triggers | **Simulated** — auto-triggered after observation window |
