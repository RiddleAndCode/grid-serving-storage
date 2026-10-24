# MQTT vs OpenADR: Protocol Analysis for the HEMS Pipeline

**Context:** Grid-Serving Storage interoperability profile — evaluating protocol choices for the Aggregator ↔ HEMS Backend ↔ HEMS Device communication pipeline.

**Date:** 2026-10-24

---

## 1. Pro/Con Analysis

### 1.1 MQTT (v5) — for Aggregator ↔ HEMS Backend

| Pros | Cons |
|------|------|
| Lightweight pub/sub scales to 10k+ backends trivially | No energy-domain semantics — you define your own data model (FlexRequest etc.) |
| Asynchronous, event-driven — natural fit for flex signals | No built-in concept of "opt-in/opt-out" or market signals |
| QoS levels (0/1/2) give delivery guarantees without protocol bloat | Requires custom topic hierarchy design and governance |
| JSON payloads — easy for cloud backends to parse and process | No standardization body for energy use cases (yet) |
| TLS 1.3 + client certs = strong security without protocol overhead | Interoperability depends on your custom schema, not on protocol alone |
| Message expiry (v5) prevents stale activations — critical for grid safety | Broker is a single point of failure (needs HA clustering) |
| Session expiry enables graceful reconnection | No native device-level semantics (power, SoC, schedules) |
| Vendor-neutral — any HEMS backend can implement an MQTT client | Less regulatory/certification backing in the energy sector |
| Low bandwidth — works well even on constrained connections | |

### 1.2 OpenADR 2.0b — for HEMS Backend ↔ HEMS Device

| Pros | Cons |
|------|------|
| Energy-domain native: events, signals, opt-in/opt-out built in | XML-heavy, verbose — higher bandwidth and parsing overhead |
| Austrian regulatory alignment (E-Control, APCS context) | VTN/VEN architecture is client-server, not pub/sub — scales differently |
| Certification program (OpenADR Alliance) ensures interoperability | Profile B push mode requires persistent connections per device |
| Built-in prosumer sovereignty (optIn/optOut per event) | Complexity overhead for simple charge/discharge signals |
| Maps to IEC CIM / EI (Energy Interop) standards | Limited adoption outside demand response (less suited for real-time telemetry) |
| Proven in US utility DR programs, gaining traction in EU | XML schema evolution is slow vs. JSON schema evolution |
| Supports multiple signal types (price, load, simple) | Each HEMS manufacturer needs VEN implementation or middleware |
| Security built into spec (XML signatures, TLS) | OpenADR 3.0 is emerging — 2.0b may become legacy |

---

## 2. SWOT Analysis

### 2.1 MQTT for the full pipeline (Aggregator → Backend → Device)

| | Positive | Negative |
|---|---|---|
| **Internal** | **Strengths:** Uniform protocol stack (no bridge needed), massive ecosystem, real-time telemetry and control in one protocol, trivial to add new message types | **Weaknesses:** No energy-domain semantics (everything is custom), no regulatory backing or certification, no built-in opt-in/opt-out or prosumer protection, interoperability only if everyone adopts the same schema |
| **External** | **Opportunities:** Sparkplug B adds industrial structure to MQTT, could become de-facto if Austrian market adopts the profile, MQTT 5 features enable sophisticated routing, low barrier to entry accelerates pilot adoption | **Threats:** EU regulation may mandate OpenADR or EEBUS for devices, fragmentation risk without standardization, competing vendors may refuse non-standard protocol, grid operators may not trust non-certified protocol for grid-critical signals |

### 2.2 OpenADR for the full pipeline (Aggregator → Backend → Device)

| | Positive | Negative |
|---|---|---|
| **Internal** | **Strengths:** End-to-end energy semantics with standardized signals, regulatory alignment and certification path, prosumer sovereignty built in, proven interoperability across vendors | **Weaknesses:** VTN-VEN hierarchy doesn't map well to aggregator pooling, XML overhead at backend-to-backend scale, scaling to 100k+ devices requires heavy VTN infrastructure, less suited for high-frequency telemetry |
| **External** | **Opportunities:** OpenADR 3.0 promises REST/JSON (addresses XML pain), EU Clean Energy Package may favor OpenADR-like standards, growing Austrian/EU DR market | **Threats:** OpenADR 3.0 timeline uncertain, EEBUS or IEEE 2030.5 may win in the EU device market, vendor lock-in to OpenADR Alliance certification costs, MQTT-based approaches may win on developer experience |

