# Grid-Serving Storage Demo

Live simulation of the four-phase interoperability profile: **Observe → Plan → Dispatch → Settle**.

Three simulated HEMS backends publish state and flexibility offers over MQTT. A Technical Aggregator observes the portfolio, runs a MILP optimizer to allocate a grid obligation across backends, dispatches goals, and collects delivery reports. Each backend runs its own device-level MILP to distribute the received goal across simulated devices, logging the OpenADR interactions that would occur on the device interface.

Each entity runs as its own process (or container), communicating only via MQTT — true separation of concerns. A browser dashboard connects via MQTT websockets and provides live charts and interactive dispatch controls.

## What It Demonstrates

| Phase | What happens | Protocol |
|---|---|---|
| **Observe** | HEMS Backends publish `SiteStateSnapshot` + `SiteFlexOffer` (power, SoC, flex envelope, constraints, reliability) | MQTT (bottom-up) |
| **Plan** | Aggregator runs portfolio-level MILP: meet grid obligation, penalize unreliable backends, respect per-backend constraints | Internal (PuLP + HiGHS) |
| **Dispatch** | Aggregator publishes `AggregatorDispatch` per backend. Each backend runs device-level MILP, distributes across devices, logs simulated OpenADR `oadrDistributeEvent` per device, publishes `DispatchAck` | MQTT (top-down) + simulated OpenADR |
| **Settle** | Aggregator publishes `FlexRelease`. Backends generate `DeliveryReport` with requested vs. delivered kWh and delivery ratio | MQTT |

### Two-Level MILP (the AI angle)

The demo runs real optimization at two levels:

1. **Aggregator MILP** — treats each backend as an opaque flexibility envelope. Decides how much to request from each backend to meet a grid obligation while minimizing dispatch to unreliable backends.
2. **Backend MILP** — treats each device as a decision variable. Distributes the aggregator's goal across devices respecting per-device SoC, battery limits, and ramp rates.

Both use PuLP with the HiGHS solver — real mixed-integer linear programming, not random allocation.

## Prerequisites

- Python 3.12+
- An MQTT broker with websocket support (port 1883 for MQTT, port 9001 for websockets)

## Setup

### Option A: Python virtual environment (use existing MQTT broker)

```bash
cd demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Option B: Docker Compose (spins up everything including the broker)

```bash
# From project root
docker compose up --build
```

This starts:
- `mosquitto` — MQTT broker (port 1883 + 9001/websockets)
- `backend-kern-01` — HEMS backend simulator for kern-01 (47 residential devices)
- `backend-solar-02` — HEMS backend simulator for solar-02 (12 commercial devices)
- `backend-flex-03` — HEMS backend simulator for flex-03 (25 mixed devices)
- `aggregator` — Technical Aggregator in continuous mode

Then open `demo/dashboard.html` in your browser.

## Running the Demo

There are two modes: a quick single-process demo for presentations, and a continuous multi-process mode for interactive exploration.

### Mode 1: Quick demo (single process, ~50 seconds)

```bash
python3 run_demo.py
```

Runs the full Observe → Plan → Dispatch → Settle cycle once with detailed terminal output:
- Portfolio state table after observation
- MILP allocation result
- Dispatch acknowledgments
- Execution summary with SoC drift
- Settlement delivery reports
- Per-entity decision trace (what each backend knew, decided, and the impact)
- Conclusions and takeaways

| Demo phase | Duration | Real-world equivalent |
|---|---|---|
| Observe | 15s | Minutes to hours of continuous monitoring |
| Plan + Dispatch | ~2s | Seconds (MILP solve + MQTT publish) |
| Execute | 20s | 15–120 minutes of active flex delivery |
| Settle | ~3s | Post-event settlement |

### Mode 2: Continuous (separate entities, interactive)

Each entity runs as its own process. The aggregator runs continuously and dispatches are triggered interactively via the browser dashboard.

**Start the backends (one terminal per backend, or background them):**
```bash
python3 backend_simulator.py --backend-id kern-01
python3 backend_simulator.py --backend-id solar-02
python3 backend_simulator.py --backend-id flex-03
```

**Start the aggregator:**
```bash
python3 aggregator.py --mode continuous
```

**Open the browser dashboard:**
```bash
# Option A: open directly
xdg-open dashboard.html

# Option B: serve via HTTP (needed if browser blocks file:// websockets)
python3 -m http.server 8080
# then open http://localhost:8080/dashboard.html
```

Or with Docker Compose (starts everything at once):
```bash
docker compose up --build
# then open demo/dashboard.html
```

### Browser Dashboard

The dashboard connects to the MQTT broker via websockets (port 9001) and shows:

**Live charts:**
- Per-backend time-series: net power with flex envelope as a shaded band (red=flex_down floor, green=flex_up ceiling)
- Portfolio-level flexibility: total flex_down + flex_up over time vs. obligation line
- Dispatch bar chart: allocated vs. accepted vs. delivered per backend

**Interactive controls:**
- **Obligation slider** (50–500 kW) — set the grid obligation
- **Direction toggle** — down (reduce consumption) or up (increase consumption)
- **Reason selector** — congestion, mFRR activation, market position, peak shaving
- **Trigger Dispatch** button — publishes to `agg-01/command/dispatch` via MQTT, the aggregator runs its MILP and dispatches
- **Release** button — publishes to `agg-01/command/release`, triggers settlement

**Aggregator state KPIs** (top right):
- Backends online, total flex down/up, current phase (observe/dispatch)
- Buttons auto-disable based on state (can't dispatch while one is active)

**Event log:**
- Color-coded MQTT messages: cyan=observe, yellow=dispatch, magenta=execute, green=settle

**Conclusions panel:**
- Appears after settlement with 5 takeaways (two-level MILP, reliability-weighted dispatch, prosumer sovereignty, delivery verification, privacy)

The dashboard requires websocket access to the MQTT broker on port 9001. If using your own Mosquitto, ensure `mosquitto.conf` includes:
```
listener 9001
protocol websockets
allow_anonymous true
```

### Running all backends in one process

For quick testing without Docker or multiple terminals:

```bash
# All 3 backends in one process
python3 backend_simulator.py

