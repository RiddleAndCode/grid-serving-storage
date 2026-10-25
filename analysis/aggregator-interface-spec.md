# Aggregator Interface Specification

2026-10-24

## Design Rationale

An aggregator orchestrates demand response across multiple sites. It does **not** care about individual devices — that is the site operator's domain. The aggregator needs:

1. **Observe** — a periodic state snapshot per site (consumption, production, grid quality)
2. **Plan** — a flexibility offer per site with site-level constraints sufficient for multi-site MILP
3. **Dispatch** — send activation signals (increase/decrease) to sites
4. **Settle** — verify delivery against promise for reliability scoring

This interface draws a clean boundary: the site abstracts its devices into an opaque flexibility envelope with constraints. The aggregator treats each site as a single controllable unit in its portfolio optimization.

The existing system already computes most of this internally. The gap is exposing it as a stable, outward-facing contract and adding the dispatch/settlement loop.

---

## 1. SiteStateSnapshot

Periodic heartbeat published by each site (push or poll, typically every 60s–5min).

```typescript
interface SiteStateSnapshot {
  // --- Identity ---
  site_id: string;                    // e.g. "wetzlas"
  display_name: string;
  timestamp: ISO8601;                 // When this snapshot was generated

  // --- Grid Connection ---
  grid_capacity_kw: number;           // Contracted connection capacity
  location: {
    latitude: number;
    longitude: number;
  };

  // --- Aggregated Power (real-time) ---
  power: {
    import_kw: number;                // Current grid import (positive = consuming)
    export_kw: number;                // Current grid export (positive = feeding in)
    net_kw: number;                   // import - export (positive = net consumer)
    production_kw: number;            // PV / local generation
    consumption_kw: number;           // Total load (monitored + unmonitored)
  };

  // --- Aggregated Energy (rolling) ---
  energy: {
    day: string;                      // ISO date
    import_kwh: number;               // Grid import today
    export_kwh: number;               // Grid export today
    production_kwh: number;           // PV generation today
    consumption_kwh: number;          // Total consumption today
  };

  // --- Grid Quality (from DSO metering point) ---
  grid_quality: {
    voltage_mean_v: number;           // Average across phases
    voltage_deviation_pct: number;    // Max deviation from nominal (230V)
    voltage_unbalance_pct: number;    // Phase unbalance
    frequency_hz: number;
    peak_to_avg_ratio: number;        // Load shape indicator
    congestion_risk: number;          // 0–1, p99 import / capacity
    voltage_risk: number;             // 0–1, deviation severity
  };

  // --- Availability ---
  online: boolean;                    // Site reporting within expected interval
  device_count: number;               // Number of monitored devices (opaque)
  last_reading_age_s: number;         // Seconds since last MQTT message
}
```

**Maps to existing system:** Combines data from `readings` (grid meter), `daily_agg`, `grid_metrics`, and `device_analytics` count. The site-level `power` block replaces the current device-by-device view.

---

## 2. SiteFlexOffer

The flexibility product a site publishes. Contains everything an aggregator MILP needs to model this site as a decision variable. Updated alongside the snapshot or on forecast refresh.

```typescript
interface SiteFlexOffer {
  site_id: string;
  timestamp: ISO8601;                 // When this offer was generated
  valid_until: ISO8601;               // Offer expiry (e.g. +15min)

  // --- Current Flexibility Envelope ---
  envelope: {
    baseline_kw: number;              // Current net power draw
    flex_down_kw: number;             // Max reduction from baseline (shedding ON loads)
    flex_up_kw: number;               // Max increase from baseline (turning ON idle loads)
    min_power_kw: number;             // baseline - flex_down (floor)
    max_power_kw: number;             // baseline + flex_up (ceiling)
    confidence: number;               // 0–1, overall envelope confidence
  };

  // --- Site-Level Constraints (for aggregator MILP) ---
  constraints: {
    ramp_rate_up_kw_per_h: number | null;    // Max upward power change per hour
    ramp_rate_down_kw_per_h: number | null;  // Max downward power change per hour
    min_activation_duration_min: number;      // Minimum time a dispatch must last
    max_activation_duration_min: number;      // Maximum sustained dispatch
    activation_lead_time_s: number;           // Seconds from signal to response
    rebound_factor: number;                   // 0–1, fraction of shed energy rebounding
    rebound_window_h: number;                 // Hours within which rebound occurs
    grid_capacity_kw: number;                 // Hard ceiling (connection limit)
  };

  // --- 24h Flexibility Forecast ---
  forecast: SiteFlexForecastSlot[];

  // --- Reliability Track Record ---
  reliability: {
    score: number;                    // 0–1, delivered / announced over trailing 7d
    announced_events: number;
    delivered_events: number;
    avg_delivery_ratio: number;       // Average actual_kw / requested_kw
  };
}

interface SiteFlexForecastSlot {
  target_time: ISO8601;               // Start of time slot
  window_minutes: number;             // 15 or 60
  baseline_kw: number;               // Expected baseline (from historical pattern)
  flex_down_kw: number;              // Predicted shedding capacity
  flex_up_kw: number;                // Predicted increase capacity
  confidence: number;                 // 0–1, model confidence for this slot
  model_type: "gbr" | "histgbr";     // Which model produced this
}
```