### 2.3 Dual-protocol approach: MQTT upstream + OpenADR downstream (current design)

| | Positive | Negative |
|---|---|---|
| **Internal** | **Strengths:** Best of both (MQTT scales for backends, OpenADR for device compliance), aggregator doesn't need to speak OpenADR to every device, privacy preserved (no per-device data on MQTT), each layer uses its natural-fit protocol | **Weaknesses:** Protocol bridge complexity at HEMS Backend, two protocol stacks to maintain and secure, translation layer can introduce latency and semantic loss, testing/debugging spans two protocol worlds |
| **External** | **Opportunities:** Profile could become reference architecture for Austrian market, HEMS Backend as bridge is a product opportunity, can swap either layer independently as standards evolve | **Threats:** OpenADR 3.0 or EEBUS adoption could shift the ground under one or both layers, regulation might mandate end-to-end OpenADR, competing profiles may choose single-protocol for simplicity |

---

## 3. Existing Protocols for This Communication

Several established and emerging protocols address parts or all of this pipeline:

### 3.1 Protocol Landscape

| Protocol | Scope | Relevance to Our Profile |
|---|---|---|
| **OpenADR 2.0b / 3.0** | DR signaling (utility → aggregator → device) | Already in profile for device layer. 3.0 moves to REST/JSON |
| **EEBUS (SPINE/SHIP)** | HEMS ↔ device (local network) | Strong in DACH region, covers EV, heat pump, battery. Complementary |
| **IEEE 2030.5 (SEP2)** | Utility ↔ device (smart grid) | US-centric but gaining EU interest. REST-based, covers DER management |
| **IEC 61850** | Substation/DER communication | Too heavy for residential, but relevant for aggregator ↔ DSO |
| **IEC 62746-10-1 (CIM for DR)** | Information model for flexibility | Our CIM alignment already references this |
| **OCPP 2.0.1** | EV charging station management | Relevant if EVs are in the flex pool |
| **Sparkplug B** | Industrial IoT over MQTT | Adds namespace, state management, birth/death semantics to MQTT — could formalize the MQTT layer |
| **S2 protocol (FAN/flexiblepower)** | Dutch standard for device flexibility | Models flexibility of devices (fill rate, curtailment) — very relevant |
| **USEF** | Universal Smart Energy Framework | End-to-end framework for flexibility trading (NL origin, EU adoption). Defines aggregator ↔ prosumer roles |
| **VHPready** | German virtual power plant standard | Aggregator ↔ DER communication for pooling — directly comparable |
| **BSI TR-03109 (Smart Meter Gateway)** | German/Austrian secure metering infra | Could become transport layer if Austrian SMGW rollout mandates it |

### 3.2 Most Directly Comparable

1. **USEF + S2 protocol** (Netherlands) — The closest existing end-to-end framework. S2 defines how devices expose their flexibility (e.g., "I can shift 3 kW for 2 hours") and USEF defines the market/aggregator roles. Our FlexRequest/FlexResponse maps conceptually to USEF's flex trading.

2. **VHPready** (Germany) — Specifically for virtual power plant aggregation of distributed assets. Defines the aggregator ↔ device control interface.

3. **OpenADR 3.0** (emerging) — If it delivers on its REST/JSON promise, it could serve as a single protocol for the full pipeline, potentially eliminating the need for the MQTT layer.

4. **EEBUS** — Very strong in Austria/Germany for local HEMS-to-device communication. Could replace or complement OpenADR at the device layer, especially for heat pumps and batteries.

---

## 4. Tier Scoping Decision

### 4.1 Three Tiers of Aggregator Use Cases

Aggregator use cases split into three tiers based on response time requirements:

| Tier | Use Cases | Full Activation Time | Communication Need |
|---|---|---|---|
| **Tier 1 — Fast control loops** | FCR (primary reserve), aFRR (secondary reserve), voltage/Q support | Sub-second to 5 minutes | Deterministic, continuous setpoint tracking |
| **Tier 2 — Event-driven flex** | Grid congestion (redispatch), mFRR (tertiary reserve) | 12.5–15 minutes | Asynchronous signals, opt-in/opt-out |
| **Tier 3 — Scheduled/market** | Peak shaving, portfolio optimization, day-ahead DR | Hours ahead | Schedule-based, market-coupled |