# Aggregator in oneshot mode (single cycle then exit)
python3 aggregator.py --mode oneshot
```

### Watching raw MQTT traffic

```bash
mosquitto_sub -t '#' -v
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Separate processes / containers                             │
│                                                              │
│  backend-kern-01  ──┐                                        │
│  backend-solar-02 ──┼── MQTT ──► mosquitto ◄── MQTT ── aggregator
│  backend-flex-03  ──┘           (1883+9001)                  │
│                                     ▲                        │
│                                     │ websockets             │
│                                 dashboard.html               │
│                                 (browser)                    │
└─────────────────────────────────────────────────────────────┘
```

Each entity only knows about MQTT topics — true separation of concerns. The dashboard reads all topics and publishes commands.

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
├── observe/                          ← Phase 1: bottom-up state
│   └── {backend_id}/
│       ├── state                        SiteStateSnapshot (periodic)
│       └── flex                         SiteFlexOffer (periodic)
├── dispatch/                         ← Phase 3: top-down goals
│   └── seg-LA-0142/
│       ├── request                      AggregatorDispatch
│       ├── ack/{backend_id}             DispatchAck
│       ├── status/{backend_id}          FlexStatus (during execution)
│       └── release                      FlexRelease
├── settle/                           ← Phase 4: settlement
│   └── {backend_id}/
│       └── {dispatch_id}                DeliveryReport
├── command/                          ← Interactive control
│   ├── dispatch                         Trigger dispatch (from dashboard)
│   └── release                          Trigger release (from dashboard)
└── state/
    └── portfolio                     ← Aggregator state (retained)
```

## CLI Reference

### backend_simulator.py

```
python3 backend_simulator.py [--backend-id ID] [--broker HOST]

Options:
  --backend-id   Run a single backend (e.g. kern-01). Default: run all.
  --broker       MQTT broker host. Default: localhost
```

### aggregator.py

```
python3 aggregator.py [--mode MODE] [--broker HOST]

Options:
  --mode         continuous (default) or oneshot
  --broker       MQTT broker host. Default: localhost

Continuous mode:
  Runs forever. Dispatch triggered via MQTT command topic.
  Publishes portfolio state every 5s to agg-01/state/portfolio.

Oneshot mode:
  Observe → dispatch → settle → exit. Original demo behavior.
```

## Configuration

Edit `config.py` to adjust:

- `SNAPSHOT_INTERVAL_S` — backend state publish interval (default: 3s)
- `FLEX_OFFER_INTERVAL_S` — flex offer publish interval (default: 5s)
- `OBSERVATION_WINDOW_S` — observe window in oneshot mode (default: 15s)
- `DISPATCH_DURATION_S` — dispatch duration in oneshot mode (default: 20s)
- `GRID_OBLIGATION_KW` — default obligation (default: 200 kW, overridable from dashboard)
- `GRID_OBLIGATION_DIRECTION` — `"down"` or `"up"` (overridable from dashboard)
- `BACKENDS` — add/remove/modify simulated backends

## File Overview

| File | Purpose |
|---|---|
| `config.py` | Shared constants, topic patterns, backend definitions |
| `models.py` | Dataclasses for all MQTT message types |
| `backend_simulator.py` | HEMS backend simulator + device-level MILP |
| `aggregator.py` | Technical Aggregator with portfolio MILP + command handling |
| `run_demo.py` | Single-process orchestrator with Rich terminal output |
| `dashboard.html` | Browser dashboard with live charts + interactive controls |
| `Dockerfile` | Container image for Python services |
| `requirements.txt` | Python dependencies |
| `../docker-compose.yml` | Orchestrates all containers (broker + 3 backends + aggregator) |
| `../mosquitto.conf` | Mosquitto config with MQTT + websocket listeners |

## What's Real vs. Simulated

| Component | Status |
|---|---|
| MQTT broker + message flow | **Real** — live Mosquitto, real pub/sub |
| Aggregator MILP | **Real** — PuLP + HiGHS solver |
| Backend device MILP | **Real** — PuLP + HiGHS solver |
| MQTT command trigger | **Real** — dashboard publishes to command topic, aggregator reacts |
| Browser dashboard | **Real** — live MQTT websocket subscription, Chart.js rendering |
| Device state (SoC, power) | **Simulated** — randomized with realistic drift |
| OpenADR VTN→VEN events | **Simulated** — logged in-process, not real HTTP/XML |
| Flexibility envelopes | **Simulated** — computed from device state, not learned from historical data |
| Market triggers | **Simulated** — interactive via dashboard or auto-triggered in oneshot mode |
