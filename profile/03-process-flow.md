# 03 — Process Flow

## Overview

The grid-serving storage system operates as a **continuous four-phase loop**: Observe → Plan → Dispatch → Settle. The architecture has two distinct communication segments:
- **Aggregator ↔ HEMS Backend**: MQTT v5
- **HEMS Backend ↔ HEMS Device**: OpenADR 2.0b (VTN ↔ VEN)

**This process flow applies identically across all serviceable markets.** Whether the trigger is a DSO congestion signal, an mFRR activation from APG, an intraday market position, or a local flexibility market clearing — the dispatch cycle is the same. Only the upstream trigger differs.

Two levels of optimization (MILP) operate at different granularities:
- **Aggregator MILP**: distributes goals across HEMS Backends (sees backends as opaque flexibility envelopes)
- **Backend MILP**: distributes received goals across individual HEMS devices (sees device-level constraints)

### Timing Context

| Market | Available Response Time | Signal Chain (~5–10s) | Headroom |
|---|---|---|---|
| **mFRR** | 12.5 min (FAT) | ~10s | ~12 min |
| **Congestion management** | Minutes (DSO-dependent) | ~10s | Minutes |
| **Intraday** | ≥5 min (gate closure) | ~10s | Minutes |
| **Day-ahead** | Hours | ~10s | Hours |

Tier 1 markets (FCR: 30s, aFRR: 5 min with 4s setpoint cycle) cannot be served through this process — they require dedicated SCADA/PLC control loops that bypass the HEMS backend stack.

---

## Phase 1 — Observe (Continuous, Bottom-Up)

HEMS devices continuously report state upward. HEMS Backends aggregate and publish to the aggregator.

### Sequence Diagram

```
  HEMS Device        HEMS Backend              MQTT Broker         Tech. Aggregator
  (VEN)              (VTN)                                         
   │                    │                          │                    │
   │  ┌─────────────────┤                          │                    │
   │  │ Periodic cycle  │                          │                    │
   │  │ (60s – 5min)    │                          │                    │
   │  └─────────────────┤                          │                    │
   │                    │                          │                    │
   │──OpenADR report───▶│                          │                    │
   │  (power, SoC,      │                          │                    │
   │   device state)    │                          │                    │
   │                    │                          │                    │
   │                    │  Aggregate across         │                    │
   │                    │  all managed devices      │                    │
   │                    │                          │                    │
   │                    │──SiteStateSnapshot───────▶│───────────────────▶│
   │                    │  (MQTT)                   │                    │  Store snapshot
   │                    │                          │                    │
   │                    │──SiteFlexOffer───────────▶│───────────────────▶│
   │                    │  (MQTT)                   │                    │  Update portfolio
   │                    │  (envelope, constraints,  │                    │  flex model
   │                    │   forecast, reliability)  │                    │
   │                    │                          │                    │
   │                    │                          │                    │
   │  ┌─────────────────┤  ... repeats every cycle  │                    │
```

### What Flows Bottom-Up

| Message | From | To | Content | Frequency |
|---|---|---|---|---|
| **Device state** | HEMS Device | HEMS Backend | Power (W), SoC (%), mode, device health | Per device reporting interval |
| **SiteStateSnapshot** | HEMS Backend | Aggregator | Aggregated power (import/export/net/production/consumption), energy counters, grid quality, availability | 60s – 5 min |
| **SiteFlexOffer** | HEMS Backend | Aggregator | Flexibility envelope (baseline, flex_up, flex_down, min/max power), constraints (ramp rates, activation lead time, min/max duration, rebound), 24h forecast, reliability score | Alongside snapshot or on forecast refresh |

### Key Properties

- The HEMS Backend **aggregates** individual device data into a site-level view — the aggregator never sees per-device data (privacy, scalability)
- Flexibility potentials (flex_up, flex_down) are **measured and learned** from the actual ramp behavior of locally managed devices, not just nameplate capacity
- Constraints (ramp rates, rebound) are **derived from observed device behavior** — they represent what the site can actually deliver, not theoretical limits
- The aggregator maintains two views: a **dashboard view** (pre-aggregated KPIs) and a **MILP input view** (per-backend disaggregated data for optimization)

---

## Phase 2 — Plan (Aggregator-Internal)

The aggregator uses observed state and flex offers to optimize its market interactions.

### Sequence Diagram

