# 03 — Process Flow

## Overview

The grid-serving storage process follows seven steps. The architecture has two distinct communication segments:
- **Aggregator ↔ HEMS Backend**: MQTT v5
- **HEMS Backend ↔ HEMS Device**: OpenADR 2.0b (VTN ↔ VEN)

**This process flow applies identically across all serviceable markets.** Whether the trigger is a DSO congestion signal, an mFRR activation from APG, an intraday market position, or a local flexibility market clearing — the FlexRequest → FlexResponse → FlexStatus → FlexRelease message cycle is the same. Only the trigger (Step 1) and the upstream market interface differ.

### Timing Context

The architecture operates in **Tier 2** (event-driven flex) with the following timing budget:

| Market | Available Response Time | Signal Chain (~5–10s) | Headroom |
|---|---|---|---|
| **mFRR** | 12.5 min (FAT) | ~10s | ~12 min |
| **Congestion management** | Minutes (DSO-dependent) | ~10s | Minutes |
| **Intraday** | ≥5 min (gate closure) | ~10s | Minutes |
| **Day-ahead** | Hours | ~10s | Hours |

Tier 1 markets (FCR: 30s, aFRR: 5 min with 4s setpoint cycle) cannot be served through this process — they require dedicated SCADA/PLC control loops that bypass the HEMS backend stack.

## Sequence Diagram

```
  DSO          Tech.           MQTT          HEMS           OpenADR        HEMS         Battery
               Aggregator      Broker        Backend        (VTN→VEN)     Device
   │               │              │              │              │            │             │
   │ 1. GRID STRESS│              │              │              │            │             │
   │   SIGNAL      │              │              │              │            │             │
   │──────────────▶│              │              │              │            │             │
   │  (existing    │              │              │              │            │             │
   │   market IF)  │              │              │            │             │
   │               │              │              │              │            │             │
   │               │ 2. PUBLISH FLEX-REQUEST     │              │            │             │
   │               │   (MQTT)     │              │              │            │             │
   │               │─────────────▶│              │              │            │             │
   │               │              │─────────────▶│              │            │             │
   │               │              │  (per HEMS   │              │            │             │
   │               │              │   backend)   │              │            │             │
   │               │              │              │              │            │             │
   │               │              │              │ 3. FORWARD AS OpenADR     │             │
   │               │              │              │  oadrDistributeEvent      │             │
   │               │              │              │─────────────▶│            │             │
   │               │              │              │              │───────────▶│             │
   │               │              │              │              │            │             │
   │               │              │              │              │  4. LOCAL  │             │
   │               │              │              │              │  EVALUATE  │             │
   │               │              │              │              │            │──check SoC─▶│
   │               │              │              │              │            │◀──status────│
   │               │              │              │              │            │             │
   │               │              │              │  5. RESPOND  │            │             │
   │               │              │              │  oadrCreatedEvent         │             │
   │               │              │              │◀─────────────│            │             │
   │               │              │              │              │◀───────────│             │
   │               │ AGGREGATE    │              │              │            │             │
   │               │ RESPONSES    │              │              │            │             │
   │               │◀─────────────│◀─────────────│              │            │             │
   │               │   (MQTT)     │              │              │            │             │
   │               │              │              │              │            │             │
   │               │              │              │              │  6. EXECUTE│             │
   │               │              │              │              │    FLEX    │             │
   │               │              │              │              │            │──set power─▶│
   │               │              │              │              │            │             │
   │               │              │              │  (periodic OpenADR       │             │
   │               │              │              │   oadrReport) │            │             │
   │               │◀─────────────│◀─────────────│◀─────────────│◀───────────│             │
   │               │  (MQTT       │              │              │            │             │
   │               │   status)    │              │              │            │             │
   │               │              │              │              │            │             │
   │               │ 7. PUBLISH RELEASE          │              │            │             │
   │               │─────────────▶│─────────────▶│              │            │             │
   │               │  (MQTT)      │              │──oadrDistrib.│            │             │
   │               │              │              │  Event       │            │             │
   │               │              │              │─────────────▶│───────────▶│             │
   │               │              │              │              │            │──resume────▶│
   │               │              │              │              │            │  normal     │
```

## Step Details

### Step 1 — Trigger: Market or Grid Signal to Aggregator

**Actor**: DSO / TSO / Market Platform → Technical Aggregator

