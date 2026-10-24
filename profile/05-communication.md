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

The topic structure supports both the continuous observation phase (bottom-up) and the dispatch phase (top-down):

```
{aggregator_id}/
├── observe/
│   └── {backend_id}/
│       ├── state                      ← Backend publishes SiteStateSnapshot
│       └── flex                       ← Backend publishes SiteFlexOffer
├── dispatch/
│   └── {segment_id}/
│       ├── request                    ← Aggregator publishes AggregatorDispatch
│       ├── ack/
│       │   └── {backend_id}           ← Backend publishes DispatchAck
│       ├── status/
│       │   └── {backend_id}           ← Backend publishes FlexStatus (periodic)
│       └── release                    ← Aggregator publishes FlexRelease
└── settle/
    └── {backend_id}/
        └── {dispatch_id}             ← Backend publishes DeliveryReport
```

### Topic Examples

| Purpose | Topic | Publisher | Subscriber | Phase |
|---|---|---|---|---|
| Site state | `agg-01/observe/kern-backend-01/state` | HEMS Backend | Aggregator | Observe |
| Flex offer | `agg-01/observe/kern-backend-01/flex` | HEMS Backend | Aggregator | Observe |
| Dispatch goal | `agg-01/dispatch/seg-LA-0142/request` | Aggregator | Backends in segment | Dispatch |
| Dispatch ack | `agg-01/dispatch/seg-LA-0142/ack/kern-backend-01` | HEMS Backend | Aggregator | Dispatch |
| Execution status | `agg-01/dispatch/seg-LA-0142/status/kern-backend-01` | HEMS Backend | Aggregator | Dispatch |
| Release | `agg-01/dispatch/seg-LA-0142/release` | Aggregator | Backends in segment | Dispatch |
| Delivery report | `agg-01/settle/kern-backend-01/dsp-001` | HEMS Backend | Aggregator | Settle |

### Backend Subscription

On onboarding, each HEMS Backend subscribes to:
```
# Dispatch signals for all segments (filter locally)
{aggregator_id}/dispatch/+/request
{aggregator_id}/dispatch/+/release
```

The aggregator subscribes to:
```
# All observation data from all backends
{aggregator_id}/observe/+/state
{aggregator_id}/observe/+/flex

# All dispatch responses
{aggregator_id}/dispatch/+/ack/+
{aggregator_id}/dispatch/+/status/+

# All settlement reports
{aggregator_id}/settle/+/+
```

### QoS & Delivery

| Message Type | Phase | QoS | Retained | Message Expiry | Rationale |
|---|---|---|---|---|---|
| SiteStateSnapshot | Observe | 0 (at-most-once) | Yes (latest) | 300s | Periodic; latest state is what matters. Retained so new subscribers get current state |
| SiteFlexOffer | Observe | 1 (at-least-once) | Yes (latest) | = valid_until | Flex offers expire; retained for aggregator reconnection |
| AggregatorDispatch | Dispatch | 1 (at-least-once) | No | = schedule duration | Stale dispatches must not activate devices |
| DispatchAck | Dispatch | 1 (at-least-once) | No | 120s | Aggregator needs timely response |
| FlexStatus | Dispatch | 0 (at-most-once) | No | 60s | Informational; loss tolerable |
| FlexRelease | Dispatch | 1 (at-least-once) | No | 300s | Must reach backends; device-side timer as backup |
| DeliveryReport | Settle | 1 (at-least-once) | No | 3600s | Settlement data; must arrive but not time-critical |

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

The HEMS Backend is the key integration point, operating in both directions:

**Bottom-up (Observe phase)**:
1. **Collect** OpenADR reports (TELEMETRY_USAGE, TELEMETRY_STATUS) from managed HEMS devices
2. **Aggregate** device data into site-level SiteStateSnapshot (power, energy, grid quality)
3. **Compute** SiteFlexOffer from device capabilities — flexibility envelope, constraints, forecast (learned from device ramp behavior)
4. **Publish** SiteStateSnapshot and SiteFlexOffer on MQTT

