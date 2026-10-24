# 06 — Design Decisions

Key decisions made in this interoperability profile and their rationale.

## D1: Aggregator-Centric Architecture (Not DSO-Direct)

**Decision**: The **Technical Aggregator** is the coordination role between grid needs and distributed storage. The DSO does not communicate directly with HEMS devices or backends.

**Alternatives considered**:
- DSO communicates directly with devices (our initial approach)
- DSO communicates with HEMS backends directly

**Rationale**:
- Aligns with the **Austrian system architecture for flexible assets** (Smart Grids Austria / AIT)
- The Technical Aggregator is an established market role that already interfaces with DSO and wholesale markets
- Decouples grid operations from HEMS device management — DSO signals grid stress, aggregator handles coordination
- Enables **market participation** (balancing energy, redispatch) beyond pure grid relief
- Multiple HEMS manufacturers can be coordinated through one aggregator interface

**Consequence**: DSO ↔ Aggregator interface is out of scope. This profile focuses on what's below the aggregator.

## D2: Dual Protocol — MQTT (Backend) + OpenADR (Device)

**Decision**: Use **MQTT v5** between Aggregator and HEMS Backends, and **OpenADR 2.0b or 3.1** between HEMS Backends and HEMS Devices.

**Alternatives considered**:
- MQTT end-to-end (aggregator to device)
- OpenADR end-to-end (aggregator to device)
- REST APIs between aggregator and backends

**Rationale**:
- **OpenADR on the device** is the Austrian standard for flexible asset control (per Smart Grids Austria architecture). The HEMS device must speak OpenADR regardless of what the backend uses upstream.
- **Both OpenADR versions** serve the same profile role — the Backend abstracts version differences from the aggregator. See D15 for version selection rationale.
- **MQTT between aggregator and backends** is better suited for device coordination: pub/sub scales to many backends, async responses match device polling times, lightweight JSON vs. OpenADR XML overhead.
- The HEMS Backend is a natural **protocol bridge** — each manufacturer already operates a backend, adding MQTT is trivial.
- REST APIs would require the aggregator to integrate per-vendor APIs. MQTT standardizes the interface.

**Consequence**: HEMS Backend must implement both MQTT and OpenADR. This is acceptable because backends are server-side infrastructure, not constrained embedded devices.

## D3: Soft Signal with Local Device Autonomy

**Decision**: The aggregator sends a **soft flex-request** with bounds. The HEMS device decides locally what it can deliver (via OpenADR optIn/optOut).

**Alternatives considered**:
- Hard override (aggregator directly controls storage setpoint)
- Pure market signal (price-based incentive, no direct request)

**Rationale**:
- Prosumer acceptance — hard override faces regulatory and consumer resistance
- Safety — only the local HEMS knows real-time battery state and limits
- Liability — if aggregator hard-overrides and damages a battery, liability is unclear
- OpenADR's event model naturally supports this: VEN responds with optIn/optOut
- Aligns with Austrian regulatory framework (prosumer sovereignty)

**Consequence**: Aggregator cannot guarantee exact flex volume. Must plan with statistical confidence based on aggregated response patterns.

## D4: HEMS Backend as Device Aggregation Point

**Decision**: The HEMS Backend aggregates individual device responses into **backend-level messages** on MQTT. The aggregator sees backend summaries, not individual devices.

**Alternatives considered**:
- Individual device messages on MQTT (aggregator sees every device)
- Flat reporting (no aggregation, raw data forwarded)

**Rationale**:
- **Privacy**: Aggregator does not need per-household data (SoC, power consumption patterns)
- **Scalability**: 1 aggregated response message vs. hundreds of individual device messages per event
- **Simplicity**: Aggregator manages backends (handful), not devices (thousands)
- **Manufacturer autonomy**: Each HEMS vendor handles their devices internally

**Consequence**: Aggregator has less granularity. For settlement and verification, more detailed reports can be requested as a separate (non-real-time) process.

## D5: OpenADR 2.0b Profile B (Push Mode) / 3.1 Subscriptions

**Decision**: Use OpenADR 2.0b **Profile B** with **PUSH mode**, or OpenADR 3.1 with **subscriptions** (webhook or MQTT notification).

**Alternatives considered**:
- Profile A (simpler, pull-only)
- Profile B with PULL mode (VEN polls VTN)
- 3.1 polling only (no subscriptions)

**Rationale**:
- **Push mode** (2.0b) / **subscriptions** (3.1) deliver events immediately — critical for time-sensitive grid relief
- Pull mode introduces latency (VEN must poll at intervals)
- Profile B supports both push and pull, plus reporting — needed for status feedback
- OpenADR 3.1 adds MQTT as a subscription transport — the same broker can serve both aggregator↔backend and VTN→VEN notification channels
- 3.1 polling (GET /events every 15s) is acceptable as a fallback when subscriptions are not configured

