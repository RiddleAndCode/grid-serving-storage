# Grid-Serving Storage — TEB Hackathon

Interoperability profile for the use case **"Grid-Serving Storage"**, designed using the IES (Integrating the Energy System) methodology.

Based on the system architecture for flexible assets from Smart Grids Austria / AIT (see `challenge/poster-systemarchitektur-v2g.md`).

## Challenge

A distribution system operator (DSO) wants to leverage distributed customer storage capacity (home batteries, commercial storage) as a fast-response measure against grid overloads — without permanently overriding prosumer autonomy. The **Technical Aggregator** pools distributed flexibility and mediates between the DSO/market and the HEMS installations.

## Focus: The Aggregator ↔ HEMS Interface

This profile specifically designs the **interface between HEMS Backends and the Technical Aggregator** — the critical interoperability boundary in the Austrian energy system architecture.

```
                    ┌──────────────┐
                    │     DSO      │
                    │ (Grid State) │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐     ┌─────────────┐
                    │  Technical   │────▶│   Market /   │
                    │  Aggregator  │     │  Balancing   │
                    └──────┬───────┘     └─────────────┘
                           │
              ═════════════╪══════════════════
              ║  THIS IS THE INTERFACE WE    ║
              ║  ARE DESIGNING               ║
              ═════════════╪══════════════════
                           │
            ┌──────────────┼──────────────┐
            │              │              │
     ┌──────▼──────┐ ┌────▼─────┐ ┌─────▼─────┐
     │HEMS Backend │ │HEMS Back.│ │HEMS Back. │
     │(Provider A) │ │(Prov. B) │ │(Prov. C)  │
     └──────┬──────┘ └────┬─────┘ └─────┬─────┘
            │              │              │
     ┌──────▼──────┐ ┌────▼─────┐ ┌─────▼─────┐
     │    HEMS     │ │   HEMS   │ │   HEMS    │
     │  (Device)   │ │ (Device) │ │ (Device)  │
     │  OpenADR    │ │ OpenADR  │ │ OpenADR   │
     └──────┬──────┘ └────┬─────┘ └─────┬─────┘
            │              │              │
     ┌──────▼──────┐ ┌────▼─────┐ ┌─────▼─────┐
     │  Battery /  │ │ Battery/ │ │ Battery / │
     │  Battery/PV │ │ Batt./PV │ │ Batt./PV  │
     └─────────────┘ └──────────┘ └───────────┘
```

## Repository Structure

```
grid-serving-storage/
├── README.md                                    ← you are here
├── challenge/
│   ├── problem-statement.md                     ← original hackathon task
│   ├── poster-systemarchitektur-v2g.pdf         ← Smart Grids Austria V2G poster
│   ├── poster-systemarchitektur-v2g.md          ← poster content (markdown)
│   ├── TEB-AI-Hackathon-Submission-Template.docx    ← submission form (original)
│   └── TEB-AI-Hackathon-Submission-Template.docx.md ← submission form (markdown)
├── profile/
│   ├── 01-use-case.md                           ← business context & narrative
│   ├── 02-actors-roles.md                       ← actor definitions (aggregator-centric)
│   ├── 03-process-flow.md                       ← sequence of interactions
│   ├── 04-information-model.md                  ← message types & data model
│   ├── 05-communication.md                      ← dual-protocol: OpenADR (HEMS) + MQTT (backend)
│   └── 06-design-decisions.md                   ← key decisions & rationale
├── open-questions.md                            ← unresolved items & next steps
└── TODO.md                                      ← submission task list
```

## Key Architecture Decisions

- **Two interfaces, two protocols**:
  - **HEMS Device ↔ HEMS Backend**: OpenADR 2.0b (Austrian standard for flexible asset control)
  - **HEMS Backend ↔ Technical Aggregator**: MQTT v5 (lightweight, scalable device coordination)
- **Control philosophy**: Soft signal — aggregator requests, HEMS decides locally
- **Austrian model**: HEMS is the intelligent gateway (no Smart Meter Gateway dependency)
- **Fail-safe**: Every failure defaults to normal prosumer operation

## IES Methodology Layers Covered

1. **Business Context** — use case narrative, actors, triggers, constraints
2. **Function Layer** — process steps from grid signal to device response
3. **Information Layer** — FlexRequest / FlexResponse / FlexRelease data model
4. **Communication Layer** — OpenADR + MQTT dual-protocol specification