```
  Market / DSO          Tech. Aggregator                    (internal)
                        
   │                        │                                
   │                        │  ┌──────────────────────────┐  
   │                        │  │ Continuous planning loop  │  
   │                        │  │                          │  
   │                        │  │ 1. Assess portfolio:     │  
   │                        │  │    - Total flex_up/down   │  
   │                        │  │    - Per-backend capacity │  
   │                        │  │    - Reliability scores   │  
   │                        │  │                          │  
   │                        │  │ 2. Market positioning:    │  
   │──market signals───────▶│  │    - mFRR availability    │  
   │──grid stress signals──▶│  │    - Intraday positions   │  
   │                        │  │    - Congestion readiness  │  
   │                        │  │                          │  
   │                        │  │ 3. Run Aggregator MILP:   │  
   │                        │  │    - Inputs: per-backend  │  
   │                        │  │      SiteFlexOffer data   │  
   │                        │  │    - Objective: meet       │  
   │                        │  │      market obligations,  │  
   │                        │  │      minimize peak,       │  
   │                        │  │      penalize unreliable  │  
   │                        │  │    - Output: dispatch      │  
   │                        │  │      plan (up/down per    │  
   │                        │  │      backend per slot)    │  
   │                        │  │                          │  
   │                        │  └──────────────────────────┘  
   │                        │                                
   │                        │──── triggers Phase 3 ────▶     
```

### Aggregator MILP Role

The aggregator's MILP treats each HEMS Backend as a **single decision variable** with an associated flexibility envelope and constraints. It does NOT see individual devices.

**Inputs** (from Phase 1):
- Per-backend: baseline_kw, flex_up_kw, flex_down_kw, ramp rates, min/max duration, rebound factor, reliability score, 24h forecast
- Market obligations: mFRR calls, intraday commitments, DSO congestion signals

**Output**:
- Per-backend dispatch goals: direction (up/down), target_delta_kw, time-series schedule
- These become the `AggregatorDispatch` messages in Phase 3

**Key**: The MILP is an implementation detail — the profile does not prescribe MILP. Any optimization method that respects the observed constraints and produces valid dispatch goals is compliant.

---

## Phase 3 — Dispatch (On Demand, Top-Down)

When market obligations or grid signals trigger activation, the aggregator sends goals downward. Two levels of optimization distribute the goal.

### Sequence Diagram

```
  DSO/Market     Tech.            MQTT           HEMS            OpenADR         HEMS          Battery
                 Aggregator       Broker         Backend         (VTN→VEN)      Device
   │                │               │               │               │             │              │
   │ TRIGGER        │               │               │               │             │              │
   │ (grid stress,  │               │               │               │             │              │
   │  mFRR call,    │               │               │               │             │              │
   │  market pos.)  │               │               │               │             │              │
   │───────────────▶│               │               │               │             │              │
   │                │               │               │               │             │              │
   │                │  ┌────────────┤               │               │             │              │
   │                │  │ Aggregator │               │               │             │              │
   │                │  │ MILP       │               │               │             │              │
   │                │  │ (optimize  │               │               │             │              │
   │                │  │  across    │               │               │             │              │
   │                │  │  backends) │               │               │             │              │
   │                │  └────────────┤               │               │             │              │
   │                │               │               │               │             │              │
   │                │  1. DISPATCH GOALS (per backend)              │             │              │
   │                │──────────────▶│──────────────▶│               │             │              │
   │                │  (MQTT)       │  AggregatorDispatch           │             │              │
   │                │  direction,   │  (up/down,    │               │             │              │
   │                │  delta_kw,    │   schedule)   │               │             │              │
   │                │  schedule     │               │               │             │              │
   │                │               │               │               │             │              │
   │                │               │               │  ┌────────────┤             │              │
   │                │               │               │  │ Backend    │             │              │
   │                │               │               │  │ MILP       │             │              │
   │                │               │               │  │ (distribute│             │              │
   │                │               │               │  │  across    │             │              │
   │                │               │               │  │  devices)  │             │              │
   │                │               │               │  └────────────┤             │              │
   │                │               │               │               │             │              │
   │                │               │               │  2. DEVICE GOALS (per HEMS) │              │
   │                │               │               │  oadrDistributeEvent        │              │
   │                │               │               │──────────────▶│────────────▶│              │
   │                │               │               │  (power setpoint,           │              │
   │                │               │               │   duration, priority)       │              │
   │                │               │               │               │             │              │
   │                │               │               │               │  3. LOCAL   │              │
   │                │               │               │               │  EVALUATE   │              │
   │                │               │               │               │             │──check SoC──▶│
   │                │               │               │               │             │◀──status─────│
   │                │               │               │               │             │              │
   │                │               │               │  4. DEVICE RESPONSE         │              │
   │                │               │               │  oadrCreatedEvent           │              │
   │                │               │               │◀──────────────│◀────────────│              │
   │                │               │               │  (optIn/optOut,             │              │
   │                │               │               │   accepted_kw)              │              │
   │                │               │               │               │             │              │
   │                │  5. DISPATCH ACK (aggregated)  │               │             │              │
   │                │◀──────────────│◀──────────────│               │             │              │
   │                │  (MQTT)       │  DispatchAck  │               │             │              │
   │                │  (accepted/   │  (accepted_   │               │             │              │
   │                │   partial/    │   delta_kw)   │               │             │              │
   │                │   rejected)   │               │               │             │              │
   │                │               │               │               │             │              │
   │                │               │               │               │  6. EXECUTE │              │
   │                │               │               │               │             │──set power──▶│
   │                │               │               │               │             │              │
   │                │               │               │  (periodic OpenADR reports) │              │
   │                │◀──────────────│◀──────────────│◀──────────────│◀────────────│              │
   │                │  (MQTT        │  FlexStatus   │               │             │              │
   │                │   status)     │  (aggregated) │               │             │              │
   │                │               │               │               │             │              │
   │                │  7. RELEASE   │               │               │             │              │
   │                │──────────────▶│──────────────▶│               │             │              │
   │                │  (MQTT)       │               │──oadrCancel──▶│────────────▶│              │
   │                │               │               │               │             │──resume─────▶│
   │                │               │               │               │             │  normal      │
```

