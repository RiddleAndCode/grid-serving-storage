# Vehicle-to-Grid (V2G): Systemarchitektur und Interoperabilität im Ländervergleich

**Source**: OVE-Energietechnik-Tagung, 63. Fachtagung der Energietechnik-Branche, 13.–14.11.2025, Wien

**Authors**:
- Daniel Stahleder¹, Harald Wechselberger², Christoph Wanzenböck³, Kurt Leonhartsberger¹
- ¹ AIT Austrian Institute of Technology GmbH
- ² VERBUND Energy4Business GmbH
- ³ Technologieplattform Smart Grids Austria
- ⁴ Impreect GmbH

**Project**: "V2G Network" (FFG-Number: 921195), funded under "CON KMU-Innovations-netzwerke 2022" by BMWFT (Bundesministerium für Wirtschaft, Energie und Tourismus) via BMVIT/FFG.

## Zentrale Fragestellung des Beitrags

Welche Anforderungen ergeben sich an die interoperable Systemarchitektur für die netz- und systemdienliche Nutzung von Elektrofahrzeugen (Vehicle-to-Grid, V2G) in Österreich, und welche Ausprägungen haben Unterschiede in den in Deutschland etablierten Architekturen auf die Marktteilnehmung, Stakeholderschaft und Teilnahme internationaler Akteure?

Während in Österreich **OpenADR als zukünftiger Standard** für die Steuerung flexibler Anlagen und V2G-Anwendungen favorisiert wird, kommen in Deutschland Lösungen auf Basis des **Smart-Meter-Gateway-Ökosystems** und der dort etablierten Kommunikationsstandards zum Einsatz. Diese Unterschiede führen zu abweichenden Anforderungen an Hard- und Softwarelösungen und erhöhen den Integrationsaufwand für international tätige Unternehmen.

## Methodischer Ansatz

Im Projekt V2G Network wurde auf Basis der im deutschen Forschungsvorhaben "HandVoll" erarbeiteten Systemarchitektur eine österreichische Systemarchitektur entwickelt und mit der deutschen verglichen. Dazu wurden relevante Stakeholder wie Netzbetreiber, Aggregatoren, Energieversorger und Technologieanbieter identifiziert und deren Kommunikationsbeziehungen analysiert. Die entstandene Architektur wurde anschließend im Rahmen externer Expertise und Stakeholder-Workshops diskutiert, validiert und mit der deutschen Systemarchitektur verglichen. Im Fokus standen insbesondere Datenflüsse, Marktrollen, Schnittstellen, Kommunikationsprotokolle sowie regulatorische Rahmenbedingungen.

## System Architecture Diagram (Austrian Model)

The poster's central diagram shows the Austrian V2G system architecture with the following actors and interfaces:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         MARKET / WHOLESALE                              │
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │   BKO        │    │  Marktplatz  │    │  Regelenergie│              │
│  │(Bilanzkreis- │    │  (Market     │    │  (Balancing  │              │
│  │ koordinator) │    │   Platform)  │    │   Energy)    │              │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘              │
│         │                   │                    │                       │
└─────────┼───────────────────┼────────────────────┼───────────────────────┘
          │                   │                    │
          ▼                   ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      AGGREGATION / FLEXIBILITY                          │
│                                                                         │
│  ┌──────────────┐    ┌──────────────────────┐    ┌──────────────┐      │
│  │  Lieferant   │    │  Technischer         │    │  Netzbetrei- │      │
│  │  (Supplier)  │    │  Aggregator          │    │  ber (DSO)   │      │
│  │              │    │  (Tech. Aggregator)  │    │              │      │
│  └──────────────┘    └──────────┬───────────┘    └──────┬───────┘      │
│                                 │                       │               │
│                          ┌──────┴───────┐               │               │
│                          │  OpenADR /   │               │               │
│                          │  MQTT / ...  │               │               │
│                          │  (Interface  │               │               │
│                          │   to define) │               │               │
│                          └──────┬───────┘               │               │
└─────────────────────────────────┼───────────────────────┼───────────────┘
                                  │                       │
                                  ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      CUSTOMER / PROSUMER SITE                           │
│                                                                         │
│  ┌──────────────────────────────────────────────┐                      │
│  │              HEMS / HEMS Backend             │                      │
│  │     (Home Energy Management System)          │                      │
│  │                                              │                      │
│  │   ┌─────────┐  ┌──────────┐  ┌───────────┐  │                      │
│  │   │   PV    │  │ Battery  │  │ Wallbox / │  │    ┌──────────────┐  │
│  │   │ Inverter│  │ Storage  │  │ EVSE      │  │    │  Smart Meter │  │
│  │   └─────────┘  └──────────┘  └─────┬─────┘  │    │  (Zähler)    │  │
│  │                                    │         │    └──────┬───────┘  │
│  └────────────────────────────────────┼─────────┘           │          │
│                                       │                     │          │
│                                  ┌────▼─────┐               │          │
│                                  │   EV     │               │          │
│                                  │(Elektro- │          to DSO│          │
│                                  │fahrzeug) │          metering         │
│                                  └──────────┘               │          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Interfaces Identified on the Poster

