# 04 — Information Model

## Overview

The information model covers two interface layers:

1. **Aggregator ↔ HEMS Backend** (MQTT): JSON messages defined in this profile
2. **HEMS Backend ↔ HEMS Device** (OpenADR): Mapped to OpenADR 2.0b event/report model

## MQTT Messages (Aggregator ↔ HEMS Backend)

### FlexRequest (Aggregator → HEMS Backend)

Sent by the Technical Aggregator to request storage flexibility from a HEMS Backend's managed devices in a specific grid segment.

| Field | Type | Required | Description |
|---|---|---|---|
| `event_id` | string | yes | Unique identifier for this grid event |
| `segment_id` | string | yes | Grid segment identifier (DSO-assigned) |
| `direction` | enum | yes | `charge` / `discharge` / `hold` |
| `power_kw_max` | float | yes | Maximum power requested per device (kW) |
| `duration_min` | integer | yes | Expected duration of the flex event (minutes) |
| `priority` | enum | yes | `low` / `medium` / `high` / `critical` |
| `timestamp` | ISO 8601 | yes | Time of request issuance |
| `reason` | enum | no | `pv_overvoltage` / `load_undervoltage` / `transformer_overload` / `forecast_congestion` |
| `ramp_rate_kw_min` | float | no | Desired ramp rate (kW per minute) |

**Example**:
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

### FlexResponse (HEMS Backend → Aggregator)

Sent by the HEMS Backend after collecting and aggregating responses from its managed devices.

| Field | Type | Required | Description |
|---|---|---|---|
| `event_id` | string | yes | References the FlexRequest event_id |
| `backend_id` | string | yes | HEMS Backend identifier |
| `device_count` | integer | yes | Total devices in segment managed by this backend |
| `accepted_devices` | integer | yes | Devices that accepted the flex-request |
| `total_accepted_power_kw` | float | yes | Sum of accepted power across all devices |
| `avg_soc_percent` | float | yes | Average SoC of participating devices |
| `estimated_duration_min` | integer | yes | Minimum duration the devices can sustain |
| `timestamp` | ISO 8601 | yes | Time of aggregated response |

**Example**:
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

### FlexStatus (HEMS Backend → Aggregator, Periodic)

Periodic status update during flex execution. Allows aggregator to track actual aggregated delivery.

| Field | Type | Required | Description |
|---|---|---|---|
| `event_id` | string | yes | References the FlexRequest event_id |
| `backend_id` | string | yes | HEMS Backend identifier |
| `active_devices` | integer | yes | Currently active devices |
| `total_actual_power_kw` | float | yes | Sum of actual power being delivered |
| `avg_soc_percent` | float | yes | Current average SoC |
| `timestamp` | ISO 8601 | yes | Time of measurement |

**Example**:
```json
{
  "event_id": "evt-2026-10-24-001",
  "backend_id": "kern-backend-01",
  "active_devices": 40,
  "total_actual_power_kw": 148.2,
  "avg_soc_percent": 58,
  "timestamp": "2026-10-24T14:45:00Z"
}
```

### FlexRelease (Aggregator → HEMS Backend)

Sent by the aggregator to end a flex event.

| Field | Type | Required | Description |
|---|---|---|---|
| `event_id` | string | yes | References the FlexRequest event_id |
| `segment_id` | string | yes | Grid segment identifier |
| `timestamp` | ISO 8601 | yes | Time of release |

**Example**:
```json
{
  "event_id": "evt-2026-10-24-001",
  "segment_id": "seg-LA-0142",
  "timestamp": "2026-10-24T15:02:00Z"
}
```

## OpenADR Mapping (HEMS Backend ↔ HEMS Device)

The HEMS Backend (acting as OpenADR VTN) translates MQTT messages to/from OpenADR 2.0b.

### FlexRequest → oadrDistributeEvent

| MQTT FlexRequest field | OpenADR 2.0b element | Notes |
|---|---|---|
| `event_id` | `eiEvent.eventDescriptor.eventID` | Direct mapping |
| `direction: charge` | `signalType: LOAD_DISPATCH`, positive value | "Increase consumption" |
| `direction: discharge` | `signalType: LOAD_DISPATCH`, negative value | "Decrease consumption / export" |
| `direction: hold` | `signalType: LOAD_DISPATCH`, value = 0 | "Maintain current state" |
| `power_kw_max` | `eiEventSignal.signalPayload.payloadFloat` | Per-device max in kW |
| `duration_min` | `eiActivePeriod.properties.dtstart + duration` | ISO 8601 duration |
| `priority: low` | `priority: 0` | Advisory |
| `priority: medium` | `priority: 1` | Normal |
| `priority: high` | `priority: 2` | Significant |
| `priority: critical` | `priority: 3` | Grid safety |

### HEMS Device Response → oadrCreatedEvent

| OpenADR 2.0b element | Meaning |
|---|---|
| `optType: optIn` | Device accepts and will execute flex |
| `optType: optOut` | Device rejects (constraints, user preference) |
| `eventResponse.requestID` | Links response to specific event |

### Status Reporting → oadrReport

| Report type | Content |
|---|---|
| `TELEMETRY_STATUS` | Device online/offline, current mode |
| `TELEMETRY_USAGE` | Actual power (kW), SoC (%), energy delivered (kWh) |

The HEMS Backend aggregates individual device reports into backend-level FlexStatus messages on MQTT.

## Data Types & Conventions

- **Identifiers**: Opaque strings. `event_id` assigned by aggregator. `backend_id` assigned by HEMS manufacturer. `segment_id` assigned by DSO.
- **Power values**: Always in kW, positive values. Direction determined by `direction` field.
- **Timestamps**: ISO 8601 with timezone (UTC preferred)
- **SoC**: Percentage 0–100, relative to usable capacity
- **Enums**: Lowercase snake_case strings (MQTT layer). OpenADR uses its own enum conventions.

## IEC CIM Alignment

| This Profile | IEC CIM Concept |
|---|---|
| `segment_id` | `ConnectivityNode` / `TopologicalNode` |
| `backend_id` | `Organisation.mRID` |
| `FlexRequest` | loosely maps to `DispatchInstruction` |
| `direction` | `FlowDirection` |
| `power_kw_max` | `ActivePower` |
| `soc_percent` | `StateOfCharge` (IEC 61850) |