**Consequence**: For 2.0b, HEMS device must support HTTP server capability (to receive pushed events). For 3.1, the VEN can choose between webhook callbacks, MQTT subscriptions, or polling — more flexible deployment options.

## D6: JSON on MQTT, XML on OpenADR

**Decision**: Use **JSON** for MQTT payloads (aggregator ↔ backend) and standard **XML** for OpenADR (backend ↔ device).

**Rationale**:
- OpenADR 2.0b mandates XML — no choice on the device side
- JSON for the MQTT layer is simpler, lighter, and universally supported in backend systems
- The HEMS Backend handles the JSON ↔ XML translation as part of its bridge function
- Backend developers work with both formats daily — no additional burden

## D7: Fail-Safe to Prosumer Control

**Decision**: Every failure mode at every layer defaults to **normal prosumer-controlled operation**.

**Rationale**:
- Prosumer sovereignty — flex participation is exceptional, not the default
- Safety — a device in normal operation is in a known, tested state
- Regulatory — aggregator intervention must be exceptional and time-limited
- OpenADR event duration expiry provides a natural fail-safe timer

**Consequence**: Aggregator must actively send requests and releases. No persistent standing orders.

## D9: Segment-Agnostic HEMS Scope (Residential to Commercial)

**Decision**: The profile does **not** restrict the type of HEMS or storage installation. It applies equally to **residential prosumers** (e.g., single-family home with PV + battery) and **commercial sites** (e.g., warehouse with large-scale storage).

**Alternatives considered**:
- Scope to residential HEMS only (simpler, more homogeneous)
- Scope to commercial EMS only (larger flex volumes, fewer participants)

**Rationale**:
- The challenge problem statement explicitly covers "relatively small storage units in households to large storage systems at commercial sites"
- The interoperability profile addresses the **interface** between HEMS Backends and the Technical Aggregator — this interface is the same regardless of what's behind the HEMS
- The HEMS is treated as a **black box** behind a standardized protocol interface (OpenADR toward device, MQTT toward aggregator)
- Restricting to one segment would reduce the available flexibility pool and limit reusability
- The Austrian system architecture (Smart Grids Austria) does not differentiate by installation size at the interface level

**Consequence**: The profile must accommodate heterogeneous device capabilities (small residential batteries vs. large commercial storage). The flex-request/response pattern handles this naturally — each device reports what it can deliver, regardless of size.

## D10: Four-Phase Interaction Model (Observe → Plan → Dispatch → Settle)

**Decision**: The system operates as a **continuous four-phase loop**, not purely event-driven activation.

**Alternatives considered**:
- Pure event-driven (aggregator sends flex-requests only when triggered)
- Continuous control (aggregator permanently steers devices)

**Rationale**:
- **Observe phase** (continuous, bottom-up) gives the aggregator an always-current picture of portfolio capacity — enabling proactive market positioning, not just reactive grid relief
- **Plan phase** (aggregator-internal) allows optimization before any dispatch — the aggregator can position in markets knowing what it can actually deliver
- **Dispatch phase** (on demand, top-down) activates flex only when needed — preserving prosumer sovereignty during normal operation
- **Settle phase** (post-event) closes the loop with verified delivery — enabling reliability scoring that feeds back into future planning

**Consequence**: The MQTT interface must support both continuous observation messages (SiteStateSnapshot, SiteFlexOffer) and event-driven dispatch messages (AggregatorDispatch, DispatchAck, FlexRelease). The topic structure reflects this split (`observe/` vs. `dispatch/` vs. `settle/`).

## D11: Bottom-Up Observation (SiteStateSnapshot + SiteFlexOffer)

**Decision**: HEMS Backends continuously publish **SiteStateSnapshot** (current state) and **SiteFlexOffer** (flexibility envelope with constraints) to the aggregator, even when no dispatch is active.

**Alternatives considered**:
- On-demand polling (aggregator queries backends when needed)
- State reporting only during active dispatch events
- Device-level reporting to aggregator

**Rationale**:
- **Proactive market positioning**: The aggregator needs an always-current picture of portfolio capacity to bid into markets (mFRR, intraday) before activation triggers arrive
- **Learned flexibility**: flex_up/flex_down potentials are measured and learned from actual device ramp behavior — not nameplate capacity. This requires continuous observation
- **MILP readiness**: The aggregator MILP needs per-backend envelopes, constraints, forecasts, and reliability scores as inputs. These must be available before any dispatch decision
- **Backend as abstraction layer**: The backend aggregates device-level data into a site-level view — the aggregator sees flexibility envelopes, not individual batteries

