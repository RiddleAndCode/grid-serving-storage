# 04 — Information Model

## Overview

The information model covers two interface layers with four phases of interaction:

1. **Aggregator ↔ HEMS Backend** (MQTT): JSON messages defined in this profile
2. **HEMS Backend ↔ HEMS Device** (OpenADR): Mapped to OpenADR 2.0b event/report model

The four phases define different message types:

| Phase | Direction | MQTT Messages | OpenADR Mapping |
|---|---|---|---|
| **Observe** | Bottom-up | SiteStateSnapshot, SiteFlexOffer | oadrReport (TELEMETRY_USAGE, TELEMETRY_STATUS) |
| **Plan** | Internal | (aggregator-internal, no messages) | — |
| **Dispatch** | Top-down | AggregatorDispatch, DispatchAck, FlexStatus, FlexRelease | oadrDistributeEvent, oadrCreatedEvent |
| **Settle** | Bottom-up | DeliveryReport | oadrReport (post-event) |

See `../aggregator-interface-spec.md` for the detailed interface specification including TypeScript definitions.

---

## Phase 1: Observe — Bottom-Up Messages

### SiteStateSnapshot (HEMS Backend → Aggregator, Periodic)

Periodic heartbeat published by each HEMS Backend, aggregating state across all managed devices. Typically every 60s–5 min.

| Field | Type | Required | Description |
|---|---|---|---|
| `site_id` | string | yes | HEMS Backend identifier |
| `timestamp` | ISO 8601 | yes | When this snapshot was generated |
| `grid_capacity_kw` | float | yes | Contracted grid connection capacity |
| `power.import_kw` | float | yes | Current grid import (positive = consuming) |
| `power.export_kw` | float | yes | Current grid export (positive = feeding in) |
| `power.net_kw` | float | yes | import - export (positive = net consumer) |
| `power.production_kw` | float | yes | PV / local generation |
| `power.consumption_kw` | float | yes | Total load |
| `energy.day` | ISO date | yes | Reference date |
| `energy.import_kwh` | float | yes | Grid import today |
| `energy.export_kwh` | float | yes | Grid export today |
| `grid_quality.voltage_deviation_pct` | float | no | Max deviation from nominal (230V) |
| `grid_quality.congestion_risk` | float | no | 0–1, import/capacity ratio |
| `online` | boolean | yes | Site reporting within expected interval |
| `device_count` | integer | yes | Number of monitored devices (opaque) |

**Example**:
```json
{
  "site_id": "kern-backend-01",
  "timestamp": "2026-10-24T14:30:00Z",
  "grid_capacity_kw": 25.0,
  "power": {
    "import_kw": 3.2,
    "export_kw": 0.0,
    "net_kw": 3.2,
    "production_kw": 4.8,
    "consumption_kw": 8.0
  },
  "energy": {
    "day": "2026-10-24",
    "import_kwh": 12.5,
    "export_kwh": 8.3
  },
  "online": true,
  "device_count": 47
}
```

### SiteFlexOffer (HEMS Backend → Aggregator, Periodic)

The flexibility product a HEMS Backend publishes. Contains everything the aggregator needs to model this backend as a decision variable in its optimization. Updated alongside the snapshot or on forecast refresh.

| Field | Type | Required | Description |
|---|---|---|---|
| `site_id` | string | yes | HEMS Backend identifier |
| `timestamp` | ISO 8601 | yes | When this offer was generated |
| `valid_until` | ISO 8601 | yes | Offer expiry |
| `envelope.baseline_kw` | float | yes | Current net power draw |
| `envelope.flex_down_kw` | float | yes | Max reduction from baseline (kW) |
| `envelope.flex_up_kw` | float | yes | Max increase from baseline (kW) |
| `envelope.min_power_kw` | float | yes | Floor: baseline - flex_down |
| `envelope.max_power_kw` | float | yes | Ceiling: baseline + flex_up |
| `envelope.confidence` | float | yes | 0–1, overall envelope confidence |
| `constraints.ramp_rate_up_kw_per_h` | float | no | Max upward power change per hour |
| `constraints.ramp_rate_down_kw_per_h` | float | no | Max downward power change per hour |
| `constraints.min_activation_duration_min` | integer | yes | Minimum dispatch duration |
| `constraints.max_activation_duration_min` | integer | yes | Maximum sustained dispatch |
| `constraints.activation_lead_time_s` | integer | yes | Seconds from signal to response |
| `constraints.rebound_factor` | float | no | 0–1, fraction of shed energy rebounding |
| `constraints.rebound_window_h` | float | no | Hours within which rebound occurs |
| `forecast` | array | no | 24h flexibility forecast (per slot) |
| `reliability.score` | float | yes | 0–1, delivered/announced over trailing 7 days |
| `reliability.avg_delivery_ratio` | float | yes | Average actual_kw / requested_kw |