### Step Details

#### Step 1 — Aggregator MILP Produces Dispatch Goals

The aggregator, having continuously observed backend state and flex offers (Phase 1), runs its MILP to determine optimal dispatch:

- **Inputs**: Per-backend SiteFlexOffer (envelope, constraints, forecast, reliability), market obligations (mFRR call, intraday position, DSO signal)
- **Optimization**: Minimize portfolio peak, meet market obligations, penalize unreliable backends, respect per-backend ramp rates and duration limits
- **Output**: Per-backend dispatch goals — direction (up/down), target_delta_kw, time-series schedule of setpoints

#### Step 2 — Backend MILP Distributes to Devices

Each HEMS Backend receives its goal and runs its own MILP to distribute the requested delta across managed HEMS devices:

- **Inputs**: Per-device state (SoC, current power, mode), per-device constraints (battery limits, inverter capacity, user preferences), the aggregator's requested delta_kw
- **Optimization**: Deliver the requested delta while respecting per-device SoC floors, ramp rates, hardware limits, and prosumer preferences
- **Output**: Per-device power setpoints, translated into OpenADR events

#### Step 3 — Device Local Evaluation

Each HEMS device receives the OpenADR event and evaluates locally:
- State of Charge: Can the battery accept/deliver?
- Prosumer preferences: Opt-out windows, minimum SoC floor
- Hardware limits: Temperature, cycle count, inverter capacity
- **Decision**: Accept (optIn), partially accept, or reject (optOut)

#### Step 4 — Device Response

Devices respond via OpenADR `oadrCreatedEvent` with optIn/optOut and accepted power.

#### Step 5 — Backend Aggregates and Acknowledges

The HEMS Backend aggregates device responses into a `DispatchAck`:
- **accepted**: All devices accepted, full delta delivered
- **partially_accepted**: Some devices rejected, partial delta
- **rejected**: Cannot deliver (e.g., all devices at SoC limits)

#### Step 6 — Execute and Monitor

Devices execute the flex. The HEMS Backend periodically collects OpenADR reports and publishes aggregated `FlexStatus` to the aggregator.

#### Step 7 — Release

The aggregator publishes a release signal. The backend translates to OpenADR event cancellation. Devices resume normal operation. Automatic release via event duration expiry acts as fail-safe.

---

## Phase 4 — Settle (Post-Event)

### Sequence Diagram

```
  HEMS Device        HEMS Backend              MQTT Broker         Tech. Aggregator      Market/DSO
   │                    │                          │                    │                    │
   │                    │                          │                    │                    │
   │──final report─────▶│                          │                    │                    │
   │  (actual power,    │                          │                    │                    │
   │   energy delivered,│                          │                    │                    │
   │   SoC trajectory)  │                          │                    │                    │
   │                    │                          │                    │                    │
   │                    │  Generate DeliveryReport  │                    │                    │
   │                    │  (requested vs. actual    │                    │                    │
   │                    │   per time slot)          │                    │                    │
   │                    │                          │                    │                    │
   │                    │──DeliveryReport──────────▶│───────────────────▶│                    │
   │                    │  (MQTT)                   │                    │                    │
   │                    │                          │                    │  Verify against     │
   │                    │                          │                    │  metering data      │
   │                    │                          │                    │                    │
   │                    │                          │                    │  Update reliability  │
   │                    │                          │                    │  scores             │
   │                    │                          │                    │                    │
   │                    │                          │                    │──settlement────────▶│
   │                    │                          │                    │  (verified delivery) │
```