**Consequence**: The MQTT topic structure includes an `observe/` subtree for continuous bottom-up messages. SiteStateSnapshot is published at QoS 0 with retained flag (latest state). SiteFlexOffer at QoS 1 with expiry matching `valid_until`.

## D12: Two-Level Hierarchical Optimization (MILP)

**Decision**: Optimization happens at **two levels** — the aggregator optimizes across backends, each backend optimizes across its devices. Both are anticipated to use MILP (Mixed-Integer Linear Programming).

**Alternatives considered**:
- Single-level optimization (aggregator optimizes down to device level)
- No optimization (simple proportional dispatch based on capacity)
- Rule-based dispatch (priority queues, round-robin)

**Rationale**:
- **Privacy**: The aggregator never sees per-device data. It treats each backend as an opaque flexibility envelope with constraints.
- **Scalability**: Aggregator solves for N backends (handful to dozens), not N×M devices (thousands). Each backend solves for its own M devices independently.
- **Autonomy**: Each manufacturer's backend knows its devices best — heterogeneous device models, firmware versions, local conditions. The backend MILP can exploit this knowledge.
- **Separation of concerns**: The aggregator optimizes the portfolio (market obligations, fairness, reliability). The backend optimizes device dispatch (SoC management, ramp rates, user preferences).
- **MILP specifically** fits because the problem has linear constraints (power bounds, ramp rates, connection limits) with integer decisions (device on/off, minimum activation duration).

**Consequence**: The SiteFlexOffer must provide enough information for the aggregator MILP (envelope, constraints, forecast, reliability) without exposing per-device details. The AggregatorDispatch must be expressed as a goal (direction + delta_kw + schedule) that the backend can decompose freely.

**Note**: MILP is the anticipated optimization method but the profile does not mandate it. Any optimization approach that respects the observed constraints and produces valid dispatch goals is compliant.

## D13: Tier 2 Scope — mFRR and Congestion as Primary Markets

**Decision**: The profile targets **Tier 2** (event-driven flex, 12.5–15 min response time) as its primary operating range. **Tier 1** (FCR, aFRR) is explicitly out of scope. **Tier 3** (day-ahead, intraday, flex markets) is naturally reachable with the same stack.

**Alternatives considered**:
- Include Tier 1 (FCR/aFRR) with tighter latency requirements
- Scope only to congestion management (single market)
- Design separate protocol stacks per market

**Rationale**:
- **Tier 1 requires SCADA/PLC hardware** (e.g., Beckhoff TwinCAT, Siemens S7) with deterministic sub-second to 4-second control loops — fundamentally incompatible with cloud-mediated HEMS backends
- **mFRR's 12.5 min FAT** (ENTSO-E standard, APG compliant) provides ~12 minutes of headroom after the ~5–10 second signal chain — comfortable for opt-in/opt-out negotiation and retry logic
- **The dispatch cycle is market-agnostic** — the same message flow serves congestion management, mFRR, intraday trading, and flex market activation. Only the upstream trigger differs
- **One protocol pair, many markets** — avoids the complexity of maintaining separate stacks per market product

**Consequence**: The profile does not address FCR or aFRR. Aggregators serving those markets need a parallel SCADA-based architecture. The MQTT + OpenADR stack covers mFRR, congestion management, nFAS (P-based), intraday, day-ahead, and emerging flex markets.

## D14: Protocol Fitness Across Markets

**Decision**: The dual-protocol stack (MQTT upstream + OpenADR downstream) is validated as a **general-purpose flexibility activation stack**, not just a congestion management tool.

**Market coverage analysis**:

| Market | Protocol Fitness | Key Reason |
|---|---|---|
| mFRR | Excellent | Activation cycle maps 1:1 to FlexRequest/Response/Status/Release |
| Congestion management | Excellent | Segment-addressed MQTT topics are purpose-built for topological grid relief |
| nFAS (P-based) | Excellent | Same message flow as congestion management |
| Intraday | Excellent | Same activation, scheduled rather than reactive |
| Day-ahead | Good | OpenADR alone would suffice, but MQTT doesn't hurt |
| Local flex markets | Excellent (activation) | Needs USEF/REST for market-facing bidding on top |
| Dynamic tariffs | Good | OpenADR's ELECTRICITY_PRICE signal is native; MQTT coordinates pool |

**Gaps requiring additional protocols**:
- **Market-facing interfaces** (bidding, settlement): USEF or platform-specific REST APIs
- **Q-based voltage support**: SunSpec Modbus / IEC 61850 (direct inverter control)
- **Tier 1 balancing** (FCR, aFRR): IEC 61850 / IEC 60870-5-104 via SCADA

See `../protocol-analysis-mqtt-vs-openadr.md` for the full protocol fitness analysis.

## D15: OpenADR 3.1 Compatibility (Alongside 2.0b)

