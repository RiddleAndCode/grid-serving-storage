"""Technical Aggregator.

Phase 1: Subscribes to observe topics, builds portfolio model.
Phase 2: On trigger, runs portfolio-level MILP.
Phase 3: Publishes AggregatorDispatch per backend, collects acks/status.
Phase 4: Publishes FlexRelease, collects DeliveryReports.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt
import pulp

import config
from config import (
    AGGREGATOR_ID, MQTT_BROKER, MQTT_PORT, SEGMENT_ID,
    DISPATCH_DURATION_S,
    TOPIC_STATE, TOPIC_FLEX, TOPIC_DISPATCH, TOPIC_ACK,
    TOPIC_STATUS, TOPIC_RELEASE, TOPIC_COMMAND, TOPIC_AGG_STATE,
)
from models import (
    AggregatorDispatch, DeliveryReport, DispatchAck, DispatchSlot,
    FlexRelease, FlexStatus, SiteFlexOffer, SiteStateSnapshot, _now,
)

log = logging.getLogger("aggregator")


class Aggregator:
    """Technical Aggregator with portfolio MILP optimization."""

    def __init__(self, client: mqtt.Client):
        self.client = client
        self.snapshots: dict[str, SiteStateSnapshot] = {}
        self.flex_offers: dict[str, SiteFlexOffer] = {}
        self.acks: dict[str, DispatchAck] = {}
        self.statuses: dict[str, FlexStatus] = {}
        self.delivery_reports: dict[str, DeliveryReport] = {}
        self.current_dispatch_id: str | None = None
        self.dispatch_issued_at: float | None = None

        # Callbacks for dashboard
        self.on_snapshot: callable = None
        self.on_flex_offer: callable = None
        self.on_ack: callable = None
        self.on_status: callable = None
        self.on_delivery: callable = None
        self.on_milp_result: callable = None

    def handle_message(self, topic: str, payload: str):
        """Route incoming MQTT messages."""
        if "/observe/" in topic and "/state" in topic:
            snap = SiteStateSnapshot.from_json(payload)
            self.snapshots[snap.site_id] = snap
            if self.on_snapshot:
                self.on_snapshot(snap)

        elif "/observe/" in topic and "/flex" in topic:
            offer = SiteFlexOffer.from_json(payload)
            self.flex_offers[offer.site_id] = offer
            if self.on_flex_offer:
                self.on_flex_offer(offer)

        elif "/dispatch/" in topic and "/ack/" in topic:
            ack = DispatchAck.from_json(payload)
            self.acks[ack.site_id] = ack
            log.info(
                f"ACK from {ack.site_id}: {ack.status} "
                f"({ack.accepted_delta_kw:.0f}kW)"
            )
            if self.on_ack:
                self.on_ack(ack)

        elif "/dispatch/" in topic and "/status/" in topic:
            status = FlexStatus.from_json(payload)
            self.statuses[status.site_id] = status
            if self.on_status:
                self.on_status(status)

        elif "/settle/" in topic:
            report = DeliveryReport.from_json(payload)
            self.delivery_reports[report.site_id] = report
            log.info(
                f"DELIVERY from {report.site_id}: "
                f"ratio={report.delivery_ratio:.1%} "
                f"({report.total_delivered_kwh:.1f}/{report.total_requested_kwh:.1f} kWh)"
            )
            if self.on_delivery:
                self.on_delivery(report)

    def portfolio_summary(self) -> dict:
        """Summarize current portfolio state."""
        total_flex_down = 0.0
        total_flex_up = 0.0
        total_baseline = 0.0
        backends_online = 0

        for site_id, offer in self.flex_offers.items():
            total_flex_down += offer.envelope.flex_down_kw * offer.envelope.confidence
            total_flex_up += offer.envelope.flex_up_kw * offer.envelope.confidence
            total_baseline += offer.envelope.baseline_kw
            backends_online += 1

        return {
            "backends_online": backends_online,
            "total_flex_down_kw": round(total_flex_down, 1),
            "total_flex_up_kw": round(total_flex_up, 1),
            "total_baseline_kw": round(total_baseline, 1),
            "obligation_kw": config.GRID_OBLIGATION_KW,
            "can_meet": total_flex_down >= config.GRID_OBLIGATION_KW,
        }

    def run_milp(self) -> dict[str, float]:
        """Run portfolio-level MILP to allocate dispatch across backends.

        Returns: {backend_id: allocated_delta_kw}
        """
        if not self.flex_offers:
            log.warning("No flex offers available — cannot run MILP")
            return {}

        prob = pulp.LpProblem("aggregator_dispatch", pulp.LpMinimize)

        # Decision variables: how much to request from each backend
        alloc = {}
        for site_id, offer in self.flex_offers.items():
            if config.GRID_OBLIGATION_DIRECTION == "down":
                max_kw = offer.envelope.flex_down_kw
            else:
                max_kw = offer.envelope.flex_up_kw
            alloc[site_id] = prob.add_variable(f"alloc_{site_id}", lowBound=0, upBound=max_kw)

        # Constraint: meet the grid obligation
        total_available = sum(
            (offer.envelope.flex_down_kw if config.GRID_OBLIGATION_DIRECTION == "down"
             else offer.envelope.flex_up_kw)
            for offer in self.flex_offers.values()
        )
        target = min(config.GRID_OBLIGATION_KW, total_available)
        prob += pulp.lpSum(alloc.values()) >= target * 0.95, "meet_obligation"

        # Objective: minimize cost, penalizing unreliable backends
        # Reliability-weighted: prefer dispatching to reliable backends
        prob += pulp.lpSum(
            (1.0 - self.flex_offers[sid].reliability.score + 0.01) * alloc[sid]
            for sid in alloc
        ), "minimize_unreliability_cost"

        # Constraint: respect per-backend confidence-weighted capacity
        for site_id, offer in self.flex_offers.items():
            prob += (
                alloc[site_id] <= offer.envelope.flex_down_kw * offer.envelope.confidence
                if config.GRID_OBLIGATION_DIRECTION == "down"
                else alloc[site_id] <= offer.envelope.flex_up_kw * offer.envelope.confidence
            ), f"confidence_{site_id}"

        prob.solve(pulp.HiGHS(msg=0))

        result = {}
        for site_id in alloc:
            val = alloc[site_id].varValue or 0
            result[site_id] = round(val, 1)

        total = sum(result.values())
        log.info(f"MILP solved: total={total:.0f}kW across {len(result)} backends")
        for sid, kw in result.items():
            rel = self.flex_offers[sid].reliability.score
            log.info(f"  {sid}: {kw:.0f}kW (reliability={rel:.0%})")

        if self.on_milp_result:
            self.on_milp_result(result)

        return result

    def dispatch(self, allocation: dict[str, float]) -> str:
        """Publish AggregatorDispatch to each backend."""
        import uuid
        dispatch_id = f"dsp-{str(uuid.uuid4())[:8]}"
        self.current_dispatch_id = dispatch_id
        self.dispatch_issued_at = time.time()
        self.acks.clear()
        self.statuses.clear()
        self.delivery_reports.clear()

        now_dt = datetime.now(timezone.utc)
        start = (now_dt + timedelta(seconds=5)).isoformat(timespec="seconds")
        end = (now_dt + timedelta(seconds=DISPATCH_DURATION_S)).isoformat(timespec="seconds")

        for site_id, delta_kw in allocation.items():
            if delta_kw < 0.1:
                continue
            dispatch = AggregatorDispatch(
                dispatch_id=dispatch_id,
                site_id=site_id,
                issued_by=AGGREGATOR_ID,
                direction=config.GRID_OBLIGATION_DIRECTION,
                target_delta_kw=delta_kw,
                schedule=[DispatchSlot(start=start, end=end,
                                       delta_kw=-delta_kw if config.GRID_OBLIGATION_DIRECTION == "down" else delta_kw)],
                reason=config.GRID_OBLIGATION_REASON,
                priority="firm",
            )
            topic = TOPIC_DISPATCH.format(
                agg_id=AGGREGATOR_ID, segment_id=SEGMENT_ID
            )
            self.client.publish(topic, dispatch.to_json(), qos=1)
            log.info(f"DISPATCH → {site_id}: {delta_kw:.0f}kW {config.GRID_OBLIGATION_DIRECTION}")

        return dispatch_id

    def release(self, dispatch_id: str):
        """Publish FlexRelease."""
        release = FlexRelease(dispatch_id=dispatch_id, site_id="all")
        topic = TOPIC_RELEASE.format(
            agg_id=AGGREGATOR_ID, segment_id=SEGMENT_ID
        )
        self.client.publish(topic, release.to_json(), qos=1)
        log.info(f"RELEASE sent for {dispatch_id}")
        self.current_dispatch_id = None

    def publish_state(self):
        """Publish aggregator portfolio state for the dashboard."""
        summary = self.portfolio_summary()
        state = {
            "timestamp": _now(),
            "phase": "dispatch" if self.current_dispatch_id else "observe",
            "dispatch_id": self.current_dispatch_id,
            "backends_online": summary["backends_online"],
            "total_flex_down_kw": summary["total_flex_down_kw"],
            "total_flex_up_kw": summary["total_flex_up_kw"],
            "total_baseline_kw": summary["total_baseline_kw"],
            "obligation_kw": summary["obligation_kw"],
            "can_meet": summary["can_meet"],
            "acks": {sid: {"status": a.status, "accepted_kw": a.accepted_delta_kw}
                     for sid, a in self.acks.items()},
            "delivery_reports": {sid: {"ratio": r.delivery_ratio,
                                       "requested_kwh": r.total_requested_kwh,
                                       "delivered_kwh": r.total_delivered_kwh}
                                 for sid, r in self.delivery_reports.items()},
        }
        topic = TOPIC_AGG_STATE.format(agg_id=AGGREGATOR_ID)
        self.client.publish(topic, json.dumps(state), qos=0, retain=True)

    def handle_command(self, action: str, payload: dict):
        """Handle commands from dashboard or external trigger."""
        if action == "dispatch":
            obligation_kw = payload.get("obligation_kw", config.GRID_OBLIGATION_KW)
            direction = payload.get("direction", config.GRID_OBLIGATION_DIRECTION)
            reason = payload.get("reason", "manual")
            segment = payload.get("segment_id", SEGMENT_ID)

            log.info(f"=== COMMAND: dispatch {obligation_kw:.0f}kW {direction} in {segment} ===")

            orig_kw, orig_dir = config.GRID_OBLIGATION_KW, config.GRID_OBLIGATION_DIRECTION
            config.GRID_OBLIGATION_KW = obligation_kw
            config.GRID_OBLIGATION_DIRECTION = direction

            try:
                allocation = self.run_milp()
                if allocation:
                    self.dispatch(allocation)
            finally:
                config.GRID_OBLIGATION_KW = orig_kw
                config.GRID_OBLIGATION_DIRECTION = orig_dir

        elif action == "release":
            if self.current_dispatch_id:
                self.release(self.current_dispatch_id)
            else:
                log.warning("No active dispatch to release")

        self.publish_state()


def run_aggregator(mode: str = "continuous", broker: str | None = None,
                   port: int | None = None):
    """Run the aggregator.

    Modes:
      - "continuous": Run forever, dispatch via MQTT command topic
      - "oneshot": Observe, dispatch once, settle, exit (original behavior)
    """
    import config as _cfg
    _broker = broker or _cfg.MQTT_BROKER
    _port = port or _cfg.MQTT_PORT

    from config import OBSERVATION_WINDOW_S

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="aggregator")
    agg = Aggregator(client)

    def on_connect(client, userdata, flags, reason_code, properties):
        log.info(f"Aggregator connected to {_broker}:{_port} (rc={reason_code})")
        client.subscribe([
            (f"{AGGREGATOR_ID}/observe/+/state", 0),
            (f"{AGGREGATOR_ID}/observe/+/flex", 1),
            (f"{AGGREGATOR_ID}/dispatch/+/ack/+", 1),
            (f"{AGGREGATOR_ID}/dispatch/+/status/+", 0),
            (f"{AGGREGATOR_ID}/settle/+/+", 1),
            (f"{AGGREGATOR_ID}/command/+", 1),
        ])
        log.info("Subscribed to observe + dispatch + settle + command topics")

    def on_message(client, userdata, msg):
        payload_str = msg.payload.decode()
        if "/command/" in msg.topic:
            action = msg.topic.split("/")[-1]
            try:
                payload = json.loads(payload_str) if payload_str else {}
            except json.JSONDecodeError:
                payload = {}
            agg.handle_command(action, payload)
        else:
            agg.handle_message(msg.topic, payload_str)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(_broker, _port, 60)
    client.loop_start()

    if mode == "oneshot":
        # Original behavior: observe → dispatch → settle → exit
        try:
            log.info(f"Observing for {OBSERVATION_WINDOW_S}s...")
            time.sleep(OBSERVATION_WINDOW_S)

            summary = agg.portfolio_summary()
            log.info(f"Portfolio: {summary['backends_online']} backends, "
                     f"flex_down={summary['total_flex_down_kw']:.0f}kW")

            log.info("=== GRID EVENT ===")
            allocation = agg.run_milp()
            dispatch_id = agg.dispatch(allocation)

            log.info(f"Dispatch active for {DISPATCH_DURATION_S}s...")
            time.sleep(DISPATCH_DURATION_S)

            agg.release(dispatch_id)
            time.sleep(3)

            log.info("=== SETTLEMENT ===")
            for sid, report in agg.delivery_reports.items():
                log.info(f"  {sid}: {report.delivery_ratio:.1%}")

        except KeyboardInterrupt:
            if agg.current_dispatch_id:
                agg.release(agg.current_dispatch_id)
        finally:
            client.loop_stop()
            client.disconnect()

    else:
        # Continuous mode: observe forever, dispatch via command topic
        log.info("Aggregator running in continuous mode")
        log.info(f"  Trigger dispatch: publish to {AGGREGATOR_ID}/command/dispatch")
        log.info(f"  Release:          publish to {AGGREGATOR_ID}/command/release")
        log.info(f"  Portfolio state:  {AGGREGATOR_ID}/state/portfolio (retained)")

        try:
            last_state_publish = 0.0
            while True:
                now = time.time()
                # Publish portfolio state every 5 seconds
                if now - last_state_publish >= 5.0:
                    agg.publish_state()
                    last_state_publish = now

                    # Log summary periodically
                    summary = agg.portfolio_summary()
                    if summary["backends_online"] > 0:
                        log.info(
                            f"Portfolio: {summary['backends_online']} backends, "
                            f"flex_down={summary['total_flex_down_kw']:.0f}kW, "
                            f"flex_up={summary['total_flex_up_kw']:.0f}kW"
                            + (f" | ACTIVE dispatch {agg.current_dispatch_id}"
                               if agg.current_dispatch_id else "")
                        )

                time.sleep(1)

        except KeyboardInterrupt:
            log.info("Aggregator shutting down")
            if agg.current_dispatch_id:
                agg.release(agg.current_dispatch_id)
        finally:
            client.loop_stop()
            client.disconnect()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Technical Aggregator")
    parser.add_argument(
        "--mode",
        choices=["continuous", "oneshot"],
        default="continuous",
        help="continuous: run forever, trigger via MQTT. oneshot: single cycle then exit.",
    )
    parser.add_argument("--broker", type=str, default=None, help="MQTT broker host")
    args = parser.parse_args()

    run_aggregator(mode=args.mode, broker=args.broker)
