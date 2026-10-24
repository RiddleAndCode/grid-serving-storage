# 07 — Interface Comparison: Austria vs. Germany

## Overview

A key question when reading the Austrian system architecture is: who communicates with the HEMS, and for what purpose? This document compares the two fundamentally different interface models — the Austrian approach (via Technical Aggregator) and the German approach (via DSO/VNB through Smart Meter Gateway).

## Austria: DSO Has No Direct Interface to the HEMS

In the Austrian model, the DSO (Verteilnetzbetreiber / VNB) does **not** communicate directly with HEMS devices or HEMS backends. The architecture deliberately places the **Technical Aggregator** as the intermediary between grid operations and prosumer assets.

```
Austria:
  DSO ──(grid stress signal)──▶ Technical Aggregator ──(flex-request)──▶ HEMS Backend ──(device control)──▶ HEMS Device

Germany:
  DSO/VNB ──(§14a control signal)──▶ Smart Meter Gateway ──(CLS channel)──▶ Steuerbox / HEMS ──▶ Device
```

The DSO's role in the Austrian model is limited to:
- Monitoring grid state (voltage, current, transformer loading)
- Signaling congestion events to the Technical Aggregator
- Validating that flex delivery relieved the grid situation
- Settlement with the aggregator for services rendered

The DSO ↔ Aggregator interface uses existing market processes and is **outside the scope** of the Grid-Serving Storage interoperability profile.

## The Two Interfaces This Profile Designs

The Austrian model defines two distinct digital interfaces (digitale Schnittstellen) between the aggregation layer and the HEMS:

### Interface 1: Technical Aggregator ↔ HEMS Backend (MQTT v5)

**Purpose**: Fleet-level coordination across heterogeneous HEMS manufacturers.

| Aspect | Detail |
|---|---|
| **Protocol** | MQTT v5 |
| **Payload format** | JSON over TLS 1.3 |
| **Communication model** | Pub/sub (asynchronous, bidirectional) |
| **Actors** | Technical Aggregator ↔ HEMS Backends (one per manufacturer) |
| **Granularity** | Aggregated — per backend, per grid segment |

**What flows over this interface**:
- **FlexRequest** (Aggregator → Backends): "I need X kW of charge/discharge in grid segment Y for Z minutes"
- **FlexResponse** (Backend → Aggregator): "42 of my 47 devices accepted, total 156.5 kW available"
- **FlexStatus** (Backend → Aggregator): periodic aggregated delivery updates
- **FlexRelease** (Aggregator → Backends): "Grid situation resolved, return to normal"

**Why MQTT (not OpenADR or REST)**:
- Multiple HEMS backends from different manufacturers must connect — pub/sub avoids point-to-point API integration per vendor
- Asynchronous — backends respond when their device fleets have been polled, not within a synchronous HTTP timeout
- Scales to many backends, each managing hundreds or thousands of devices
- Lightweight JSON payloads, low overhead
- MQTT v5 adds message expiry (stale flex-requests auto-expire), reason codes, and user properties

### Interface 2: HEMS Backend ↔ HEMS Device (OpenADR 2.0b)

**Purpose**: Individual device control and telemetry collection.

| Aspect | Detail |
|---|---|
| **Protocol** | OpenADR 2.0b (Profile B, PUSH mode) |
| **Payload format** | XML over HTTPS (TLS 1.2+) |
| **Communication model** | VTN → VEN (push events, collect reports) |
| **Actors** | HEMS Backend (as VTN) ↔ HEMS Device (as VEN) |
| **Granularity** | Individual device — per HEMS |

**What flows over this interface**:
- **oadrDistributeEvent** (VTN → VEN): charge/discharge setpoint for this specific device
- **oadrCreatedEvent** (VEN → VTN): device opts in or out, based on local constraint evaluation
- **oadrReport** (VEN → VTN): actual power delivery, SoC, device status
- **Event cancellation** (VTN → VEN): release signal forwarded from aggregator

**Why OpenADR (not MQTT or proprietary)**:
- Austrian standard — Smart Grids Austria identifies OpenADR as the favored protocol for controlling flexible assets
- Designed for demand response — the event model (distribute → create → report) maps directly to the flex-request lifecycle
- Vendor-neutral — any HEMS manufacturer can implement a VEN; any backend can implement a VTN
- Security built-in — HTTPS transport with PKI-based authentication
- Proven — deployed globally with active certification program (OpenADR Alliance)

## Side-by-Side: The Two Interfaces

| Dimension | Aggregator ↔ HEMS Backend (MQTT) | HEMS Backend ↔ HEMS Device (OpenADR) |
|---|---|---|
| **Purpose** | Fleet coordination | Device control |
| **Scope** | Aggregated (many devices) | Individual (one device) |
| **Protocol** | MQTT v5 | OpenADR 2.0b |
| **Payload** | JSON | XML |
| **Transport** | TLS 1.3 | HTTPS (TLS 1.2+) |
| **Auth** | Client certificates + ACLs | OpenADR PKI certificates |
| **Direction** | Bidirectional pub/sub | VTN pushes to VEN |
| **Message types** | FlexRequest, FlexResponse, FlexStatus, FlexRelease | oadrDistributeEvent, oadrCreatedEvent, oadrReport |
| **Latency tolerance** | Seconds (coordination) | Sub-second to seconds (control) |
| **Who implements** | Aggregator platform + each HEMS backend | Each HEMS backend (VTN) + each HEMS device (VEN) |

The **HEMS Backend** is the protocol bridge between these two interfaces. It translates MQTT flex-requests into OpenADR events, collects individual device responses, aggregates them, and publishes the aggregated result back via MQTT.

## Austria vs. Germany: Architectural Comparison

| Aspect | Austria | Germany |
|---|---|---|
| **Communication path to prosumer** | OpenADR from Aggregator → HEMS Backend → HEMS | CLS channel via Smart Meter Gateway (SMGW) |
| **Gateway role** | HEMS is the intelligent gateway | Smart Meter Gateway is the mandatory, BSI-certified gateway |
| **DSO involvement with devices** | Indirect only — DSO talks to Aggregator, never to HEMS | More direct — DSO can reach devices via SMGW infrastructure (§14a EnWG) |
| **Regulatory driver** | E-Control / ElWOG flexibility provisions | BSI (Bundesamt für Sicherheit) / EnWG §14a |
| **Protocol preference** | OpenADR 2.0b | HAN/CLS interface via SMGW |
| **Metering** | Smart Meter (simpler architecture) | Smart Meter Gateway ecosystem (complex, certified) |
| **Flexibility architecture** | More open to alternative protocols | Strongly tied to SMGW infrastructure |
| **Trust boundary** | HEMS device (enforces prosumer sovereignty) | SMGW (enforces regulatory compliance) |

### Key Implication

In Germany, the DSO/VNB has a **direct digital interface** to the prosumer's site via the Smart Meter Gateway — the SMGW acts as a regulated, certified communication gateway under BSI oversight. The DSO can send control signals (e.g., §14a dimming) directly through this path.

In Austria, there is **no equivalent direct DSO-to-device interface**. The HEMS is the intelligent gateway, and the Technical Aggregator is the market intermediary. The DSO influences device behavior only indirectly, by signaling grid stress to the aggregator, who then coordinates with HEMS backends. This design choice preserves prosumer sovereignty — the HEMS device is the trust boundary that decides locally whether to accept or reject a flex-request, regardless of who originated it.