| Interface | Between | Protocol (AT) | Protocol (DE) |
|---|---|---|---|
| Aggregator ↔ HEMS/HEMS Backend | Tech. Aggregator ↔ Customer Site | **OpenADR** (favored in AT) | CLS-Management via Smart Meter Gateway |
| HEMS ↔ Wallbox/EVSE | Local site | OCPP / Modbus / SunSpec | OCPP / Modbus / SunSpec |
| HEMS ↔ Battery Storage | Local site | Modbus / SunSpec / vendor API | Modbus / SunSpec / vendor API |
| HEMS ↔ PV Inverter | Local site | Modbus / SunSpec | Modbus / SunSpec |
| DSO ↔ Smart Meter | Metering | IEC 62056 (DLMS/COSEM) | via Smart Meter Gateway (BSI) |
| Aggregator ↔ DSO | Flexibility coordination | To be defined | To be defined |
| Aggregator ↔ Market | Wholesale / balancing | Market protocols | Market protocols |

### Austria vs. Germany — Key Differences

| Aspect | Austria (AT) | Germany (DE) |
|---|---|---|
| **Communication path to prosumer** | OpenADR from aggregator to HEMS | Smart Meter Gateway (SMGW) with CLS channel |
| **Gateway role** | HEMS is the intelligent gateway | Smart Meter Gateway is the mandatory gateway |
| **Regulatory driver** | E-Control / ElWOG flexibility provisions | BSI (Bundesamt für Sicherheit) / EnWG § 14a |
| **Protocol preference** | OpenADR 2.0b | HAN/CLS interface via SMGW |
| **Metering** | Smart Meter (simpler architecture) | Smart Meter Gateway ecosystem (complex, certified) |
| **Flexibility** | More open to alternative protocols | Strongly tied to SMGW infrastructure |

## Ergebnisse

Die Analyse zeigt, dass zwischen Österreich und Deutschland trotz vergleichbarer Zielbilder wesentliche Unterschiede bei der technischen und organisatorischen Umsetzung von V2G bestehen. Diese betreffen insbesondere die Rollenverteilung der Marktakteure, die eingesetzte Messtechnik, die Wahl zentraler Kommunikationsstandards sowie die regulatorischen Rahmenbedingungen.

Während in Österreich OpenADR als zukünftiger Standard für die Steuerung flexibler Anlagen und V2G-Anwendungen favorisiert wird, kommen in Deutschland Lösungen auf Basis des Smart-Meter-Gateway-Ökosystems und der dort etablierten Kommunikationsstandards zum Einsatz.

## Schlussfolgerungen

Die Gegenüberstellung des österreichischen und regulatorisch unterschiedlichen nationalen V2G-Architekturen zeigt erhebliche Auswirkungen auf die Bauweise und die technischen Anforderungen an Hard- und Softwarelösungen. Insbesondere für internationale Akteure stellt die Entwicklung interoperabler Lösungen einen zusätzlichen Aufwand dar, der bei kleineren Märkten wie Österreich die wirtschaftliche Attraktivität reduzieren kann. Eine stärkere Harmonisierung von Kommunikationsstandards, Schnittstellen und Marktprozessen auf europäischer Ebene könnte die Interoperabilität erhöhen, Markteintrittsbarrieren reduzieren und die Einführung von Vehicle-to-Grid-Anwendungen beschleunigen. Langfristig wird die Standardisierung zentraler Bausteine der V2G-Systemarchitektur eine wesentliche Voraussetzung für eine erfolgreiche Integration von Elektrofahrzeugen als Flexibilitätsressource im europäischen Energiesystem darstellen.

## Key Takeaways for Grid-Serving Storage Profile

1. **Austria favors OpenADR** as the standard for controlling flexible assets (including storage) — this is the protocol the HEMS should speak
2. **The critical interface is Aggregator ↔ HEMS** — this is where interoperability must be designed
3. **The HEMS is the intelligent gateway** in the Austrian model (unlike Germany where the Smart Meter Gateway plays this role)
4. **The Technical Aggregator** is the market role that pools flexibility and interacts with DSO/market — not the DSO directly with devices
5. **Local device protocols** (Modbus, SunSpec, OCPP) are below the HEMS — the interoperability profile focuses on what's above it