**Example**:
```json
{
  "site_id": "kern-backend-01",
  "timestamp": "2026-10-24T14:30:00Z",
  "valid_until": "2026-10-24T14:45:00Z",
  "envelope": {
    "baseline_kw": 3.2,
    "flex_down_kw": 180.0,
    "flex_up_kw": 200.0,
    "min_power_kw": -176.8,
    "max_power_kw": 203.2,
    "confidence": 0.85
  },
  "constraints": {
    "ramp_rate_up_kw_per_h": 400.0,
    "ramp_rate_down_kw_per_h": 400.0,
    "min_activation_duration_min": 15,
    "max_activation_duration_min": 120,
    "activation_lead_time_s": 30,
    "rebound_factor": 0.3,
    "rebound_window_h": 2.0
  },
  "forecast": [
    {
      "target_time": "2026-10-24T15:00:00Z",
      "window_minutes": 15,
      "baseline_kw": 2.8,
      "flex_down_kw": 175.0,
      "flex_up_kw": 210.0,
      "confidence": 0.82
    }
  ],
  "reliability": {
    "score": 0.92,
    "avg_delivery_ratio": 0.88
  }
}
```

**Key**: Flexibility potentials (flex_up, flex_down) are **measured and learned** from actual ramp behavior of locally managed devices, not just nameplate capacity. The confidence score reflects how reliably the backend can deliver the advertised envelope.

---

## Phase 3: Dispatch — Top-Down Messages

### AggregatorDispatch (Aggregator → HEMS Backend)

Activation signal sent from the aggregator to a HEMS Backend. The backend translates this into device-level actions using its own optimization.

| Field | Type | Required | Description |
|---|---|---|---|
| `dispatch_id` | string | yes | Unique ID for tracking/settlement |
| `site_id` | string | yes | Target HEMS Backend |
| `issued_at` | ISO 8601 | yes | Time of dispatch |
| `issued_by` | string | yes | Aggregator identity |
| `direction` | enum | yes | `down` (reduce) / `up` (increase) |
| `target_delta_kw` | float | yes | Requested change magnitude (always positive) |
| `schedule` | array | yes | Time-series of setpoints (DispatchSlot[]) |
| `reason` | enum | no | `congestion` / `mfrr` / `peak_shaving` / `portfolio_balance` / `market` |
| `priority` | enum | yes | `advisory` (best-effort) / `firm` / `emergency` |

**DispatchSlot**:

| Field | Type | Description |
|---|---|---|
| `start` | ISO 8601 | Slot start time |
| `end` | ISO 8601 | Slot end time |
| `delta_kw` | float | Signed: negative = reduce, positive = increase |

**Example**:
```json
{
  "dispatch_id": "dsp-2026-10-24-001",
  "site_id": "kern-backend-01",
  "issued_at": "2026-10-24T14:32:00Z",
  "issued_by": "agg-01",
  "direction": "down",
  "target_delta_kw": 100.0,
  "schedule": [
    { "start": "2026-10-24T14:35:00Z", "end": "2026-10-24T14:50:00Z", "delta_kw": -100.0 },
    { "start": "2026-10-24T14:50:00Z", "end": "2026-10-24T15:05:00Z", "delta_kw": -80.0 }
  ],
  "reason": "congestion",
  "priority": "firm"
}
```

### DispatchAck (HEMS Backend → Aggregator)

The HEMS Backend's response after running its MILP and collecting device responses.

| Field | Type | Required | Description |
|---|---|---|---|
| `dispatch_id` | string | yes | References the AggregatorDispatch |
| `site_id` | string | yes | HEMS Backend identifier |
| `received_at` | ISO 8601 | yes | When dispatch was received |
| `status` | enum | yes | `accepted` / `partially_accepted` / `rejected` |
| `accepted_delta_kw` | float | yes | What the backend commits to |
| `rejection_reason` | string | no | e.g., "exceeds current flex_down capacity" |
| `estimated_activation_time` | ISO 8601 | yes | When the flex will begin |

**Example**:
```json
{
  "dispatch_id": "dsp-2026-10-24-001",
  "site_id": "kern-backend-01",
  "received_at": "2026-10-24T14:32:05Z",
  "status": "partially_accepted",
  "accepted_delta_kw": 85.0,
  "rejection_reason": "3 devices at SoC floor, 2 offline",
  "estimated_activation_time": "2026-10-24T14:32:35Z"
}
```

### FlexStatus (HEMS Backend → Aggregator, Periodic)

Periodic status update during dispatch execution.

| Field | Type | Required | Description |
|---|---|---|---|
| `dispatch_id` | string | yes | References the AggregatorDispatch |
| `site_id` | string | yes | HEMS Backend identifier |
| `active_devices` | integer | yes | Currently active devices |
| `total_actual_power_kw` | float | yes | Sum of actual power being delivered |
| `avg_soc_percent` | float | yes | Current average SoC |
| `timestamp` | ISO 8601 | yes | Time of measurement |

### FlexRelease (Aggregator → HEMS Backend)

Sent by the aggregator to end a dispatch.