**Top-down (Dispatch phase)**:
1. **Receive** AggregatorDispatch from aggregator via MQTT (direction, target delta, schedule)
2. **Run Backend MILP** to distribute the requested delta across managed devices (respecting per-device SoC, ramps, user preferences)
3. **Translate** per-device goals to OpenADR `oadrDistributeEvent` for each HEMS device
4. **Collect** OpenADR `oadrCreatedEvent` responses from devices
5. **Aggregate** device responses into DispatchAck and publish on MQTT
6. **Periodically collect** OpenADR reports during execution and publish aggregated FlexStatus on MQTT
7. **Receive** FlexRelease and translate to OpenADR event cancellation

**Settlement**:
1. **Generate** DeliveryReport from device metering data (requested vs. actual per slot)
2. **Publish** DeliveryReport on MQTT

This bridge logic is **manufacturer-specific** — each HEMS vendor implements it in their backend, including their own MILP or optimization approach for device-level dispatch. The profile standardizes the MQTT and OpenADR interfaces on either side.

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

---

## Protocol Fitness Across Markets

The dual-protocol stack serves all serviceable markets (Tier 2 primary, Tier 3 secondary) with the same message flow. Only the upstream trigger differs.

### Why MQTT + OpenADR Covers Multiple Markets

| Market Requirement | How MQTT Addresses It | How OpenADR Addresses It |
|---|---|---|
| **Fast fan-out** (mFRR, congestion) | Pub/sub delivers to all backends in one publish | N/A — backend-to-device layer |
| **Segment targeting** (congestion, nFAS) | Topic `flex/{agg}/{segment_id}/request` is purpose-built | N/A — addressing is at MQTT layer |
| **Opt-in/opt-out** (all markets) | FlexResponse aggregates acceptance | optIn/optOut is native to OpenADR VEN |
| **Delivery telemetry** (mFRR verification) | FlexStatus periodic updates at QoS 0 | oadrReport (TELEMETRY_USAGE) per device |
| **Scheduled activation** (intraday, day-ahead) | FlexRequest with future timestamp + duration | oadrDistributeEvent with scheduled dtstart |
| **Price signals** (dynamic tariffs) | Aggregator coordinates pool response | ELECTRICITY_PRICE signal type is native |
| **Market-facing interface** (flex markets) | N/A — separate USEF/REST layer needed | N/A — neither protocol covers market bidding |

### Protocol Suitability Summary

| Market | MQTT | OpenADR | Recommended |
|---|---|---|---|
| **mFRR** | ★★★ | ★★★ | MQTT + OpenADR |
| **Congestion management** | ★★★ | ★★★ | MQTT + OpenADR |
| **nFAS (P-based)** | ★★★ | ★★★ | MQTT + OpenADR |
| **Intraday** | ★★★ | ★★ | MQTT + OpenADR |
| **Day-ahead** | ★★ | ★★★ | Either sufficient |
| **Local flex markets** | ★★★ | ★★ | MQTT + OpenADR (activation) + USEF/REST (market) |
| **Dynamic tariffs** | ★★ | ★★★ | OpenADR primary, MQTT for coordination |

★★★ = excellent fit, ★★ = works well

### What This Stack Does NOT Cover

- **Tier 1 markets** (FCR, aFRR): Require dedicated SCADA/PLC with deterministic sub-second to 4-second control. Fundamentally different architecture.
- **Q-based voltage support**: Requires direct inverter-level reactive power control (SunSpec Modbus / IEC 61850).
- **Market bidding/settlement**: The upstream market interface (aggregator ↔ TSO/DSO/market platform) needs USEF, platform-specific REST APIs, or existing market processes — not MQTT/OpenADR.

See `../protocol-analysis-mqtt-vs-openadr.md` for the full analysis.