### 4.2 Scope: Tier 2 (with Tier 3 reachable)

**This profile targets Tier 2.** Tier 1 is explicitly out of scope.

**Rationale:** Tier 1 (FCR, aFRR) requires deterministic, sub-second to 4-second communication cycles that cannot be reliably delivered through cloud-mediated HEMS backends. These use cases require dedicated SCADA/PLC hardware (e.g., Beckhoff TwinCAT, Siemens S7) with direct controller connections — a fundamentally different architecture that bypasses the HEMS stack entirely.

Tier 3 (scheduled DR, portfolio optimization) is naturally reachable from the Tier 2 architecture — if you can activate flex in 12.5 minutes, you can certainly schedule it hours ahead. The MQTT + OpenADR stack handles both.

### 4.3 mFRR Response Time Requirements (Austrian/ENTSO-E Context)

mFRR is the balancing product that fits the HEMS architecture. Key timing parameters:

| Parameter | Value |
|---|---|
| **Full Activation Time (FAT)** | **12.5 minutes** (ENTSO-E standard, APG compliant) |
| **Notification lead time** | 7.5–15 minutes before delivery period |
| **Delivery period** | 15-minute market intervals (quarter-hourly) |
| **Minimum duration** | 15 minutes (one interval), can be extended |
| **Ramping** | Must reach full capacity within FAT from activation signal |
| **Deactivation** | Ramp down within same FAT window after release signal |

**Signal chain timing budget (Tier 2):**

```
Aggregator publishes FlexRequest via MQTT     ~100ms
MQTT broker delivery to HEMS Backend           ~100ms
Backend translates to OpenADR event            ~500ms
OpenADR push to HEMS devices                   ~1–2s
Device local evaluation + response             ~1–5s
Backend aggregates responses via MQTT          ~1–2s
                                         ─────────────
Total signal chain (estimate)                  ~5–10s
Available headroom before FAT deadline         ~12 minutes
```

The architecture has ~12 minutes of headroom — more than sufficient for opt-in/opt-out negotiation, partial pool activation, and retry logic.

### 4.4 Why Tier 1 Requires a Different Architecture

| Aspect | Tier 2 (mFRR, congestion) | Tier 1 (FCR, aFRR) |
|---|---|---|
| Signal path | Cloud → Backend → Device | Controller → Device (direct) |
| Latency tolerance | Seconds to minutes | Milliseconds to seconds |
| Communication | Asynchronous, event-based | Continuous, deterministic |
| Infrastructure | MQTT broker, HEMS backends | SCADA/PLC (Beckhoff, Siemens), dedicated gateways |
| Prosumer opt-out | Yes (soft signal) | No (prequalified, contracted capacity) |
| Protocol | MQTT + OpenADR | IEC 61850, IEC 60870-5-104, proprietary SCADA |

---

## 5. Energy Markets Serviceable via This Architecture

The MQTT + OpenADR dual-protocol stack (Tier 2 + Tier 3) enables participation in several energy markets and grid services:

### 5.1 Balancing Markets

| Market / Product | Operator | Fit | Notes |
|---|---|---|---|
| **mFRR (Tertiary Reserve)** | APG (Austrian TSO) | **Excellent** | 12.5 min FAT, quarter-hourly. Primary target market for this architecture |
| **aFRR (Secondary Reserve)** | APG | **Marginal** | 5 min FAT, 4s setpoint cycle. Technically borderline — could work with tight MQTT latency, but not reliably via HEMS backends. Out of scope |
| **FCR (Primary Reserve)** | APG / ENTSO-E | **Not feasible** | 30s activation, continuous. Requires SCADA. Out of scope |

### 5.2 Congestion Management / Redispatch