**Decision**: The profile supports **both OpenADR 2.0b and 3.1** on the device interface. The HEMS Backend abstracts the version difference — the aggregator-facing MQTT interface is identical regardless of which OpenADR version the devices speak.

**Alternatives considered**:
- Mandate OpenADR 2.0b only (proven, widely deployed)
- Mandate OpenADR 3.1 only (modern, but limited deployments)
- Separate profiles per OpenADR version

**Rationale**:
- **3.1 is REST/JSON** — aligns with modern web architecture, easier to implement in new devices, machine-readable OpenAPI spec enables code generation
- **3.1 adds MQTT notifications** — VTN can push event notifications via MQTT, sharing the broker infrastructure with the aggregator↔backend layer
- **3.1 uses OAuth 2.0** — standard web authentication, no PKI certificate hierarchy required
- **2.0b is still widely deployed** — existing HEMS devices and VTNs should not be excluded
- **The HEMS Backend is the abstraction boundary** — it translates between MQTT and whichever OpenADR version its devices support. The aggregator never needs to know.

**Key 3.1 differences affecting the profile**:
- No explicit optIn/optOut — VTN infers compliance from OPERATING_STATE in reports. The Backend must derive DispatchAck.status from observed behavior.
- Programs organize events and reports — the Backend maps profile phases to programs (e.g., flex-readiness → Observe, grid-capacity → Dispatch).
- Report types are richer — STORAGE_CHARGE_LEVEL, STORAGE_DISPATCH_FORECAST, USAGE_FORECAST enable more precise SiteFlexOffer computation.
- STORAGE_CHARGE_LEVEL uses 0–1 fraction despite being declared as PERCENT — implementations must normalize.

**Consequence**: The profile's information model (04) includes mappings for both versions. HEMS Backend implementations may support one or both. The aggregator-facing interface remains unchanged.

**Validated against**: Reference implementation (home-wetzlas-ven, OpenADR 3.1.0) with VTN at 127.0.0.1:8088, programs AT-flex-readiness / AT-grid-capacity / AT-awattar-spot, per-resource and aggregate reporting every 5 min, hourly 24h forecasts.

## D8: Grid Segment as Addressing Unit

**Decision**: Flex-requests target a **grid segment** (`segment_id`), not individual devices or backends.

**Alternatives considered**:
- Target individual devices by ID
- Target backends by ID
- Geographic addressing (postal code, GPS area)

**Rationale**:
- Grid congestion is a **topological** problem — it occurs in specific grid segments, not geographic areas
- DSO already defines grid segments for their operations
- Each HEMS Backend knows which of its devices are in which segment (from grid connection registration)
- The aggregator maps DSO segment IDs to MQTT topics — clean and scalable

**Consequence**: Segment assignment must happen during device commissioning. HEMS Backend must maintain a segment registry for its managed devices.

## Summary Table

| # | Decision | Choice | Key Driver |
|---|---|---|---|
| D1 | Architecture | Aggregator-centric | Austrian market architecture (Smart Grids AT) |
| D2 | Protocols | MQTT (backend) + OpenADR 2.0b/3.1 (device) | AT standard for devices + scalability for backends |
| D3 | Control philosophy | Soft signal with local autonomy | Prosumer sovereignty + OpenADR optIn/optOut |
| D4 | Aggregation level | Backend-level on MQTT | Privacy + scalability + manufacturer autonomy |
| D5 | OpenADR delivery | 2.0b Profile B push / 3.1 subscriptions | Low-latency event delivery |
| D6 | Payload formats | JSON (MQTT) + XML (OpenADR) | Best fit per layer |
| D7 | Failure mode | Fail-safe to prosumer control | Safety + regulatory compliance |
| D8 | Addressing | Grid segment ID | Topological grid problem, DSO-defined |
| D9 | HEMS scope | Segment-agnostic (residential to commercial) | Challenge scope + interface-level design |
| D10 | Interaction model | Four-phase loop (Observe → Plan → Dispatch → Settle) | Continuous observation enables proactive market positioning |
| D11 | Observation messages | SiteStateSnapshot + SiteFlexOffer (bottom-up) | Aggregator needs always-current portfolio picture |
| D12 | Optimization | Two-level hierarchical MILP | Privacy + scalability + manufacturer autonomy |
| D13 | Market scope | Tier 2 primary (mFRR, congestion), Tier 3 reachable | Tier 1 needs SCADA; HEMS backends serve Tier 2+ |
| D14 | Protocol-market fitness | One stack, many markets | Dispatch cycle is market-agnostic; only trigger differs |
| D15 | OpenADR version | Both 2.0b and 3.1 supported | Backend abstracts version; 3.1 adds REST/JSON + MQTT notifications |
