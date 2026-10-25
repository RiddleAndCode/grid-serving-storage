"""HEMS Backend Simulator.

Simulates N HEMS backends, each managing M devices.
Phase 1 (Observe): publishes SiteStateSnapshot + SiteFlexOffer.
Phase 3 (Dispatch): receives AggregatorDispatch, runs device-level MILP,
                    publishes DispatchAck, FlexStatus, DeliveryReport.

When a VTN URL is configured, the backend creates real OpenADR 3.1 events
on the VTN instead of just logging simulated interactions.
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timedelta, timezone

import httpx
import paho.mqtt.client as mqtt
import pulp

from config import (
    AGGREGATOR_ID, BACKENDS, MQTT_BROKER, MQTT_PORT,
    SEGMENT_ID, SNAPSHOT_INTERVAL_S, FLEX_OFFER_INTERVAL_S,
    STATUS_INTERVAL_S, DISPATCH_DURATION_S,
    PV_SCALE, CONS_SCALE,
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

    def __init__(self, cfg: dict, client: mqtt.Client, vtn_url: str | None = None):
        self.cfg = cfg
        self.id = cfg["id"]
        self.client = client
        self.devices: list[SimulatedDevice] = []
        self.active_dispatch: AggregatorDispatch | None = None
        self.dispatch_start_time: float | None = None
        self.total_requested_kwh = 0.0
        self.total_delivered_kwh = 0.0
        self.vtn_url = vtn_url
        self.vtn_token: str | None = None
        self.vtn_event_ids: list[str] = []
        self._init_devices()
        if self.vtn_url:
            self._init_vtn()

    def _init_devices(self):
        """Create simulated devices with randomized but realistic state."""
        for i in range(self.cfg["device_count"]):
            peak_pv = self.cfg["avg_pv_kw"] * PV_SCALE * random.uniform(0.7, 1.3) if self.cfg["has_pv"] else 0
            dev = SimulatedDevice(
                device_id=f"{self.id}-dev-{i:03d}",
                battery_kw=self.cfg["avg_battery_kw"] * random.uniform(0.7, 1.3),
                battery_kwh=self.cfg["avg_battery_kwh"] * random.uniform(0.8, 1.2),
                soc_percent=random.uniform(25, 90),
                pv_kw=max(0.0, peak_pv * random.uniform(0.3, 0.9)),
                consumption_kw=max(0.2, random.uniform(0.5, 4.0) * CONS_SCALE),
                online=random.random() > 0.05,  # 95% online
                min_soc=random.uniform(15, 25),
                max_soc=random.uniform(90, 98),
            )
            self.devices.append(dev)

    def _init_vtn(self):
        """Authenticate with the OpenADR 3.1 VTN."""
        try:
            resp = httpx.post(
                f"{self.vtn_url}/auth/token",
                json={"grant_type": "client_credentials", "client_id": f"backend-{self.id}", "client_secret": "demo"},
                timeout=10,
            )
            resp.raise_for_status()
            self.vtn_token = resp.json()["access_token"]
            log.info(f"[{self.id}] Authenticated with VTN at {self.vtn_url}")
        except Exception as e:
            log.warning(f"[{self.id}] VTN auth failed: {e} — falling back to simulated OpenADR")
            self.vtn_url = None

    def _vtn_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.vtn_token}", "Content-Type": "application/json"}

    def _create_vtn_dispatch_event(self, dispatch: AggregatorDispatch, total_delta_kw: float):
        """Create a single site-level OpenADR 3.1 event on the VTN for this dispatch.

        The VTN event represents the aggregate capacity limit for the whole site,
        not per-device allocations (device-level MILP stays internal to the backend).
        The VEN polls this event and distributes the limit across its resources.
        """
        if not self.vtn_url or not self.vtn_token:
            return
        try:
            payload_type = "IMPORT_CAPACITY_LIMIT" if dispatch.direction == "down" else "EXPORT_CAPACITY_LIMIT"
            now = datetime.now(timezone.utc)
            event = {
                "programID": "prg-grid-capacity",
                "eventName": f"dispatch-{dispatch.dispatch_id}-{self.id}",
                "priority": 1 if dispatch.priority == "firm" else (0 if dispatch.priority == "emergency" else 2),
                "targets": [{"type": "VEN_NAME", "values": [self.id]}],
                "intervals": [{
                    "id": 0,
                    "intervalPeriod": {
                        "start": now.isoformat(timespec="seconds"),
                        "duration": f"PT{int(DISPATCH_DURATION_S)}S",
                    },
                    "payloads": [{"type": payload_type, "values": [abs(total_delta_kw)]}],
                }],
            }

            resp = httpx.post(
                f"{self.vtn_url}/events",
                json=event,
                headers=self._vtn_headers(),
                timeout=10,
            )
            resp.raise_for_status()
            evt_id = resp.json().get("id", "unknown")
            self.vtn_event_ids.append(evt_id)
            log.info(
                f"[{self.id}] OpenADR 3.1 VTN event created: "
                f"{payload_type}={abs(total_delta_kw):.1f}kW (evt={evt_id})"
            )
        except Exception as e:
            log.warning(f"[{self.id}] OpenADR 3.1 event creation failed: {e}")

    def _poll_vtn_reports(self):
        """Read VEN reports from the VTN to observe device-side telemetry."""
        if not self.vtn_url or not self.vtn_token:
            return
        try:
            resp = httpx.get(
                f"{self.vtn_url}/reports",
                params={"programID": "prg-flex-readiness"},
                headers=self._vtn_headers(),
                timeout=10,
            )
            resp.raise_for_status()
            ven_reports = resp.json()
            # Find the most recent status report (has multiple resources, not forecast)
            status_reports = [r for r in ven_reports if len(r.get("resources", [])) > 1]
            if status_reports:
                latest = status_reports[-1]
                resources = latest.get("resources", [])
                for res in resources:
                    name = res.get("resourceName", "?")
                    intervals = res.get("intervals", [])
                    if not intervals:
                        continue
                    payloads = intervals[-1].get("payloads", [])
                    readings = {p["type"]: p["values"][0] for p in payloads if p.get("values")}
                    if name == "AGGREGATED_REPORT":
                        reading = readings.get("READING", "?")
                        state = readings.get("OPERATING_STATE", "?")
                        shed = readings.get("LOAD_SHED_DELTA_AVAILABLE", "?")
                        log.info(
                            f"[{self.id}] VEN report (via VTN): "
                            f"state={state}, net={reading}kW, shed_avail={shed}kW"
                        )
        except Exception as e:
            log.debug(f"[{self.id}] VTN report poll failed: {e}")

    def _delete_vtn_events(self):
        """Remove dispatch events from the VTN (release)."""
        if not self.vtn_url or not self.vtn_token:
            return
        for evt_id in self.vtn_event_ids:
            try:
                httpx.delete(
                    f"{self.vtn_url}/events/{evt_id}",
                    headers=self._vtn_headers(),
                    timeout=10,
                )
                log.info(f"  OpenADR 3.1 VTN event deleted: {evt_id}")
            except Exception as e:
                log.warning(f"  OpenADR 3.1 event delete failed for {evt_id}: {e}")
        self.vtn_event_ids.clear()

    def _drift_devices(self):
        """Update device PV and consumption with gentle random walk."""
        for dev in self.devices:
            if not dev.online:
                if random.random() < 0.1:
                    dev.online = True
                continue

            # PV: gentle random walk around current value
            if self.cfg["has_pv"]:
                peak_pv = self.cfg["avg_pv_kw"] * PV_SCALE
                dev.pv_kw += random.uniform(-0.3, 0.3) * peak_pv * 0.1
                dev.pv_kw = max(0.0, min(peak_pv * 1.3, dev.pv_kw))
            else:
                dev.pv_kw = 0.0

            # Consumption: gentle random walk
            dev.consumption_kw += random.uniform(-0.2, 0.2)
            dev.consumption_kw = max(0.2, min(5.0 * CONS_SCALE, dev.consumption_kw))

            # SoC drifts based on net power
            if dev.pv_kw > dev.consumption_kw:
                dev.soc_percent += random.uniform(0.5, 2.0)
            else:
                dev.soc_percent -= random.uniform(0.3, 1.5)
            dev.soc_percent = max(dev.min_soc, min(dev.max_soc, dev.soc_percent))

            if random.random() < 0.02:
                dev.online = False

    def compute_snapshot(self) -> SiteStateSnapshot:
        """Aggregate device state into a site-level snapshot."""
        online = [d for d in self.devices if d.online]
        total_pv = sum(d.pv_kw for d in online)
        total_consumption = sum(d.consumption_kw for d in online)

        # During active dispatch, battery power shows up in production/consumption
        # so that net = consumption - production always holds
        if self.active_dispatch:
            actual = self.active_dispatch.target_delta_kw * random.uniform(0.85, 1.0)
            if self.active_dispatch.direction == "down":
                total_pv += actual  # discharging = site produces more
            else:
                total_consumption += actual  # charging = site consumes more

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

        # Dispatch to devices via OpenADR
        accepted_devices = 0
        total_accepted = 0.0
        for dev_id, delta in allocation.items():
            dev = next(d for d in self.devices if d.device_id == dev_id)
            if abs(delta) > 0.01:
                accepted_devices += 1
                total_accepted += abs(delta)
                if not self.vtn_url:
                    log.info(
                        f"  OpenADR VTN→VEN: oadrDistributeEvent to {dev_id}, "
                        f"setpoint: {delta:+.1f}kW (SoC: {dev.soc_percent:.0f}%)"
                    )
            else:
                log.info(f"  OpenADR VTN→VEN: {dev_id} optOut (SoC: {dev.soc_percent:.0f}%)")

        # Create a single site-level event on the VTN with the aggregate allocation
        if self.vtn_url and total_accepted > 0.01:
            self._create_vtn_dispatch_event(dispatch, total_accepted)

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
        # Read VEN telemetry from VTN (closes the feedback loop)
        self._poll_vtn_reports()
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

        # Clean up OpenADR 3.1 events on VTN
        self._delete_vtn_events()

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


def _run_loop(backends: list[HEMSBackend], client: mqtt.Client,
              broker: str | None = None, port: int | None = None):
    """Main publish loop shared by single and multi-backend modes."""
    import config as _cfg
    _broker = broker or _cfg.MQTT_BROKER
    _port = port or _cfg.MQTT_PORT

    def on_connect(client, userdata, flags, reason_code, properties):
        log.info(f"Backend(s) connected to {_broker}:{_port} (rc={reason_code})")
        dispatch_topic = TOPIC_DISPATCH.format(agg_id=AGGREGATOR_ID, segment_id="+")
        release_topic = TOPIC_RELEASE.format(agg_id=AGGREGATOR_ID, segment_id="+")
        client.subscribe([(dispatch_topic, 1), (release_topic, 1)])

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
    client.connect(_broker, _port, 60)
    client.loop_start()

    log.info(f"Running backends: {[b.id for b in backends]}")

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


def run_backends(backend_ids: list[str] | None = None,
                 broker: str | None = None, port: int | None = None,
                 vtn_url: str | None = None):
    """Run backend simulators.

    Args:
        backend_ids: List of backend IDs to run. None = all backends.
        broker: MQTT broker host. None = use config default.
        port: MQTT broker port. None = use config default.
        vtn_url: OpenADR 3.1 VTN base URL. None = simulate OpenADR in-process.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    configs = BACKENDS
    if backend_ids:
        configs = [c for c in BACKENDS if c["id"] in backend_ids]
        if not configs:
            log.error(f"No matching backend config for {backend_ids}. Available: {[c['id'] for c in BACKENDS]}")
            return

    client_id = f"backend-{configs[0]['id']}" if len(configs) == 1 else "backend-sim"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    backends = [HEMSBackend(cfg, client, vtn_url=vtn_url) for cfg in configs]
    _run_loop(backends, client, broker=broker, port=port)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HEMS Backend Simulator")
    parser.add_argument(
        "--backend-id",
        type=str,
        default=None,
        help="Run a single backend by ID (e.g. kern-01). Default: run all.",
    )
    parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="MQTT broker host (default: from config.py)",
    )
    parser.add_argument(
        "--vtn-url",
        type=str,
        default=None,
        help="OpenADR 3.1 VTN URL (e.g. http://localhost:8088). Default: simulate OpenADR in-process.",
    )
    args = parser.parse_args()

    if args.backend_id:
        run_backends([args.backend_id], broker=args.broker, vtn_url=args.vtn_url)
    else:
        run_backends(broker=args.broker, vtn_url=args.vtn_url)
