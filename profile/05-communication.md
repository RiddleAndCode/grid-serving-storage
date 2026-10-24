# 05 — Communication Layer

## Dual-Protocol Architecture

This profile defines two distinct communication interfaces:

1. **Aggregator ↔ HEMS Backend**: MQTT v5 (backend-level coordination)
2. **HEMS Backend ↔ HEMS Device**: OpenADR 2.0b (device-level control)

```
┌──────────────┐         MQTT v5          ┌──────────────┐       OpenADR 2.0b      ┌──────────────┐
│  Technical   │◀────────────────────────▶│    HEMS      │◀──────────────────────▶│    HEMS      │
│  Aggregator  │   Device coordination    │   Backend    │   Device control        │   Device     │
│              │   JSON over TLS          │   (VTN)      │   XML over HTTPS        │   (VEN)      │
└──────────────┘                          └──────────────┘                         └──────────────┘
```

The HEMS Backend is the **protocol bridge**: it speaks MQTT upstream (to the aggregator) and OpenADR downstream (to devices).

---

## Interface 1: Aggregator ↔ HEMS Backend (MQTT v5)

### Why MQTT for This Interface

- **Multiple HEMS backends** from different manufacturers must connect to the aggregator — pub/sub avoids point-to-point API integration per vendor
- **Scales** to many backends, each managing hundreds/thousands of devices
- **Asynchronous** — backends respond when their devices have been polled, not within a synchronous HTTP timeout
- **Lightweight** — small JSON payloads, low overhead
- **Bidirectional** — aggregator pushes requests, backends push responses and status
- **MQTT v5** adds message expiry (prevents stale activations), reason codes, and user properties

### Topic Structure

```
flex/
└── {aggregator_id}/
    └── {segment_id}/
        ├── request                    ← Aggregator publishes FlexRequest
        ├── response/
        │   └── {backend_id}           ← Backend publishes FlexResponse
        ├── status/
        │   └── {backend_id}           ← Backend publishes FlexStatus (periodic)
        └── release                    ← Aggregator publishes FlexRelease
```

### Topic Examples

| Purpose | Topic | Publisher | Subscriber |
|---|---|---|---|
| Flex request | `flex/agg-01/seg-LA-0142/request` | Aggregator | All backends with devices in segment |
| Backend response | `flex/agg-01/seg-LA-0142/response/kern-backend-01` | HEMS Backend | Aggregator |
| Backend status | `flex/agg-01/seg-LA-0142/status/kern-backend-01` | HEMS Backend | Aggregator |
| Event release | `flex/agg-01/seg-LA-0142/release` | Aggregator | All backends with devices in segment |

### Backend Subscription

On onboarding, each HEMS Backend subscribes to segment topics for all grid segments where it has devices:
```
flex/{aggregator_id}/+/request
flex/{aggregator_id}/+/release
```

Using MQTT wildcard `+` for segment_id, so the backend receives requests for all segments. The backend filters locally for segments where it actually has devices.

### QoS & Delivery

| Message Type | QoS | Retained | Message Expiry | Rationale |
|---|---|---|---|---|
| FlexRequest | 1 (at-least-once) | No | = duration_min × 60s | Stale requests must not activate devices |
| FlexResponse | 1 (at-least-once) | No | 120s | Aggregator needs timely response |
| FlexStatus | 0 (at-most-once) | No | 60s | Informational; loss tolerable |
| FlexRelease | 1 (at-least-once) | No | 300s | Must reach backends; device-side timer as backup |

### MQTT v5 Features

| Feature | Usage |
|---|---|
| **Message Expiry** | Flex-requests auto-expire — prevents stale activation after reconnect |
| **Reason Codes** | Broker communicates subscription/publish failures |
| **User Properties** | Carry `event_id` for filtering without parsing payload |
| **Topic Aliases** | Reduce bandwidth for frequent status messages |
| **Session Expiry** | Backends set session expiry — broker queues messages during brief disconnections |

### MQTT Security

- **TLS 1.3** mandatory for all connections
- **Client certificates** (X.509) for mutual authentication between aggregator, broker, and backends
- **ACLs**: Each backend can only publish to its own `{backend_id}` response/status topics
- **Broker deployment**: Operated by aggregator or neutral party with appropriate SLAs

---

## Interface 2: HEMS Backend ↔ HEMS Device (OpenADR 2.0b)

### Why OpenADR for This Interface

