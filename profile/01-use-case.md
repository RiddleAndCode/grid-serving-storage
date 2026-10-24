# 01 — Use Case: Grid-Serving Storage

## Business Context

Distribution grids face increasing stress from renewable generation build-out (PV, wind) and electrification loads (heat pumps, battery storage). Grid expansion is slow and expensive. Meanwhile, distributed battery storage is being deployed at scale — primarily for prosumer self-consumption optimization.

This use case leverages existing distributed storage as a **grid relief resource**. The **Technical Aggregator** pools distributed flexibility from HEMS installations and offers it to the DSO and wholesale markets. The DSO signals grid stress to the aggregator, who coordinates the response across HEMS backends and their managed devices.

## Architecture Context (Austrian Model)

Per the Smart Grids Austria system architecture for flexible assets (see `../challenge/poster-systemarchitektur-v2g.md`):

- **Austria favors OpenADR** as the standard for controlling flexible assets (both 2.0b and 3.1 are supported)
- **The HEMS is the intelligent gateway** at the prosumer site (unlike Germany's Smart Meter Gateway model)
- **The Technical Aggregator** is the market role that pools flexibility — devices do not interact directly with the DSO or market
- **The critical interface** is between HEMS Backends and the Technical Aggregator

```
                    ┌──── Observe (continuous) ────┐
                    │                               │
HEMS Device ──state──▶ HEMS Backend ──aggregated──▶ Technical Aggregator
                                      state+flex      │
                    ┌──── Dispatch (on demand) ────┘
                    │
Technical Aggregator ──goals──▶ HEMS Backend ──device goals──▶ HEMS Device
     (MILP)                       (MILP)
                    │
                    └──── Settle (post-event) ─────▶ DeliveryReport
```

## Interaction Model: Observe → Plan → Dispatch → Settle

The system operates as a **continuous four-phase loop**, not just event-driven activation:

### Phase 1 — Observe (Continuous, Bottom-Up)

HEMS devices report their state to their HEMS Backend. Each HEMS Backend aggregates across its managed devices and publishes to the Technical Aggregator:

- **Current state**: consumption, production, SoC, grid import/export
- **Flexibility potentials**: how much the site can flex up or down (in kW), measured and learned from the ramp behavior of locally managed devices
- **Constraints**: ramp rates (up/down), activation lead time, min/max duration, rebound characteristics
- **Forecast**: 24h flexibility forecast per time slot with confidence levels

This gives the aggregator a continuously updated picture of what each HEMS Backend (and by extension, each cluster of devices) can deliver.

### Phase 2 — Plan (Aggregator-Internal)

The Technical Aggregator uses the observed state and flex offers from all HEMS Backends to plan its market interactions:

- **Portfolio assessment**: What is my total available flexibility (up and down)?
- **Market positioning**: Which markets can I serve with this portfolio? (mFRR, intraday, congestion, flex markets)
- **Optimization**: The aggregator runs a **MILP (Mixed-Integer Linear Program)** to determine optimal dispatch across backends — respecting per-backend constraints, ramp rates, rebound effects, reliability scores, and market obligations
- **Dispatch plan**: The MILP output is a set of goals (up/down deltas per time slot) for each HEMS Backend

### Phase 3 — Dispatch (On Demand, Top-Down)

When market obligations or grid signals require activation:

1. The **Aggregator** sends dispatch goals to each relevant HEMS Backend — direction (up/down), target delta in kW, and a time-series schedule of setpoints
2. Each **HEMS Backend** receives its goal and runs its own **MILP** to distribute the requested delta across its managed HEMS devices — respecting per-device SoC, ramp limits, hardware constraints, and prosumer preferences
3. Each **HEMS Device** receives its individual goal, evaluates locally, and accepts (fully or partially) or rejects
4. The **HEMS Backend** aggregates device responses and acknowledges the dispatch to the aggregator

### Phase 4 — Settle (Post-Event)

After dispatch completes:

1. Each **HEMS Backend** generates a delivery report: what was requested vs. what was actually delivered (per time slot)
2. The **Aggregator** verifies delivery against metering data and updates reliability scores
3. Settlement with DSO/market counterparties based on verified delivery

## Use Case Narrative

### Normal Operation (Observe Phase Active)

A prosumer operates their battery storage system according to their own preferences — typically maximizing self-consumption of PV generation. The HEMS controls charge/discharge cycles locally.

**Even during normal operation**, the HEMS reports its state to the HEMS Backend, which continuously publishes aggregated state snapshots and flexibility offers to the Technical Aggregator. The aggregator observes but does not intervene — it uses the data to assess portfolio capacity and plan market positions.

### Grid Stress Event (Full Cycle)

1. The **DSO** detects an emerging overload and signals the Technical Aggregator.
2. The **Aggregator** — already aware of current flexibility from continuous observation — runs its MILP to determine optimal dispatch across HEMS Backends for the affected grid segment.
3. The **Aggregator** sends dispatch goals (up/down) to relevant HEMS Backends.
4. Each **HEMS Backend** runs its own MILP to distribute the goal across managed HEMS devices, respecting per-device constraints.
5. **HEMS devices** execute within accepted bounds, reporting actual delivery back up the chain.
6. On resolution, the aggregator releases the dispatch. Delivery reports are generated for settlement.

### Market Participation (Full Cycle)

1. The **Aggregator** continuously observes portfolio flex capacity and positions in wholesale/balancing markets.
2. When a market commitment triggers (mFRR activation, intraday position, flex market clearing), the aggregator dispatches accordingly — same Phase 3/4 as above.

### Post-Event

The aggregator settles with market counterparties and updates backend reliability scores. These scores feed back into future MILP planning (unreliable backends receive less dispatch).

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
