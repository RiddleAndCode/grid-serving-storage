"""HEMS Backend Simulator.

Simulates N HEMS backends, each managing M devices.
Phase 1 (Observe): publishes SiteStateSnapshot + SiteFlexOffer.
Phase 3 (Dispatch): receives AggregatorDispatch, runs device-level MILP,
                    publishes DispatchAck, FlexStatus, DeliveryReport.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt
import pulp

from config import (
    AGGREGATOR_ID, BACKENDS, MQTT_BROKER, MQTT_PORT,
    SEGMENT_ID, SNAPSHOT_INTERVAL_S, FLEX_OFFER_INTERVAL_S,
    STATUS_INTERVAL_S, DISPATCH_DURATION_S,
    TOPIC_STATE, TOPIC_FLEX, TOPIC_DISPATCH, TOPIC_ACK,
    TOPIC_STATUS, TOPIC_RELEASE, TOPIC_SETTLE,
)
from models import (
    AggregatorDispatch, DeliveryReport, DispatchAck, FlexConstraints,
    FlexEnvelope, FlexRelease, FlexStatus, Power, Reliability,
    SimulatedDevice, SiteFlexOffer, SiteStateSnapshot, _now,
)

log = logging.getLogger("backend")


class HEMSBackend:
    """Simulates one HEMS backend with its managed devices."""

    def __init__(self, cfg: dict, client: mqtt.Client):
        self.cfg = cfg
        self.id = cfg["id"]
        self.client = client
        self.devices: list[SimulatedDevice] = []
        self.active_dispatch: AggregatorDispatch | None = None
        self.dispatch_start_time: float | None = None
        self.total_requested_kwh = 0.0
        self.total_delivered_kwh = 0.0
        self._init_devices()

    def _init_devices(self):
        """Create simulated devices with randomized but realistic state."""
        for i in range(self.cfg["device_count"]):
            dev = SimulatedDevice(
                device_id=f"{self.id}-dev-{i:03d}",
                battery_kw=self.cfg["avg_battery_kw"] * random.uniform(0.7, 1.3),
                battery_kwh=self.cfg["avg_battery_kwh"] * random.uniform(0.8, 1.2),
                soc_percent=random.uniform(25, 90),
                pv_kw=self.cfg["avg_pv_kw"] * random.uniform(0.0, 1.0) if self.cfg["has_pv"] else 0,
                consumption_kw=random.uniform(0.5, 4.0),
                online=random.random() > 0.05,  # 95% online
                min_soc=random.uniform(15, 25),
                max_soc=random.uniform(90, 98),
            )
            self.devices.append(dev)

    def _drift_devices(self):
        """Small random drift to simulate changing conditions."""
        for dev in self.devices:
            if not dev.online:
                if random.random() < 0.1:
                    dev.online = True
                continue
            dev.soc_percent += random.uniform(-1.5, 1.5)
            dev.soc_percent = max(dev.min_soc, min(dev.max_soc, dev.soc_percent))
            dev.pv_kw = max(0, dev.pv_kw + random.uniform(-0.3, 0.3))
            dev.consumption_kw = max(0.2, dev.consumption_kw + random.uniform(-0.2, 0.2))
            if random.random() < 0.02:
                dev.online = False

    def compute_snapshot(self) -> SiteStateSnapshot:
        """Aggregate device state into a site-level snapshot."""
        online = [d for d in self.devices if d.online]
        total_pv = sum(d.pv_kw for d in online)
        total_consumption = sum(d.consumption_kw for d in online)
        net = total_consumption - total_pv
        return SiteStateSnapshot(
            site_id=self.id,
            grid_capacity_kw=self.cfg["avg_battery_kw"] * self.cfg["device_count"],
            power=Power(
                import_kw=max(0, net),
                export_kw=max(0, -net),
                net_kw=net,
                production_kw=total_pv,
                consumption_kw=total_consumption,
            ),
            online=True,
            device_count=len(online),
        )

    def compute_flex_offer(self) -> SiteFlexOffer:
        """Compute flexibility envelope from device capabilities."""
        online = [d for d in self.devices if d.online]
        baseline = sum(d.consumption_kw - d.pv_kw for d in online)

        # flex_down: how much we can reduce (discharge batteries, shed load)
        flex_down = sum(
            min(d.battery_kw, (d.soc_percent - d.min_soc) / 100 * d.battery_kwh)
            for d in online
        )
        # flex_up: how much we can increase (charge batteries)
        flex_up = sum(
            min(d.battery_kw, (d.max_soc - d.soc_percent) / 100 * d.battery_kwh)
            for d in online
        )

        avg_ramp = self.cfg["avg_battery_kw"] * len(online) * 2
        valid_until = (datetime.now(timezone.utc) + timedelta(seconds=FLEX_OFFER_INTERVAL_S * 3)).isoformat(timespec="seconds")

        return SiteFlexOffer(
            site_id=self.id,
            valid_until=valid_until,
            envelope=FlexEnvelope(
                baseline_kw=round(baseline, 1),
                flex_down_kw=round(flex_down, 1),
                flex_up_kw=round(flex_up, 1),
                min_power_kw=round(baseline - flex_down, 1),
                max_power_kw=round(baseline + flex_up, 1),
                confidence=round(random.uniform(0.75, 0.95), 2),
            ),
            constraints=FlexConstraints(
                ramp_rate_up_kw_per_h=round(avg_ramp, 1),
                ramp_rate_down_kw_per_h=round(avg_ramp, 1),
                min_activation_duration_min=15,
                max_activation_duration_min=120,
                activation_lead_time_s=30,
                rebound_factor=round(random.uniform(0.2, 0.4), 2),
            ),
            reliability=Reliability(
                score=round(random.uniform(0.8, 0.98), 2),
                avg_delivery_ratio=round(random.uniform(0.82, 0.96), 2),
            ),
        )

    def publish_snapshot(self):
        self._drift_devices()
        snap = self.compute_snapshot()
        topic = TOPIC_STATE.format(agg_id=AGGREGATOR_ID, backend_id=self.id)
        self.client.publish(topic, snap.to_json(), qos=0, retain=True)
        log.info(f"[{self.id}] snapshot: net={snap.power.net_kw:+.1f}kW, devices={snap.device_count}")

    def publish_flex_offer(self):
        offer = self.compute_flex_offer()
        topic = TOPIC_FLEX.format(agg_id=AGGREGATOR_ID, backend_id=self.id)
        self.client.publish(topic, offer.to_json(), qos=1, retain=True)
        log.info(
            f"[{self.id}] flex offer: down={offer.envelope.flex_down_kw:.0f}kW "
            f"up={offer.envelope.flex_up_kw:.0f}kW conf={offer.envelope.confidence:.0%}"
        )

    def handle_dispatch(self, dispatch: AggregatorDispatch):
        """Receive dispatch, run device MILP, acknowledge."""
        self.active_dispatch = dispatch
        self.dispatch_start_time = time.time()
        self.total_requested_kwh = 0.0
        self.total_delivered_kwh = 0.0

        log.info(f"[{self.id}] DISPATCH received: {dispatch.direction} {dispatch.target_delta_kw:.0f}kW")

        # Run device-level MILP
        allocation = self._run_device_milp(dispatch)

        # Simulate OpenADR interactions
        accepted_devices = 0
        total_accepted = 0.0
        for dev_id, delta in allocation.items():
            dev = next(d for d in self.devices if d.device_id == dev_id)
            if abs(delta) > 0.01:
                accepted_devices += 1
                total_accepted += abs(delta)
                log.info(
                    f"  OpenADR VTN→VEN: oadrDistributeEvent to {dev_id}, "
                    f"setpoint: {delta:+.1f}kW (SoC: {dev.soc_percent:.0f}%)"
                )
            else:
                log.info(f"  OpenADR VTN→VEN: {dev_id} optOut (SoC: {dev.soc_percent:.0f}%)")

        # Publish DispatchAck
        status = "accepted" if total_accepted >= dispatch.target_delta_kw * 0.9 else "partially_accepted"
        ack = DispatchAck(
            dispatch_id=dispatch.dispatch_id,
            site_id=self.id,
            status=status,
            accepted_delta_kw=round(total_accepted, 1),
            rejection_reason="" if status == "accepted" else f"{dispatch.target_delta_kw - total_accepted:.0f}kW unavailable",
            estimated_activation_time=_now(),
        )
        topic = TOPIC_ACK.format(
            agg_id=AGGREGATOR_ID, segment_id=SEGMENT_ID, backend_id=self.id
        )
        self.client.publish(topic, ack.to_json(), qos=1)
        log.info(
            f"[{self.id}] ACK: {status}, accepted={total_accepted:.0f}kW "
            f"({accepted_devices}/{len(self.devices)} devices)"
        )

    def _run_device_milp(self, dispatch: AggregatorDispatch) -> dict[str, float]:
        """Run MILP to distribute dispatch across devices."""
        online = [d for d in self.devices if d.online]
        if not online:
            return {}

        prob = pulp.LpProblem(f"backend_{self.id}_dispatch", pulp.LpMinimize)

        # Decision variables: how much each device contributes (kW)
        alloc = {}
        for d in online:
            if dispatch.direction == "down":
                max_contribution = min(
                    d.battery_kw,
                    (d.soc_percent - d.min_soc) / 100 * d.battery_kwh,
                )
            else:
                max_contribution = min(
                    d.battery_kw,
                    (d.max_soc - d.soc_percent) / 100 * d.battery_kwh,
                )
            max_contribution = max(0, max_contribution)
            alloc[d.device_id] = prob.add_variable(
                f"alloc_{d.device_id}", lowBound=0, upBound=max_contribution
            )

        # Constraint: try to meet the target
        total_available = sum(alloc[d.device_id].upBound or 0 for d in online)
        target = min(dispatch.target_delta_kw, total_available)
        prob += pulp.lpSum(alloc[d.device_id] for d in online) >= target * 0.95, "meet_target"

        # Objective: minimize slack (maximize delivery) + small fairness term
        # Slack allows infeasible targets to still produce a solution
        slack = prob.add_variable("slack", lowBound=0)
        prob += pulp.lpSum(alloc[d.device_id] for d in online) + slack >= target, "slack_target"
        prob += slack, "minimize_slack"

        prob.solve(pulp.HiGHS(msg=0))

        result = {}
        for d in online:
            val = alloc[d.device_id].varValue or 0
            sign = -1 if dispatch.direction == "down" else 1
            result[d.device_id] = round(val * sign, 2)

        return result

    def publish_status(self):
        """Publish FlexStatus during active dispatch."""
        if not self.active_dispatch:
            return
        online = [d for d in self.devices if d.online]
        # Simulate actual delivery with some noise
        target = self.active_dispatch.target_delta_kw
        actual = target * random.uniform(0.85, 1.0)
        avg_soc = sum(d.soc_percent for d in online) / max(1, len(online))

        elapsed_h = (time.time() - self.dispatch_start_time) / 3600 if self.dispatch_start_time else 0
        self.total_requested_kwh += target * (STATUS_INTERVAL_S / 3600)
        self.total_delivered_kwh += actual * (STATUS_INTERVAL_S / 3600)

        status = FlexStatus(
            dispatch_id=self.active_dispatch.dispatch_id,
            site_id=self.id,
            active_devices=len([d for d in online if d.soc_percent > d.min_soc]),
            total_actual_power_kw=round(actual, 1),
            avg_soc_percent=round(avg_soc, 1),
        )
        topic = TOPIC_STATUS.format(
            agg_id=AGGREGATOR_ID, segment_id=SEGMENT_ID, backend_id=self.id
        )
        self.client.publish(topic, status.to_json(), qos=0)
        # Drift SoC during dispatch
        for d in online:
            if self.active_dispatch.direction == "down":
                d.soc_percent = max(d.min_soc, d.soc_percent - random.uniform(0.5, 2.0))
            else:
                d.soc_percent = min(d.max_soc, d.soc_percent + random.uniform(0.5, 2.0))

    def handle_release(self, dispatch_id: str):
        """Handle FlexRelease — generate DeliveryReport."""
        if not self.active_dispatch or self.active_dispatch.dispatch_id != dispatch_id:
            return

        ratio = self.total_delivered_kwh / max(0.001, self.total_requested_kwh)
        report = DeliveryReport(
            dispatch_id=dispatch_id,
            site_id=self.id,
            total_requested_kwh=round(self.total_requested_kwh, 2),
            total_delivered_kwh=round(self.total_delivered_kwh, 2),
            delivery_ratio=round(ratio, 3),
            rebound_kwh=round(self.total_delivered_kwh * 0.25, 2),
            baseline_method="meter_before",
        )
        topic = TOPIC_SETTLE.format(
            agg_id=AGGREGATOR_ID, backend_id=self.id, dispatch_id=dispatch_id
        )
        self.client.publish(topic, report.to_json(), qos=1)
        log.info(
            f"[{self.id}] DELIVERY REPORT: requested={report.total_requested_kwh:.1f}kWh "
            f"delivered={report.total_delivered_kwh:.1f}kWh ratio={report.delivery_ratio:.1%}"
        )
        self.active_dispatch = None
        self.dispatch_start_time = None


def run_backends():
    """Run all backend simulators."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="backend-sim")
    backends: list[HEMSBackend] = []

    for cfg in BACKENDS:
        backends.append(HEMSBackend(cfg, client))

    def on_connect(client, userdata, flags, reason_code, properties):
        log.info(f"Backend simulator connected (rc={reason_code})")
        # Subscribe to dispatch and release topics
        dispatch_topic = TOPIC_DISPATCH.format(
            agg_id=AGGREGATOR_ID, segment_id="+"
        )
        release_topic = TOPIC_RELEASE.format(
            agg_id=AGGREGATOR_ID, segment_id="+"
        )
        client.subscribe([(dispatch_topic, 1), (release_topic, 1)])
        log.info(f"Subscribed to dispatch: {dispatch_topic}")

    def on_message(client, userdata, msg):
        payload = msg.payload.decode()
        if "/dispatch/" in msg.topic and "/request" in msg.topic:
            dispatch = AggregatorDispatch.from_json(payload)
            for b in backends:
                if b.id == dispatch.site_id:
                    b.handle_dispatch(dispatch)
        elif "/dispatch/" in msg.topic and "/release" in msg.topic:
            data = json.loads(payload)
            dispatch_id = data.get("dispatch_id", "")
            for b in backends:
                b.handle_release(dispatch_id)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()

    log.info(f"Starting {len(backends)} backends: {[b.id for b in backends]}")

    try:
        last_snapshot = 0.0
        last_flex = 0.0
        last_status = 0.0

        while True:
            now = time.time()

            if now - last_snapshot >= SNAPSHOT_INTERVAL_S:
                for b in backends:
                    b.publish_snapshot()
                last_snapshot = now

            if now - last_flex >= FLEX_OFFER_INTERVAL_S:
                for b in backends:
                    b.publish_flex_offer()
                last_flex = now

            if now - last_status >= STATUS_INTERVAL_S:
                for b in backends:
                    b.publish_status()
                last_status = now

            time.sleep(0.5)

    except KeyboardInterrupt:
        log.info("Backend simulator shutting down")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    run_backends()