- **Austrian standard**: Smart Grids Austria identifies OpenADR as the favored protocol for controlling flexible assets in Austria
- **Designed for demand response**: OpenADR's event model (distribute → create → report) maps directly to the flex-request lifecycle
- **Vendor-neutral**: Any HEMS manufacturer can implement an OpenADR VEN; any backend can implement a VTN
- **Proven**: Deployed globally for demand response, with active certification program (OpenADR Alliance)
- **Security built-in**: HTTPS transport with PKI-based authentication

### OpenADR Architecture

```
┌─────────────────────┐              ┌─────────────────────┐
│    HEMS Backend     │              │    HEMS Device      │
│                     │              │                     │
│  ┌───────────────┐  │    HTTPS     │  ┌───────────────┐  │
│  │  OpenADR VTN  │◀─┼─────────────┼─▶│  OpenADR VEN  │  │
│  │               │  │              │  │               │  │
│  │ - Push events │  │              │  │ - Receive     │  │
│  │ - Collect     │  │              │  │   events      │  │
│  │   reports     │  │              │  │ - Opt in/out  │  │
│  │ - Manage      │  │              │  │ - Report      │  │
│  │   registr.    │  │              │  │   telemetry   │  │
│  └───────────────┘  │              │  └───────────────┘  │
└─────────────────────┘              └─────────────────────┘
```

### OpenADR Message Flow

| Step | OpenADR Service | Direction | Purpose |
|---|---|---|---|
| Registration | `EiRegisterParty` | VEN → VTN | HEMS device registers with backend |
| Event distribution | `EiEvent` / `oadrDistributeEvent` | VTN → VEN | Backend pushes flex-request as event |
| Event response | `oadrCreatedEvent` | VEN → VTN | Device responds optIn / optOut |
| Reporting | `EiReport` / `oadrReport` | VEN → VTN | Device reports actual power, SoC |
| Cancellation | `oadrDistributeEvent` (cancelled) | VTN → VEN | Backend pushes event release |

### OpenADR Profile Requirements

For the Grid-Serving Storage use case, HEMS devices (VENs) must support:

**Mandatory**:
- `EiEvent` service — receive events and respond with optIn/optOut
- `EiRegisterParty` service — register with VTN
- Signal type: `LOAD_DISPATCH` — direct power setpoint signals
- `optType` response — communicate acceptance/rejection

**Recommended**:
- `EiReport` service — telemetry reporting (actual power, SoC)
- Report type: `TELEMETRY_USAGE` — real-time power and energy data
- Report type: `TELEMETRY_STATUS` — device online/fault status

**Transport**:
- HTTPS (HTTP over TLS 1.2+)
- OpenADR 2.0b profile B (PUSH mode — VTN pushes events to VEN)
- XML payloads per OpenADR schema

### OpenADR Security

- **HTTPS** with TLS 1.2+ (mandatory per OpenADR 2.0b)
- **OpenADR PKI certificates** — VTN and VEN authenticate via OpenADR Alliance certificate hierarchy (or private PKI)
- **XML signatures** — optional but recommended for payload integrity

---

## Protocol Bridge: HEMS Backend

The HEMS Backend is the key integration point. It must:

1. **Receive** MQTT FlexRequest from aggregator
2. **Translate** to OpenADR `oadrDistributeEvent` for each device in the segment
3. **Collect** OpenADR `oadrCreatedEvent` responses from devices
4. **Aggregate** device responses into an aggregated FlexResponse
5. **Publish** aggregated FlexResponse on MQTT
6. **Periodically collect** OpenADR reports from devices
7. **Publish** aggregated FlexStatus on MQTT
8. **Receive** MQTT FlexRelease and translate to OpenADR event cancellation

This bridge logic is **manufacturer-specific** — each HEMS vendor implements it in their backend. The profile standardizes the MQTT and OpenADR interfaces on either side.

---

## Fallback & Resilience

| Failure | Behavior |
|---|---|
| MQTT broker unavailable | HEMS Backends cannot receive requests. Devices continue normal operation |
| HEMS Backend down | Aggregator does not receive response for that backend's devices. Other backends still respond |
| OpenADR VTN-VEN link lost | Device continues normal operation. Backend reports reduced aggregated capacity |
| Device offline | Backend marks device as non-participating in aggregated response |
| Message expiry reached | Backend ignores stale flex-request. No activation |
| Duration exceeded without release | OpenADR event duration expires naturally. Device auto-resumes normal operation |

**Fail-safe principle**: Any failure at any layer defaults to normal prosumer-controlled operation.