| Market / Product | Operator | Fit | Notes |
|---|---|---|---|
| **Local congestion management** | DSO (e.g., Netz NÖ, Wiener Netze) | **Excellent** | Core use case. DSO signals grid stress → Aggregator activates segment-level flex. Minutes of lead time, topological addressing via grid segments |
| **Redispatch 3.0 (emerging EU)** | DSO / TSO coordination | **Good** | As EU redispatch frameworks evolve to include distributed assets, this architecture is positioned to participate |
| **Non-frequency ancillary services (nFAS)** | DSO | **Good** | Voltage support via active power adjustment, congestion prevention. Emerging market in Austria |

### 5.3 Wholesale / Intraday Markets

| Market / Product | Operator | Fit | Notes |
|---|---|---|---|
| **Intraday continuous trading** | EXAA / EPEX SPOT | **Good** | Aggregator optimizes pool against 15-min intraday prices. Activation via MQTT well within market gate closure times |
| **Day-ahead market** | EXAA / EPEX SPOT | **Good** | Schedule-based (Tier 3). Aggregator commits pool capacity day-ahead, dispatches via the same MQTT/OpenADR stack |
| **Intraday auctions (15-min)** | EPEX SPOT | **Good** | Quarter-hourly auctions fit the 15-min delivery granularity |

### 5.4 Flexibility Markets (Emerging)

| Market / Product | Operator | Fit | Notes |
|---|---|---|---|
| **Local flexibility markets** | DSO / market platform | **Excellent** | Emerging across EU (e.g., NODES, Equigy, Enera). Aggregator bids flex from pool into local market. MQTT handles activation |
| **Peer-to-peer flexibility trading** | Platform-based | **Potential** | Future market model. Architecture supports it but market doesn't exist yet in Austria |
| **Capacity markets / strategic reserve** | TSO / regulator | **Good** | If Austria introduces capacity mechanisms, aggregated storage is eligible. Activation timing is comfortable |

### 5.5 Behind-the-Meter Optimization

| Market / Product | Operator | Fit | Notes |
|---|---|---|---|
| **Self-consumption optimization** | Prosumer / HEMS | **Inherent** | Not an aggregator market per se, but the HEMS device does this locally. Aggregator flex signals must respect this baseline |
| **Dynamic tariff response** | Retailer / BRP | **Good** | HEMS responds to price signals (e.g., hourly spot tariffs under Austrian smart meter rollout). Aggregator can coordinate pool response |
| **Grid fee optimization** | Prosumer | **Good** | Avoid peak grid fees by shifting consumption. Can be coordinated at pool level |

### 5.6 Market Fitness Summary

```
                        ┌─────────────────────────────────┐
                        │   Markets by Response Time       │
                        │                                  │
  Out of scope          │  FCR ◄── aFRR                   │  Tier 1: SCADA
  (SCADA required)      │  (<30s)   (<5min)                │
                        ├──────────────────────────────────┤
                        │                                  │
  ★ PRIMARY TARGET      │  mFRR    Congestion  nFAS       │  Tier 2: MQTT+OpenADR
                        │  (12.5m) (minutes)   (minutes)  │
                        ├──────────────────────────────────┤
                        │                                  │
  Also serviceable      │  Intraday  Day-ahead  Local     │  Tier 3: MQTT+OpenADR
                        │  (15min)   (hours)    flex mkts │  (same stack)
                        │                                  │
                        │  Tariff    Grid fee   Capacity  │
                        │  response  optim.     markets   │
                        └─────────────────────────────────┘
```

The architecture's sweet spot is **mFRR + congestion management** (Tier 2), with natural reach into **intraday trading + emerging flex markets** (Tier 3). This covers the most commercially relevant markets for distributed residential/commercial storage in Austria today.

---

## 6. Protocol Fitness by Market — Detailed Analysis

This section maps each serviceable market to its communication requirements and evaluates which protocols are best suited.

### 6.1 Primary Markets (Tier 2)

#### mFRR (Tertiary Balancing Reserve)

| Requirement | Detail | Best Protocol | Why |
|---|---|---|---|
| Activation signal | TSO/aggregator → pool, 12.5 min FAT | **MQTT** | Pub/sub fan-out to all backends in one publish |
| Confirmation | Backends report accepted capacity | **MQTT** | FlexResponse aggregated per backend |
| Delivery telemetry | Periodic power/SoC during activation | **MQTT** | FlexStatus at QoS 0, lightweight |
| Device dispatch | Backend → individual devices | **OpenADR 2.0b** | oadrDistributeEvent with optIn/optOut |
| Metering/verification | Post-delivery settlement proof | **OpenADR EiReport** | TELEMETRY_USAGE, or separate metering interface |
| Market interface | Aggregator ↔ TSO (APG) | Out of scope | Existing balancing market platform (MOL, LIBRA) |

