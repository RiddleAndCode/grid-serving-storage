"""Data models for the grid-serving storage demo.

Matches the aggregator-interface-spec.md message definitions,
simplified for demo purposes.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _uuid() -> str:
    return str(uuid.uuid4())[:8]


# ---------------------------------------------------------------------------
# Phase 1: Observe (bottom-up)
# ---------------------------------------------------------------------------

@dataclass
class Power:
    import_kw: float = 0.0
    export_kw: float = 0.0
    net_kw: float = 0.0
    production_kw: float = 0.0
    consumption_kw: float = 0.0


@dataclass
class SiteStateSnapshot:
    site_id: str
    timestamp: str = field(default_factory=_now)
    grid_capacity_kw: float = 25.0
    power: Power = field(default_factory=Power)
    online: bool = True
    device_count: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=None)

    @classmethod
    def from_json(cls, data: str) -> SiteStateSnapshot:
        d = json.loads(data)
        d["power"] = Power(**d["power"])
        return cls(**d)


@dataclass
class FlexEnvelope:
    baseline_kw: float = 0.0
    flex_down_kw: float = 0.0
    flex_up_kw: float = 0.0
    min_power_kw: float = 0.0
    max_power_kw: float = 0.0
    confidence: float = 0.85


@dataclass
class FlexConstraints:
    ramp_rate_up_kw_per_h: float = 400.0
    ramp_rate_down_kw_per_h: float = 400.0
    min_activation_duration_min: int = 15
    max_activation_duration_min: int = 120
    activation_lead_time_s: int = 30
    rebound_factor: float = 0.3


@dataclass
class Reliability:
    score: float = 0.9
    avg_delivery_ratio: float = 0.88


@dataclass
class SiteFlexOffer:
    site_id: str
    timestamp: str = field(default_factory=_now)
    valid_until: str = ""
    envelope: FlexEnvelope = field(default_factory=FlexEnvelope)
    constraints: FlexConstraints = field(default_factory=FlexConstraints)
    reliability: Reliability = field(default_factory=Reliability)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=None)

    @classmethod
    def from_json(cls, data: str) -> SiteFlexOffer:
        d = json.loads(data)
        d["envelope"] = FlexEnvelope(**d["envelope"])
        d["constraints"] = FlexConstraints(**d["constraints"])
        d["reliability"] = Reliability(**d["reliability"])
        return cls(**d)


# ---------------------------------------------------------------------------
# Phase 3: Dispatch (top-down)
# ---------------------------------------------------------------------------

@dataclass
class DispatchSlot:
    start: str
    end: str
    delta_kw: float


@dataclass
class AggregatorDispatch:
    dispatch_id: str = field(default_factory=lambda: f"dsp-{_uuid()}")
    site_id: str = ""
    issued_at: str = field(default_factory=_now)
    issued_by: str = "agg-01"
    direction: str = "down"
    target_delta_kw: float = 0.0
    schedule: list[DispatchSlot] = field(default_factory=list)
    reason: str = "congestion"
    priority: str = "firm"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=None)

    @classmethod
    def from_json(cls, data: str) -> AggregatorDispatch:
        d = json.loads(data)
        d["schedule"] = [DispatchSlot(**s) for s in d["schedule"]]
        return cls(**d)


@dataclass
class DispatchAck:
    dispatch_id: str = ""
    site_id: str = ""
    received_at: str = field(default_factory=_now)
    status: str = "accepted"  # accepted / partially_accepted / rejected
    accepted_delta_kw: float = 0.0
    rejection_reason: str = ""
    estimated_activation_time: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=None)

    @classmethod
    def from_json(cls, data: str) -> DispatchAck:
        return cls(**json.loads(data))


@dataclass
class FlexStatus:
    dispatch_id: str = ""
    site_id: str = ""
    active_devices: int = 0
    total_actual_power_kw: float = 0.0
    avg_soc_percent: float = 50.0
    timestamp: str = field(default_factory=_now)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=None)

    @classmethod
    def from_json(cls, data: str) -> FlexStatus:
        return cls(**json.loads(data))


@dataclass
class FlexRelease:
    dispatch_id: str = ""
    site_id: str = ""
    timestamp: str = field(default_factory=_now)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=None)


# ---------------------------------------------------------------------------
# Phase 4: Settle
# ---------------------------------------------------------------------------

@dataclass
class DeliveryReport:
    dispatch_id: str = ""
    site_id: str = ""
    generated_at: str = field(default_factory=_now)
    total_requested_kwh: float = 0.0
    total_delivered_kwh: float = 0.0
    delivery_ratio: float = 1.0
    rebound_kwh: float = 0.0
    baseline_method: str = "meter_before"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=None)

    @classmethod
    def from_json(cls, data: str) -> DeliveryReport:
        return cls(**json.loads(data))


# ---------------------------------------------------------------------------
# Internal: Simulated device (not on MQTT — internal to backend simulator)
# ---------------------------------------------------------------------------

@dataclass
class SimulatedDevice:
    device_id: str
    battery_kw: float = 5.0       # Max charge/discharge rate
    battery_kwh: float = 10.0     # Total capacity
    soc_percent: float = 50.0     # Current state of charge
    pv_kw: float = 0.0            # Current PV production
    consumption_kw: float = 1.5   # Current load
    online: bool = True
    min_soc: float = 20.0         # Prosumer floor
    max_soc: float = 95.0         # Prosumer ceiling