**Maps to existing system:** `envelope` comes from `compute_flexibility_snapshot()`. `constraints` aggregates `device_constraints` (already done in `fetch_aggregate_constraints()`). `forecast` maps directly to `flexibility_forecast` table. `reliability` comes from the existing `announced_events` / `delivered_events` tracking.

**What's new:** `valid_until`, `min/max_activation_duration_min`, `activation_lead_time_s` — these are needed so the aggregator knows the temporal shape of what it can request, not just the kW magnitude.

---

## 3. AggregatorDispatch

Activation signal sent from the aggregator to a site. The site translates this into device-level actions internally.

```typescript
interface AggregatorDispatch {
  dispatch_id: string;                // Unique ID for tracking/settlement
  site_id: string;
  issued_at: ISO8601;
  issued_by: string;                  // Aggregator identity

  // --- What to do ---
  direction: "down" | "up";          // "down" = reduce consumption, "up" = increase
  target_delta_kw: number;           // Requested change magnitude (always positive)

  // --- When to do it ---
  schedule: DispatchSlot[];           // Time-series of setpoints

  // --- Why (optional, for transparency / audit) ---
  reason: "peak_shaving" | "congestion" | "frequency" | "portfolio_balance" | "market";
  priority: "advisory" | "firm" | "emergency";  // advisory = best-effort
}

interface DispatchSlot {
  start: ISO8601;
  end: ISO8601;
  delta_kw: number;                  // Signed: negative = reduce, positive = increase
  // The site should adjust its net power by this amount relative to baseline
}

interface DispatchAck {
  dispatch_id: string;
  site_id: string;
  received_at: ISO8601;
  status: "accepted" | "partially_accepted" | "rejected";
  accepted_delta_kw: number;         // What the site commits to
  rejection_reason?: string;         // e.g. "exceeds current flex_down capacity"
  estimated_activation_time: ISO8601;
}
```

**Maps to existing system:** The current MILP output (`u_kw`, `d_kw` per timeslot) is the internal equivalent. Today it's computed and stored but never sent as an activation signal. This interface externalizes it.

---

## 4. DeliveryReport

Post-activation settlement. The site reports what actually happened; the aggregator verifies against metering data.

```typescript
interface DeliveryReport {
  dispatch_id: string;
  site_id: string;
  generated_at: ISO8601;

  // --- Per-slot actual vs. requested ---
  slots: DeliverySlot[];

  // --- Summary ---
  total_requested_kwh: number;       // Integral of requested delta over time
  total_delivered_kwh: number;       // Integral of actual delta over time
  delivery_ratio: number;            // delivered / requested (1.0 = perfect)
  rebound_kwh: number;              // Energy payback observed after activation

  // --- Baseline verification ---
  baseline_method: "meter_before" | "historical_avg" | "forecast";
  baseline_kwh: number;             // What consumption would have been without dispatch
}

interface DeliverySlot {
  start: ISO8601;
  end: ISO8601;
  requested_delta_kw: number;
  actual_delta_kw: number;           // Measured from meter (actual - baseline)
  baseline_kw: number;               // Reference power for this slot
}
```

**Maps to existing system:** The `reliability_score` and `announced/delivered_events` tracking is a simplified version of this. Full delivery reports would replace that with per-dispatch granularity.

---

## 5. Multi-Site MILP Formulation

How an aggregator uses these interfaces to solve portfolio-level DR dispatch.

### Decision Variables

For each site `s` and time slot `t`:

```
u[s,t] >= 0    # Upward flex activated at site s, slot t (kW)
d[s,t] >= 0    # Downward flex activated at site s, slot t (kW)
P[s,t]         # Net power at site s after dispatch
P_port[t]      # Portfolio-level net power at slot t
P_max          # Portfolio peak power (to minimize)
```

### Objective

```
minimize  P_max  +  lambda * sum_s( (1 - reliability[s]) * (u[s,t] + d[s,t]) )
```