**Verdict:** MQTT + OpenADR is the natural fit. mFRR's activation-confirmation-delivery-release cycle maps 1:1 to FlexRequest → FlexResponse → FlexStatus → FlexRelease. The 12.5 min FAT gives massive headroom.

#### Local Congestion Management (DSO Redispatch)

| Requirement | Detail | Best Protocol | Why |
|---|---|---|---|
| Segment-targeted activation | DSO identifies overloaded segment → aggregator activates only that segment | **MQTT** | Topic `flex/{agg}/{segment_id}/request` is purpose-built for this |
| Bidirectional flex | Charge (absorb surplus) or discharge (reduce load) | **MQTT** | `direction` field in FlexRequest |
| Fast opt-in/opt-out | Devices decide locally based on SoC, user prefs | **OpenADR** | optIn/optOut is native |
| Topological addressing | Grid segment = ConnectivityNode | **MQTT topic hierarchy** | Segments as addressing units (Decision D8) |
| DSO ↔ Aggregator | Grid stress signal, verification | Out of scope | Likely IEC 61850 / CIM based |

**Verdict:** MQTT + OpenADR is excellent. This is the use case the profile was designed for. The segment-based MQTT topic structure is a differentiator — no other protocol offers this natively.

#### Non-Frequency Ancillary Services (nFAS)

| Requirement | Detail | Best Protocol | Why |
|---|---|---|---|
| Active power adjustment | Reduce/increase feed-in per segment | **MQTT + OpenADR** | Same as congestion management |
| Voltage support (P-based) | Shift active power to influence voltage | **MQTT + OpenADR** | Same FlexRequest with direction |
| Voltage support (Q-based) | Reactive power from inverters | **Neither** | Requires inverter-level Q control (SunSpec Modbus / IEC 61850) |

**Verdict:** MQTT + OpenADR covers P-based nFAS. Q-based voltage support is out of scope — needs direct inverter control, same architectural gap as Tier 1.

### 6.2 Secondary Markets (Tier 3)

#### Intraday Continuous / 15-min Auctions (EPEX SPOT / EXAA)

| Requirement | Detail | Best Protocol | Why |
|---|---|---|---|
| Schedule delivery | Aggregator commits pool for specific 15-min interval | **MQTT** | FlexRequest with future timestamp + duration |
| Gate closure timing | Up to 5 min before delivery (intraday continuous) | **MQTT** | Comfortable margin |
| Portfolio optimization | Aggregator decides when/how much to activate | Internal | Not a protocol question |
| Activation | Same as mFRR but scheduled | **MQTT + OpenADR** | Identical message flow |

**Verdict:** Same MQTT + OpenADR stack. The only difference vs. mFRR is that activation is scheduled rather than reactive. FlexRequest already supports this.

#### Day-Ahead Market

| Requirement | Detail | Best Protocol | Why |
|---|---|---|---|
| Schedule-based | Hours ahead, known delivery windows | **MQTT** or **OpenADR** | Either works given the relaxed timing |
| Low urgency | No real-time pressure | **OpenADR** or **USEF** | Event-based scheduling is native to both |
| Aggregated commitment | Aggregator commits MW, dispatches internally | **MQTT** | For internal pool dispatch |

**Verdict:** MQTT + OpenADR works, but OpenADR alone (especially 3.0 with REST/JSON) or USEF would also be sufficient. MQTT adds value only if you need the same fast fan-out pattern, which for day-ahead you don't strictly need.

#### Local Flexibility Markets (NODES, Equigy, emerging)

| Requirement | Detail | Best Protocol | Why |
|---|---|---|---|
| Bid/offer submission | Aggregator offers flex capacity to market platform | **Market-specific API** | USEF flex trading or platform REST API — not MQTT/OpenADR |
| Activation upon clearing | Market clears → aggregator activates pool | **MQTT + OpenADR** | Same activation flow as mFRR |
| Location-specific | Flex needed in specific grid area | **MQTT** | Segment addressing is a strong fit |
| Settlement/verification | Proof of delivery | **OpenADR EiReport** | Or dedicated metering interface |

