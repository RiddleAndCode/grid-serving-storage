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

**Decision**: Use **MQTT v5** between Aggregator and HEMS Backends, and **OpenADR 2.0b** between HEMS Backends and HEMS Devices.

**Alternatives considered**:
- MQTT end-to-end (aggregator to device)
- OpenADR end-to-end (aggregator to device)
- REST APIs between aggregator and backends

**Rationale**:
- **OpenADR on the device** is the Austrian standard for flexible asset control (per Smart Grids Austria architecture). The HEMS device must speak OpenADR regardless of what the backend uses upstream.
- **MQTT between aggregator and backends** is better suited for device coordination: pub/sub scales to many backends, async responses match device polling times, lightweight JSON vs. OpenADR XML overhead.
- The HEMS Backend is a natural **protocol bridge** — each manufacturer already operates a backend, adding MQTT is trivial.
- REST APIs would require the aggregator to integrate per-vendor APIs. MQTT standardizes the interface.

**Consequence**: HEMS Backend must implement both protocols. This is acceptable because backends are server-side infrastructure, not constrained embedded devices.

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

## D5: OpenADR 2.0b Profile B (Push Mode)

**Decision**: Use OpenADR 2.0b **Profile B** with **PUSH mode** (VTN pushes events to VEN).

**Alternatives considered**:
- Profile A (simpler, pull-only)
- Profile B with PULL mode (VEN polls VTN)

**Rationale**:
- **Push mode** delivers events immediately — critical for time-sensitive grid relief
- Pull mode introduces latency (VEN must poll at intervals)
- Profile B supports both push and pull, plus reporting — needed for status feedback
- Profile B is the standard profile for non-trivial deployments

**Consequence**: HEMS device must support HTTP server capability (to receive pushed events). Modern HEMS devices typically support this.

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
| D2 | Protocols | MQTT (backend) + OpenADR (device) | AT standard for devices + scalability for backends |
| D3 | Control philosophy | Soft signal with local autonomy | Prosumer sovereignty + OpenADR optIn/optOut |
| D4 | Aggregation level | Backend-level on MQTT | Privacy + scalability + manufacturer autonomy |
| D5 | OpenADR profile | Profile B, push mode | Low-latency event delivery |
| D6 | Payload formats | JSON (MQTT) + XML (OpenADR) | Best fit per layer |
| D7 | Failure mode | Fail-safe to prosumer control | Safety + regulatory compliance |
| D8 | Addressing | Grid segment ID | Topological grid problem, DSO-defined |