Peak shaving with a penalty term for dispatching to unreliable sites.
`lambda` controls the reliability–optimality tradeoff.

### Constraints

```
# Per-site bounds (from SiteFlexOffer.forecast[t])
0 <= u[s,t] <= flex_up_kw[s,t]
0 <= d[s,t] <= flex_down_kw[s,t]

# Site power after dispatch
P[s,t] = baseline[s,t] + u[s,t] - d[s,t]

# Grid connection limit
P[s,t] <= grid_capacity_kw[s]

# Portfolio aggregation
P_port[t] = sum_s( P[s,t] )

# Portfolio peak
P_port[t] <= P_max    for all t

# Per-site ramp rates (from SiteFlexOffer.constraints)
P[s,t] - P[s,t-1] <= ramp_rate_up[s] * dt_hours
P[s,t-1] - P[s,t] <= ramp_rate_down[s] * dt_hours

# Per-site rebound (energy payback)
for each (s, t):
  sum(u[s,j] for j in [t, t+rebound_window[s])) >= rebound_factor[s] * d[s,t]

# Min activation duration
if d[s,t] > 0:
  d[s,t+1], ..., d[s,t+min_duration-1] > 0   (or model with binary activation variables)

# External DR obligations (grid operator signals, market commitments)
sum_s( d[s,t] ) >= DR_obligation_down[t]
sum_s( u[s,t] ) >= DR_obligation_up[t]
```

### Extensions Beyond Current Single-Site MILP

| Capability | Current (single-site) | Aggregator (multi-site) |
|---|---|---|
| Scope | One site, minimize its own peak | Portfolio of N sites, minimize aggregate peak |
| Reliability | Not modeled | Penalize unreliable sites in objective |
| DR obligations | `future_demands` table (up/down per slot) | External grid operator / market commitments |
| Min activation duration | Not enforced | Binary activation variables + min-duration constraint |
| Fairness | N/A | Optional: max dispatch share per site, rotation |
| Rebound coordination | Per-device, within site | Cross-site: stagger rebound windows to avoid coincident peaks |
| Cost | Not modeled | Optional: add dispatch cost per site (wear, comfort, tariff) |

### Additional Constraints an Aggregator Would Want

```
# Fairness — no single site bears disproportionate burden
sum_t( d[s,t] ) <= max_dispatch_share * sum_s,t( d[s,t] )    for all s

# Rebound staggering — avoid coincident rebound peaks
# Sites with overlapping rebound windows should not all activate simultaneously
# (binary activation variables + cardinality constraints)

# Confidence-weighted bounds — discount flex by confidence
u[s,t] <= flex_up_kw[s,t] * confidence[s,t]
d[s,t] <= flex_down_kw[s,t] * confidence[s,t]

# Cost minimization (if secondary objective or weighted)
minimize  alpha * P_max  +  beta * sum_s,t( cost[s] * (u[s,t] + d[s,t]) )
```

---

## 6. Portfolio Aggregation Rules

How a HEMS backend combines `SiteStateSnapshot` and `SiteFlexOffer` across sites. Not everything is a simple sum.

### Additive (just sum across sites)

| Field | Aggregation | Notes |
|---|---|---|
| `power.import_kw` | `sum` | Portfolio net import |
| `power.export_kw` | `sum` | Portfolio net export |
| `power.net_kw` | `sum` | Portfolio net power |
| `power.production_kw` | `sum` | Total generation |
| `power.consumption_kw` | `sum` | Total load |
| `energy.*` | `sum` | All energy counters are additive |
| `envelope.baseline_kw` | `sum` | Current total draw |

### Additive but overstated (discount before using)

`flex_down_kw` and `flex_up_kw` are technically additive, but the raw sum is the **theoretical maximum** — not what the portfolio can reliably deliver. Two effects erode it:

**Coincidence factor:** Correlated loads reduce diversity. On a cold day, all heat pumps run (high flex_down everywhere). On a warm day, they're all off (zero flex_down everywhere). The flex doesn't diversify the way uncorrelated loads would. A portfolio of 10 sites each reporting 2 kW flex_down will not reliably deliver 20 kW.

**Confidence variation:** Each site's envelope has different confidence. A 0.9-confidence site and a 0.5-confidence site should not contribute equally.

Three practical aggregation strategies, from simple to rigorous:

