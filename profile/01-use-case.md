# 01 — Use Case: Grid-Serving Storage

## Business Context

Distribution grids face increasing stress from renewable generation build-out (PV, wind) and electrification loads (heat pumps, battery storage). Grid expansion is slow and expensive. Meanwhile, distributed battery storage is being deployed at scale — primarily for prosumer self-consumption optimization.

This use case leverages existing distributed storage as a **grid relief resource**. The **Technical Aggregator** pools distributed flexibility from HEMS installations and offers it to the DSO and wholesale markets. The DSO signals grid stress to the aggregator, who coordinates the response across HEMS backends and their managed devices.

## Architecture Context (Austrian Model)

Per the Smart Grids Austria system architecture for flexible assets (see `../challenge/poster-systemarchitektur-v2g.md`):

- **Austria favors OpenADR** as the standard for controlling flexible assets
- **The HEMS is the intelligent gateway** at the prosumer site (unlike Germany's Smart Meter Gateway model)
- **The Technical Aggregator** is the market role that pools flexibility — devices do not interact directly with the DSO or market
- **The critical interface** is between HEMS Backends and the Technical Aggregator

```
DSO ──signals grid stress──▶ Technical Aggregator ──flex-request──▶ HEMS Backend ──OpenADR──▶ HEMS Device
                                                   ◀──flex-response──             ◀──report──
```

## Use Case Narrative

### Normal Operation

A prosumer operates their battery storage system according to their own preferences — typically maximizing self-consumption of PV generation. The HEMS (Home Energy Management System) controls charge/discharge cycles locally. Neither the aggregator nor the DSO are involved in normal operation.

### Grid Stress Event

1. The **DSO's grid monitoring system** detects an emerging overload in a distribution grid segment (e.g., voltage rise from excess PV feed-in, or transformer overload from simultaneous high consumption).

2. The **DSO signals the grid situation** to the Technical Aggregator (via their established interface — outside this profile's scope). The signal identifies the affected grid segment and the type of relief needed.

3. The **Technical Aggregator** determines which HEMS backends manage devices in the affected segment. It sends a **flex-request** to the relevant HEMS backends via MQTT, specifying direction (charge/discharge/hold), maximum power, and duration.

4. Each **HEMS Backend** forwards the flex-request to its managed HEMS devices via **OpenADR** (as VEN-VTN communication). The HEMS device evaluates the request against local constraints (state of charge, user preferences, safety limits).

5. The **HEMS device** adjusts storage operation within accepted bounds and reports actual delivery back to the HEMS Backend (via OpenADR reports), which aggregates and forwards to the Technical Aggregator (via MQTT).

6. When the grid situation normalizes, the aggregator publishes a **release signal**. HEMS devices return to normal prosumer-controlled operation.

### Post-Event

The aggregator logs the event and actual flex delivered for settlement with the DSO and compensation to prosumers/HEMS operators.

## Triggers

- DSO signals grid congestion to aggregator (voltage, transformer loading, forecast)
- TSO/APG activates mFRR (tertiary balancing reserve) — aggregator dispatches pool
- Aggregator's own market participation (intraday trading, day-ahead scheduling)
- Local flexibility market clearing — aggregator activates contracted flex
- Preventive activation based on aggregator's grid-aware forecasting

## Serviceable Markets

This use case and its dual-protocol architecture (MQTT + OpenADR) serve multiple energy markets and grid services. The architecture targets **Tier 2** (event-driven flex, 12.5–15 min response) as its primary operating range, with natural reach into **Tier 3** (scheduled/market-driven, hours ahead).

**Tier 1** (FCR, aFRR — sub-second to 5 min response) is explicitly out of scope: these use cases require deterministic, continuous control loops via dedicated SCADA/PLC hardware (e.g., Beckhoff TwinCAT) that bypass the HEMS backend stack entirely.

### Primary Markets (Tier 2)

| Market | Operator | Why it fits |
|---|---|---|
| **mFRR (Tertiary Balancing Reserve)** | APG (Austrian TSO) | 12.5 min FAT, quarter-hourly delivery. The activation-confirmation-delivery-release cycle maps 1:1 to FlexRequest → FlexResponse → FlexStatus → FlexRelease |
| **Local Congestion Management** | DSO (e.g., Netz NÖ, Wiener Netze) | Core use case. Segment-addressed MQTT topics are purpose-built for topological grid relief |
| **Non-Frequency Ancillary Services (P-based)** | DSO | Active power adjustment for voltage support and congestion prevention. Same message flow as congestion management |

### Secondary Markets (Tier 3 — reachable with the same stack)

| Market | Operator | Why it fits |
|---|---|---|
| **Intraday Continuous / 15-min Auctions** | EXAA / EPEX SPOT | Same activation flow, scheduled rather than reactive. Well within gate closure timing |
| **Day-ahead Market** | EXAA / EPEX SPOT | Schedule-based dispatch via the same MQTT/OpenADR stack |
| **Local Flexibility Markets** | DSO / platform (NODES, Equigy) | MQTT + OpenADR for activation; market-facing interface (USEF/REST) on top |
| **Dynamic Tariff Response** | Retailer / BRP | OpenADR's ELECTRICITY_PRICE signal type is native. MQTT coordinates pool response to prevent herd behavior |
| **Capacity Markets / Strategic Reserve** | TSO / regulator | If Austria introduces capacity mechanisms, aggregated storage is eligible |

See `../protocol-analysis-mqtt-vs-openadr.md` for the full protocol fitness analysis by market.

## Goals

- **Primary**: Avoid curtailment of renewable generation and consumer loads
- **Secondary**: Defer grid expansion investment
- **Tertiary**: Enable aggregator market participation with distributed storage (mFRR, intraday, flexibility markets)
- **Quaternary**: Build operational experience with distributed flexibility in Austrian market

## Constraints

- Aggregator intervention is **exceptional and time-limited** — not a daily optimization tool
- Prosumer retains **ultimate control** over safety limits and minimum SoC
- HEMS device is the **trust boundary** — it enforces local constraints regardless of what the aggregator requests
- Must work across **heterogeneous HEMS backends** (different manufacturers, device counts)
- Must support the **Austrian regulatory model** (OpenADR as preferred standard, no SMGW dependency)
