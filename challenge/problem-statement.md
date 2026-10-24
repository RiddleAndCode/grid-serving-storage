# Grid-Friendly / Grid-Serving Storage — Challenge

## Background

Falling storage prices mean that more and more electrical energy storage systems are being installed in distribution grids. They range from relatively small storage units in households to large storage systems at commercial sites. These systems are often installed together with, or as a complement to, a PV system, and they serve primarily to increase the share of self-generated electricity that is consumed on site.

At the same time, grid overloads are looming in many distribution grid sections, caused by the build-out of renewable generation and by additional loads resulting from electrification, such as heat pumps or charging stations for electric cars. The storage capacity installed across the distribution grid could be used to counteract grid bottlenecks. This would allow further expansion of renewable generation while reducing the need for grid expansion.

## Problem Statement

A distribution system operator (DSO) wants to use the storage capacity of customer installations as a simple and quick measure against grid overloads. By charging and discharging storage systems in a targeted way, critical grid situations are to be eased, so that curtailment of generation plants or consumers is avoided as far as possible. In principle, storage operation is determined by the plant operator, while the grid operator can, in exceptional situations and for a limited time, influence the operation of a large number of storage systems in a grid segment.

## Task

Together with other experts, use the IES (Integrating the Energy System) methodology to design processes and interfaces as part of an interoperability profile for the application "Grid-Serving Storage". The goal is a rough interoperability profile for easily integrating devices and systems that is concrete and reusable, but is not a complete profile definition (it contains no technical details).

## Key Constraints

- The profile must be **reusable** across different DSOs, device manufacturers, and aggregators
- It is a **rough profile** — concrete enough to guide implementation, but not a full technical specification
- The DSO intervention is **exceptional and time-limited** — normal operation remains with the prosumer
- The solution must scale to a **large number of storage systems** in a grid segment
- **Curtailment avoidance** is the primary goal — storage flexibility is preferred over hard curtailment
