# 02 — Actors & Roles

## Architecture Overview

Based on the Austrian system architecture for flexible assets (Smart Grids Austria / AIT). The Technical Aggregator is the central coordination role. Two distinct interfaces connect the layers.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    MARKET & GRID LEVEL                               │
│                                                                     │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────┐             │
│  │   DSO    │    │  Balancing / │    │  BKO          │             │
│  │ (Netz-   │    │  Wholesale   │    │ (Bilanzkreis- │             │
│  │ betreiber)│    │  Market      │    │  koordinator) │             │
│  └────┬─────┘    └──────┬───────┘    └───────┬───────┘             │
│       │                 │                     │                     │
└───────┼─────────────────┼─────────────────────┼─────────────────────┘
        │                 │                     │
        ▼                 ▼                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   TECHNICAL AGGREGATOR                               │
│                                                                     │
│  Pools distributed flexibility. Interacts with DSO & market         │
│  upstream, with HEMS backends downstream.                           │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │            Aggregator Platform / Backend                     │   │
│  │   - Device management   - Market bidding                    │   │
│  │   - Grid segment mapping - Settlement & reporting           │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                              │                                      │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
                ═══════════════╪═══════════════
                ║    MQTT v5 INTERFACE        ║
                ║    (this profile designs)   ║
                ═══════════════╪═══════════════
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                   │
┌───────────▼────────┐ ┌──────▼────────┐ ┌───────▼────────┐
│   HEMS Backend A   │ │ HEMS Backend B│ │ HEMS Backend C │
│  (Manufacturer X)  │ │(Manufacturer Y│ │(Manufacturer Z)│
│                    │ │               │ │                │
│                    │ │               │ │                │
└─────────┬──────────┘ └──────┬────────┘ └───────┬────────┘
          │                   │                   │
   ═══════╪═══════     ═══════╪═══════     ═══════╪═══════
   ║ OpenADR 2.0b ║    ║ OpenADR 2.0b ║    ║ OpenADR 2.0b ║
   ║  or 3.1      ║    ║  or 3.1      ║    ║  or 3.1      ║
   ═══════╪═══════     ═══════╪═══════     ═══════╪═══════
          │                   │                   │
   ┌──────▼──────┐     ┌─────▼──────┐     ┌──────▼──────┐
   │  HEMS       │     │  HEMS      │     │  HEMS       │
   │  (Device)   │     │  (Device)  │     │  (Device)   │
   │  VEN        │     │  VEN       │     │  VEN        │
   └──────┬──────┘     └─────┬──────┘     └──────┬──────┘
          │                  │                    │
   ┌──────▼──────┐     ┌────▼───────┐     ┌─────▼──────┐
   │ Battery/PV  │     │ Battery/PV │     │ Battery/PV │
   │ Heat Pump   │     │ Heat Pump  │     │ Heat Pump  │
   └─────────────┘     └────────────┘     └────────────┘
```

## Actor Definitions

### DSO (Distribution System Operator / Netzbetreiber)

**Role**: Grid operator responsible for maintaining grid stability and power quality in the distribution network.

**In this architecture**:
- The DSO does **NOT** communicate directly with HEMS devices or backends
- The DSO signals grid stress situations to the **Technical Aggregator**
- The DSO ↔ Aggregator interface is outside this profile's scope (existing market processes)

**Responsibilities**:
- Monitor grid state (voltage, current, transformer loading)
- Signal congestion events to aggregators operating in affected segments
- Validate that flex delivery actually relieved the grid situation
- Settlement with aggregator for grid services rendered

### Technical Aggregator (Technischer Aggregator)

**Role**: The central market role that pools distributed flexibility from multiple HEMS device portfolios and offers it to the DSO and wholesale/balancing markets.

**This is the upstream actor in our interface.**

**Market scope**: The aggregator participates across multiple markets using the same MQTT + OpenADR activation stack:
- **Balancing**: mFRR (tertiary reserve) via APG — 12.5 min full activation time, quarter-hourly delivery
- **Grid services**: Local congestion management, P-based non-frequency ancillary services (nFAS) via DSO
- **Wholesale**: Intraday continuous and 15-min auctions (EPEX SPOT / EXAA), day-ahead scheduling
- **Flexibility**: Emerging local flexibility markets (NODES, Equigy), capacity markets

FCR and aFRR are **not** serviceable through this architecture — they require dedicated SCADA/PLC infrastructure with sub-second to 4-second control cycles.

**Responsibilities**:
- Receive grid stress signals from DSO
- Receive mFRR activation signals from TSO/APG
- Bid into wholesale and flexibility markets on behalf of the pool
- Determine which HEMS backends have devices in the affected grid segment
- Send flex-requests to relevant HEMS backends (via **MQTT**)
- Collect and aggregate flex-responses from HEMS backends
- Monitor actual flex delivery during events
- Report aggregated flex to DSO / market
- Handle settlement with HEMS operators and market counterparties

**Does NOT**:
- Communicate directly with individual HEMS devices (that's the backend's job)
- Override HEMS local constraints
- Know the internal architecture of each HEMS manufacturer's device portfolio
- Serve Tier 1 markets (FCR, aFRR) — these require a fundamentally different architecture

### HEMS Backend (HEMS Manufacturer's Cloud/Server)

**Role**: The manufacturer-operated backend that manages a portfolio of HEMS devices. Each HEMS manufacturer operates their own backend. This is the **downstream actor** in the MQTT interface.

**This is the downstream actor in our interface.**

**Responsibilities**:
- Receive flex-requests from aggregator (via **MQTT**)
- Determine which of its managed HEMS devices are in the affected segment and capable of responding
- Forward flex-requests to individual HEMS devices (via **OpenADR 2.0b or 3.1** — acting as VTN)
- Collect device responses and aggregate them
- Publish aggregated flex-response to aggregator (via **MQTT**)
- Stream status updates during flex execution
- Handle device management, firmware updates, device provisioning

**Key property**: The HEMS Backend is the **protocol bridge** — it translates between MQTT (aggregator-facing) and OpenADR (device-facing).

### HEMS Device (Home Energy Management System — On-Site)

**Role**: The intelligent controller at the prosumer's site. Manages local energy assets (battery, PV inverter, heat pump).

**Communicates via OpenADR** as a VEN (Virtual End Node). Both OpenADR 2.0b and 3.1 are supported — the choice depends on device capabilities.

**Responsibilities**:
- Receive flex-requests from HEMS Backend via **OpenADR 2.0b or 3.1** (as VEN)
- Evaluate requests against local constraints (SoC, user preferences, safety limits, hardware limits)
- Execute accepted flex by adjusting battery charge/discharge setpoints
- Report actual delivery back to HEMS Backend via **OpenADR reports**
- Return to normal operation on release or timeout

**Key property**: The HEMS device is the **trust boundary** — it is the only actor that knows real-time battery state and prosumer preferences. It enforces local constraints regardless of what the aggregator or backend requests.

**Local device interfaces** (below the HEMS, outside this profile's scope):
- Battery inverter: Modbus / SunSpec
- PV inverter: Modbus / SunSpec
- Heat pump: SG Ready / Modbus
- Smart Meter: DLMS/COSEM (IEC 62056)

### Prosumer (Storage Owner / Anlagenbetreiber)

**Role**: Owner and operator of the installation. Retains sovereignty.

**Responsibilities**:
- Contract with HEMS manufacturer (device + backend service)
- Consent to participation in grid-serving flex (contractual basis with aggregator or HEMS operator)
- Configure local preferences (minimum SoC, opt-out windows) via HEMS interface

**Rights**:
- Normal operation fully under prosumer control
- Can set constraints that flex-requests cannot breach
- Can opt out (with potential contractual implications)

## Interface Summary

| Interface | Actors | Protocol | Scope |
|---|---|---|---|
| DSO ↔ Aggregator | DSO → Tech. Aggregator | Existing market processes | Outside this profile |
| **Aggregator ↔ HEMS Backend** | **Tech. Aggregator ↔ HEMS Backend** | **MQTT v5** | **This profile designs this** |
| **HEMS Backend ↔ HEMS Device** | **HEMS Backend (VTN) ↔ HEMS (VEN)** | **OpenADR 2.0b / 3.1** | **This profile specifies requirements** |
| HEMS ↔ Local devices | HEMS → Battery/PV/Heat Pump | Modbus / SunSpec / SG Ready | Outside this profile |
| DSO ↔ Smart Meter | DSO → Meter | DLMS/COSEM | Outside this profile |