**Verdict:** MQTT + OpenADR for activation. Market interface needs USEF or platform-specific REST API on top. The dual-protocol stack handles the "last mile" (aggregator → devices) but not the market-facing side.

#### Dynamic Tariff Response

| Requirement | Detail | Best Protocol | Why |
|---|---|---|---|
| Price signal distribution | Retailer/BRP sends hourly prices | **OpenADR** | `ELECTRICITY_PRICE` signal type is purpose-built |
| Coordinated pool response | Aggregator coordinates to avoid herd behavior | **MQTT** | Aggregator can dampen/stagger activation |
| Device-level decision | HEMS optimizes against price + SoC + user prefs | **OpenADR** | Price event, device decides locally |

**Verdict:** OpenADR is strongest here — price signals are a core OpenADR capability. MQTT adds value for coordinated pool response to prevent grid stress from synchronized price reaction.

#### Grid Fee Optimization

| Requirement | Detail | Best Protocol | Why |
|---|---|---|---|
| Peak avoidance signals | Shift consumption away from network fee peaks | **MQTT** or **OpenADR** | Either works; low real-time requirement |
| Prosumer preference | User sets cost optimization targets | Local HEMS | Not an inter-system protocol question |

**Verdict:** Low protocol sensitivity — either protocol handles this comfortably.

### 6.3 Protocol Suitability Matrix

| Market | MQTT | OpenADR 2.0b | USEF | IEC 61850 | REST/Custom | Recommended Stack |
|---|---|---|---|---|---|---|
| **mFRR** | ★★★ | ★★★ | ★★ | - | - | **MQTT + OpenADR** |
| **Congestion mgmt** | ★★★ | ★★★ | ★★ | - | - | **MQTT + OpenADR** |
| **nFAS (P-based)** | ★★★ | ★★★ | ★★ | - | - | **MQTT + OpenADR** |
| **nFAS (Q-based)** | - | - | - | ★★★ | - | IEC 61850 / SunSpec (out of scope) |
| **Intraday** | ★★★ | ★★ | ★★★ | - | ★★ | **MQTT + OpenADR** |
| **Day-ahead** | ★★ | ★★★ | ★★★ | - | ★★ | OpenADR or USEF sufficient; MQTT optional |
| **Local flex markets** | ★★★ | ★★ | ★★★ | - | ★★★ | **MQTT + OpenADR** (activation) + **USEF/REST** (market) |
| **Dynamic tariffs** | ★★ | ★★★ | ★★ | - | ★ | **OpenADR** primary, MQTT for coordination |
| **Grid fee optimization** | ★★ | ★★ | ★★ | - | ★★ | Either; low real-time requirement |

**Legend:** ★★★ = excellent fit, ★★ = works well, ★ = possible but suboptimal, - = not suited

### 6.4 Conclusion

**MQTT + OpenADR covers all primary markets and most secondary markets with one stack.** The only gaps are:

1. **Market-facing interfaces** (flex bidding, settlement) — need USEF or platform-specific REST APIs on top of the activation stack
2. **Q-based voltage support** — needs direct inverter control (SunSpec Modbus / IEC 61850), fundamentally different architecture
3. **Day-ahead / price signals** — OpenADR alone would suffice, but using MQTT doesn't hurt

The dual-protocol design is validated: it is not just a congestion management tool — it is a **general-purpose flexibility activation stack** for Tier 2 + Tier 3 markets. One protocol pair, many markets.

---

## 7. Strategic Assessment

The dual-protocol choice (MQTT upstream, OpenADR downstream) is well-reasoned for the current landscape:

- **Main strategic risk:** OpenADR 3.0 or EEBUS adoption in Austria could shift the ground under one or both layers.
- **Main strategic opportunity:** No dominant standard exists yet for the aggregator ↔ HEMS backend interface specifically — the MQTT-based profile could fill that gap.
- **Watch items:** OpenADR 3.0 timeline, Austrian SMGW rollout decisions, EEBUS adoption trajectory in DACH, EU Clean Energy Package implementation acts.