**Interface**: Existing market interfaces (outside this profile's scope)

**Trigger sources** (same process from Step 2 onward):

| Source | Signal | Example |
|---|---|---|
| **DSO** | Grid congestion signal | Overvoltage in segment seg-LA-0142 from excess PV feed-in |
| **TSO (APG)** | mFRR activation | Tertiary reserve call, 12.5 min FAT, quarter-hourly delivery |
| **Intraday market** | Cleared position | Aggregator committed 500 kW discharge for 14:00–14:15 interval |
| **Flex market platform** | Activation after clearing | Local flexibility market (NODES/Equigy) cleared a bid in segment |
| **Aggregator internal** | Preventive forecast | Grid-aware forecasting predicts congestion in 30 min |

**Note**: These upstream interfaces already exist in Austrian market processes. Our profile begins at Step 2 — the activation flow is market-agnostic.

### Step 2 — Aggregator Publishes Flex-Request via MQTT

**Actor**: Technical Aggregator → MQTT Broker → HEMS Backend(s)

**Protocol**: MQTT v5

**Action**: The aggregator determines which HEMS backends operate devices in the affected grid segment and publishes a FlexRequest message.

**MQTT details**:
- Topic: `flex/{aggregator_id}/{segment_id}/request`
- QoS: 1 (at-least-once delivery)
- Message expiry: set to event duration

**Message content** (see `04-information-model.md`):
```json
{
  "event_id": "evt-2026-10-24-001",
  "segment_id": "seg-LA-0142",
  "direction": "charge",
  "power_kw_max": 5.0,
  "duration_min": 30,
  "priority": "high",
  "timestamp": "2026-10-24T14:32:00Z",
  "reason": "pv_overvoltage"
}
```

### Step 3 — HEMS Backend Forwards as OpenADR Event

**Actor**: HEMS Backend (VTN) → HEMS Device (VEN)

**Protocol**: OpenADR 2.0b

**Action**: The HEMS Backend translates the MQTT flex-request into an OpenADR `oadrDistributeEvent` message and pushes it to each relevant HEMS device in the affected segment.

**OpenADR mapping**:
- FlexRequest → `oadrEvent` within `oadrDistributeEvent`
- `direction` → `signalType` (e.g., `LEVEL` or `LOAD_DISPATCH`)
- `power_kw_max` → `signalPayload` / `currentValue`
- `duration_min` → `eiActivePeriod` / `duration`
- `priority` → `priority` (0–3 mapping)

**Key**: The HEMS Backend acts as the **OpenADR VTN** (Virtual Top Node). Each HEMS device is an **OpenADR VEN** (Virtual End Node).

### Step 4 — HEMS Device Evaluates Locally

**Actor**: HEMS Device (at customer site)

**Action**: The HEMS receives the OpenADR event and evaluates it against local constraints:

- **State of Charge (SoC)**: Can the battery accept charge / deliver discharge?
- **Minimum SoC floor**: Prosumer's configured minimum (e.g., never below 20%)
- **Maximum charge rate**: Hardware limit of the battery/inverter
- **User preferences**: Opt-out windows, priority schedules
- **Safety limits**: Temperature, cycle count, manufacturer limits

**Decision**: Accept fully (`optIn`), accept partially (reduced power via `optIn` with modified signal), or reject (`optOut`).

### Step 5 — HEMS Device Responds via OpenADR

**Actor**: HEMS Device (VEN) → HEMS Backend (VTN)

**Protocol**: OpenADR 2.0b

**Action**: The HEMS device sends an `oadrCreatedEvent` response indicating opt-in/opt-out status.

**HEMS Backend aggregation**: The backend collects responses from all its devices in the segment, aggregates them into a single FlexResponse, and publishes via MQTT:

**MQTT response**:
- Topic: `flex/{aggregator_id}/{segment_id}/response/{backend_id}`
- QoS: 1

```json
{
  "event_id": "evt-2026-10-24-001",
  "backend_id": "kern-backend-01",
  "device_count": 47,
  "accepted_devices": 42,
  "total_accepted_power_kw": 156.5,
  "avg_soc_percent": 52,
  "estimated_duration_min": 30,
  "timestamp": "2026-10-24T14:32:18Z"
}
```

### Step 6 — Execute Flex

**Actor**: HEMS Device → Battery

**Action**: The HEMS adjusts battery charge/discharge setpoints per the accepted flex signal.

**During execution**:
- HEMS monitors battery state continuously
- If constraints are hit (SoC limit), HEMS modifies its OpenADR opt-in status
- HEMS Backend periodically collects status via OpenADR `oadrReport` (report-only polling or push)
- HEMS Backend publishes aggregated status to aggregator via MQTT FlexStatus messages

### Step 7 — Release

**Actor**: Aggregator → MQTT → HEMS Backend → OpenADR → HEMS Device

**Action**: Aggregator publishes FlexRelease on MQTT. HEMS Backend translates to OpenADR event cancellation (`oadrDistributeEvent` with `eventStatus = cancelled`). HEMS devices return to normal operation.

**Automatic release**: If neither release nor renewed event is received within `duration_min`, the HEMS device auto-releases (fail-safe via OpenADR event duration expiry).

## Edge Cases

| Situation | Behavior |
|---|---|
| HEMS device offline when event arrives | OpenADR VTN (backend) marks device as non-participating. Does not count in aggregated response |
| HEMS Backend offline | MQTT broker queues message (QoS 1, session expiry). Aggregator does not count this backend's devices |
| Battery hits SoC limit during flex | HEMS device updates OpenADR opt-in → backend publishes updated FlexStatus via MQTT |
| New event before release of previous | New OpenADR event supersedes. HEMS evaluates fresh. Backend notifies aggregator of changed capacity |
| MQTT broker unreachable | HEMS Backend cannot receive requests. Devices continue normal operation |
| OpenADR VTN-VEN connection lost | Device continues normal operation (fail-safe). Backend adjusts aggregated capacity report |
| Multiple aggregators for same segment | Each aggregator operates independently. HEMS Backend must prevent double-commitment (first-come-first-served or priority-based) |
