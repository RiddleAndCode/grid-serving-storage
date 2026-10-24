# Open Questions & Next Steps

## Unresolved Questions

### Architecture

- **HEMS Backend ownership**: Is the HEMS Backend always the device manufacturer's cloud? Or could a third-party platform (e.g., KERN) operate as a multi-vendor HEMS Backend?
- **Multiple aggregators**: Can a HEMS Backend connect to multiple aggregators simultaneously? If so, how to prevent double-commitment of the same device capacity?
- **Aggregator ↔ DSO interface**: This profile deliberately scopes out the DSO-to-aggregator interface. Is there an existing standard or does it need a separate IES profile?

### OpenADR Specifics

- **OpenADR certification**: Must HEMS devices be OpenADR-certified, or is protocol compliance sufficient?
- **Signal type selection**: Is `LOAD_DISPATCH` the right signal type, or should `LOAD_CONTROL` or a custom signal be used for storage-specific scenarios?
- **Report intervals**: What reporting frequency should VENs support? Every 10s (near-real-time) or every 60s (lower overhead)?
- **OpenADR version**: Is 2.0b the target, or should we plan for OpenADR 3.0 (under development)?

### Regulatory & Commercial

- **Compensation model**: How are prosumers/HEMS operators compensated for flex delivery? Per-event payment, reduced grid fees, or flat annual fee?
- **Contractual basis**: What is the legal framework in Austria? ElWOG flexibility provisions? E-Control guidelines? Separate aggregator agreement?
- **Opt-out rights**: Can a prosumer opt out of individual events without penalty? What are the consequences for repeated opt-out?
- **Priority conflicts**: If a HEMS device is already committed to another aggregator or market obligation, what takes precedence?

### Technical

- **Segment definition**: How large is a "grid segment"? One transformer district? One feeder? How does the DSO communicate segment topology to the aggregator?
- **Device registration flow**: End-to-end provisioning — from grid connection application to OpenADR VEN registration to MQTT backend onboarding to aggregator segment mapping.
- **Metering & verification**: How is actual flex delivery measured and verified? Smart meter data (15-min) or OpenADR telemetry (sub-minute)?
- **HEMS Backend SLA**: What availability and response time requirements should the profile mandate for HEMS Backends?

## Next Steps (Post-Hackathon)

1. **Validate with Christoph Wanzenböck / Smart Grids Austria** — confirm alignment with V2G Network project findings and IES methodology expectations
2. **Prototype the MQTT interface** — implement a minimal aggregator + HEMS backend mock to demonstrate the flex-request/response flow
3. **OpenADR VEN prototype on KERN device** — implement OpenADR 2.0b VEN capability on the KERN HEMS device
4. **Formalize as IES profile** — map the rough profile into the official IES interoperability profile template
5. **Regulatory review** — clarify Austrian legal basis (ElWOG, E-Control flexibility guidelines)
6. **Align with KERN product roadmap** — integrate OpenADR VEN into KERN HEMS firmware; MQTT aggregator interface into KERN backend
7. **Engage TEB / IES community** — submit profile draft for peer review