```
# 1. Confidence-weighted sum (good for dashboards)
portfolio_flex_down = sum( site.flex_down_kw * site.confidence )

# 2. Firm capacity at 90th percentile (good for DSO commitments)
portfolio_firm_down = sum( site.reliability_curve.firm_down_90 )

# 3. Full MILP (the only accurate answer for dispatch)
# Keep per-site, apply constraints, let the solver find what's achievable
```

**Rule of thumb:** Use (1) for monitoring, (2) for capacity promises, (3) for actual dispatch.

### NOT additive (keep per-site for the MILP)

| Field | Why not sum |
|---|---|
| `constraints.ramp_rate_*` | Each site ramps independently. A fast site and a slow site don't average out — the slow one still constrains what you can ask of it |
| `constraints.rebound_*` | Rebound is per-site and must be staggered to avoid coincident rebound peaks |
| `constraints.min/max_activation_duration` | Per-site physical limits. The portfolio min is meaningless |
| `constraints.activation_lead_time_s` | The slowest site determines how early you must signal, but you dispatch each site individually |
| `grid_capacity_kw` | Each site has its own connection limit. The portfolio constraint is at the **transformer/feeder** level — a different number from the DSO, not the sum of site capacities |

These fields remain individual rows in the MILP. Pre-aggregating them loses information the solver needs.

### Different aggregation method

| Field | Method | Rationale |
|---|---|---|
| `grid_quality.congestion_risk` | **max** across sites | Aggregator cares about the worst bottleneck |
| `grid_quality.voltage_risk` | **max** across sites | One site with voltage problems constrains dispatch in that area |
| `reliability.score` | **capacity-weighted average** | A 0.5-reliability site offering 10 kW matters more than one offering 0.5 kW |
| `forecast[t].confidence` | **capacity-weighted harmonic mean** or **min** | Weakest link for firm commitments |
| `online` | **count** | "12 of 15 sites online" |
| `last_reading_age_s` | **max** | Stalest reading determines data freshness |

### Two views the aggregator maintains

**1. Dashboard view** — pre-aggregated using the rules above. Shows portfolio KPIs: total consumption, total flex available (confidence-weighted), worst-case grid risk, sites online. Updated every snapshot cycle.

**2. MILP input view** — no pre-aggregation. Every site remains a separate row with its full `SiteFlexOffer`. The solver sees per-site constraints, per-site forecasts, per-site reliability. The **output** of the MILP is an aggregated dispatch plan, but the **input** must stay disaggregated.

**The gap between the dashboard sum and the MILP result is where coincidence, ramp limits, rebound, and reliability eat into the theoretical portfolio capacity.** That gap is the aggregator's value-add — finding the achievable optimum within the constraints.

---

## 7. Gaps in Today's System

What needs to be built to support this aggregator interface:

| Gap | Current State | Needed |
|---|---|---|
| **Site-level power aggregation** | Device-by-device only; grid meter gives import but no production/consumption split at API level | `SiteStateSnapshot.power` endpoint that merges grid meter + PV + device sum |
| **Outward-facing flex offer** | `flexibility_metrics` endpoint returns device-level contributors | New endpoint returning `SiteFlexOffer` (device-opaque) |
| **Temporal constraints** | `activation_time_s` and `sustain_time_min` are hardcoded (30s, 30min) | Derive from device constraints or make configurable per site |
| **Dispatch inbound API** | No dispatch endpoint exists | `POST /dispatch` accepting `AggregatorDispatch`, translating to device actions |
| **Dispatch acknowledgment** | N/A | Response to dispatch with `DispatchAck` |
| **Delivery reporting** | `reliability_score` is a simple ratio | Per-dispatch `DeliveryReport` with baseline verification |
| **Aggregator-level MILP** | Single-site MILP in `optimize_milp.py` | Extend to multi-site or build separate aggregator service |
| **Offer validity / expiry** | No concept of offer expiry | Add `valid_until` to flex snapshots |
| **Baseline verification** | No counterfactual baseline | Implement baseline methods (meter-before, forecast, historical avg) |
| **Dispatch-to-device translation** | No actuator layer | Service that maps `delta_kw` to device on/off commands (via MQTT/Zigbee) |

### Suggested Build Order

1. **`SiteStateSnapshot` endpoint** — aggregate existing data, no new computation
2. **`SiteFlexOffer` endpoint** — reshape existing flex metrics + constraints into offer format
3. **`POST /dispatch` + `DispatchAck`** — accept signals, store in new `dispatches` table
4. **Dispatch-to-device translation** — map site-level delta to device actions using priority + constraints
5. **`DeliveryReport` generation** — compare metered actuals vs. dispatch baseline
6. **Multi-site MILP** — extend `optimize_milp.py` or build aggregator-level solver