### Settlement Data

| Field | Description |
|---|---|
| Per-slot requested vs. actual delta | What was asked vs. what was measured |
| Delivery ratio | actual / requested (1.0 = perfect) |
| Baseline method | How the counterfactual was determined (meter-before, forecast, historical) |
| Rebound energy | Energy payback observed after activation |
| Reliability score update | Rolling 7-day delivered / announced ratio |

---

## The Two-Level MILP Pattern

The hierarchical optimization is a key architectural feature:

```
┌─────────────────────────────────────────────────────────────┐
│                    AGGREGATOR MILP                            │
│                                                              │
│  Sees: N backends, each with a flexibility envelope          │
│  Decides: How much to ask each backend (up/down per slot)    │
│  Respects: Per-backend constraints, market obligations,      │
│            reliability scores, ramp rates, rebound           │
│  Output: AggregatorDispatch per backend                      │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │Backend A │  │Backend B │  │Backend C │  ...              │
│  │flex_up:  │  │flex_up:  │  │flex_up:  │                  │
│  │  200 kW  │  │  150 kW  │  │   80 kW  │                  │
│  │flex_down:│  │flex_down:│  │flex_down:│                  │
│  │  180 kW  │  │  120 kW  │  │   60 kW  │                  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                  │
│       │              │              │                         │
│  goal: -100 kW  goal: -80 kW  goal: -50 kW                 │
└───────┼──────────────┼──────────────┼────────────────────────┘
        │              │              │
        ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  BACKEND A   │ │  BACKEND B   │ │  BACKEND C   │
│  MILP        │ │  MILP        │ │  MILP        │
│              │ │              │ │              │
│  Sees: M     │ │  Sees: K     │ │  Sees: L     │
│  devices     │ │  devices     │ │  devices     │
│              │ │              │ │              │
│  Distributes │ │  Distributes │ │  Distributes │
│  -100 kW     │ │  -80 kW      │ │  -50 kW      │
│  across      │ │  across      │ │  across      │
│  devices     │ │  devices     │ │  devices     │
│              │ │              │ │              │
│  Respects:   │ │  Respects:   │ │  Respects:   │
│  per-device  │ │  per-device  │ │  per-device  │
│  SoC, ramps, │ │  SoC, ramps, │ │  SoC, ramps, │
│  user prefs  │ │  user prefs  │ │  user prefs  │
└──────────────┘ └──────────────┘ └──────────────┘
```

**Why two levels, not one:**
- **Privacy**: The aggregator never sees per-device data
- **Scalability**: The aggregator solves for N backends (handful), not N×M devices (thousands)
- **Autonomy**: Each manufacturer's backend optimizes its own devices — the aggregator doesn't need to understand heterogeneous device models
- **Separation of concerns**: The aggregator optimizes the portfolio, the backend optimizes device dispatch

**Note**: MILP is the anticipated optimization method but the profile does not mandate it. Any optimization approach that respects the observed constraints and produces valid dispatch goals is compliant with this interoperability profile.

---

## Edge Cases

| Situation | Behavior |
|---|---|
| HEMS device offline when dispatch arrives | Backend MILP excludes device. Reduced accepted_delta_kw in DispatchAck |
| HEMS Backend offline | Aggregator MILP redistributes goal to remaining backends (re-optimize) |
| Battery hits SoC limit during execution | HEMS device updates OpenADR opt-in → backend publishes updated FlexStatus → aggregator may re-dispatch |
| Dispatch exceeds current flex envelope | Backend returns `partially_accepted` or `rejected` with reason |
| Backend MILP cannot meet requested delta | DispatchAck with `partially_accepted` and actual `accepted_delta_kw` |
| MQTT broker unreachable | HEMS Backends cannot receive dispatch. Devices continue normal operation |
| OpenADR VTN-VEN connection lost | Device continues normal operation. Backend adjusts aggregated capacity |
| Multiple aggregators for same backend | Backend must prevent double-commitment (first-come-first-served or priority-based) |
| Stale SiteFlexOffer (not refreshed) | Aggregator should discount or exclude backends with expired `valid_until` |
| Delivery ratio consistently low | Aggregator MILP penalizes backend via reliability score, reducing future dispatch |