| Field | Type | Required | Description |
|---|---|---|---|
| `dispatch_id` | string | yes | References the AggregatorDispatch |
| `site_id` | string | yes | Target HEMS Backend |
| `timestamp` | ISO 8601 | yes | Time of release |

---

## Phase 4: Settle — Post-Event Messages

### DeliveryReport (HEMS Backend → Aggregator)

Post-dispatch settlement report. Generated after dispatch completes.

| Field | Type | Required | Description |
|---|---|---|---|
| `dispatch_id` | string | yes | References the AggregatorDispatch |
| `site_id` | string | yes | HEMS Backend identifier |
| `generated_at` | ISO 8601 | yes | Report generation time |
| `total_requested_kwh` | float | yes | Integral of requested delta over time |
| `total_delivered_kwh` | float | yes | Integral of actual delta over time |
| `delivery_ratio` | float | yes | delivered / requested (1.0 = perfect) |
| `rebound_kwh` | float | no | Energy payback after activation |
| `baseline_method` | enum | yes | `meter_before` / `historical_avg` / `forecast` |
| `slots` | array | yes | Per-slot requested vs. actual (DeliverySlot[]) |

---

## OpenADR Mapping (HEMS Backend ↔ HEMS Device)

The HEMS Backend (acting as OpenADR VTN) translates MQTT messages to/from OpenADR 2.0b.

### AggregatorDispatch → oadrDistributeEvent

The Backend MILP decomposes the aggregator's goal into per-device setpoints, then maps each to an OpenADR event:

| Dispatch concept | OpenADR 2.0b element | Notes |
|---|---|---|
| `dispatch_id` | `eiEvent.eventDescriptor.eventID` | Tracking ID |
| `direction: down` | `signalType: LOAD_DISPATCH`, negative value | Reduce consumption / increase export |
| `direction: up` | `signalType: LOAD_DISPATCH`, positive value | Increase consumption |
| Per-device delta_kw | `eiEventSignal.signalPayload.payloadFloat` | Device-specific setpoint from Backend MILP |
| `schedule[].start/end` | `eiActivePeriod.properties.dtstart + duration` | ISO 8601 duration |
| `priority: advisory` | `priority: 0` | Best-effort |
| `priority: firm` | `priority: 2` | Committed |
| `priority: emergency` | `priority: 3` | Grid safety |

### Device Response → oadrCreatedEvent

| OpenADR 2.0b element | Meaning |
|---|---|
| `optType: optIn` | Device accepts and will execute |
| `optType: optOut` | Device rejects (constraints, user preference) |

### Status Reporting → oadrReport

| Report type | Content |
|---|---|
| `TELEMETRY_STATUS` | Device online/offline, current mode |
| `TELEMETRY_USAGE` | Actual power (kW), SoC (%), energy delivered (kWh) |

The HEMS Backend aggregates individual device reports into backend-level FlexStatus and DeliveryReport messages on MQTT.

---

## Data Types & Conventions

- **Identifiers**: Opaque strings. `dispatch_id` assigned by aggregator. `site_id` / `backend_id` assigned by HEMS manufacturer. `segment_id` assigned by DSO.
- **Power values**: Always in kW. Positive values in snapshots/offers. Signed delta in dispatch schedules (negative = reduce, positive = increase).
- **Timestamps**: ISO 8601 with timezone (UTC preferred)
- **SoC**: Percentage 0–100, relative to usable capacity
- **Confidence/reliability**: 0–1 float. 1.0 = perfect.
- **Enums**: Lowercase snake_case strings (MQTT layer). OpenADR uses its own enum conventions.

## Portfolio Aggregation Rules

Not all fields from SiteStateSnapshot and SiteFlexOffer aggregate the same way:

| Aggregation | Fields | Method |
|---|---|---|
| **Additive** | power.*, energy.*, envelope.baseline_kw | Sum across backends |
| **Additive but overstated** | flex_down_kw, flex_up_kw | Sum is theoretical max — discount by confidence or use MILP |
| **NOT additive (keep per-backend)** | constraints.*, ramp rates, rebound | Each backend is independent — these remain individual inputs to the aggregator MILP |
| **Max across backends** | grid_quality.congestion_risk, voltage_risk | Worst bottleneck matters |
| **Capacity-weighted average** | reliability.score | Larger backends contribute more |

**Rule of thumb**: Use confidence-weighted sums for dashboards, firm capacity at 90th percentile for market commitments, and the full MILP for actual dispatch.

## IEC CIM Alignment

| This Profile | IEC CIM Concept |
|---|---|
| `segment_id` | `ConnectivityNode` / `TopologicalNode` |
| `site_id` / `backend_id` | `Organisation.mRID` |
| `AggregatorDispatch` | `DispatchInstruction` |
| `direction` | `FlowDirection` |
| `power_kw` / `delta_kw` | `ActivePower` |
| `soc_percent` | `StateOfCharge` (IEC 61850) |
| `SiteFlexOffer.envelope` | `FlexibilityOffer` (conceptual) |
