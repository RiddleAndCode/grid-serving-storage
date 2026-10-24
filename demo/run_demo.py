#!/usr/bin/env python3
"""Grid-Serving Storage Demo — Orchestrator.

Runs the full four-phase loop with a rich terminal dashboard:
  Phase 1: Observe  — backends publish state + flex offers
  Phase 2: Plan     — aggregator runs MILP
  Phase 3: Dispatch — aggregator sends goals, backends distribute to devices
  Phase 4: Settle   — delivery reports, reliability scoring
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import (
    AGGREGATOR_ID, BACKENDS, DISPATCH_DURATION_S, GRID_OBLIGATION_DIRECTION,
    GRID_OBLIGATION_KW, MQTT_BROKER, MQTT_PORT, OBSERVATION_WINDOW_S,
    SEGMENT_ID,
)
from aggregator import Aggregator
from backend_simulator import HEMSBackend
from models import (
    AggregatorDispatch, DeliveryReport, DispatchAck, FlexStatus,
    SiteFlexOffer, SiteStateSnapshot,
)


class DemoState:
    """Shared state for the dashboard."""

    def __init__(self):
        self.phase = "STARTING"
        self.phase_detail = ""
        self.mqtt_log: list[tuple[str, str, str]] = []  # (time, phase_color, message)
        self.milp_result: dict[str, float] = {}
        self.observation_start: float = 0
        self.dispatch_start: float = 0
        self.lock = threading.Lock()

    def log(self, phase_color: str, msg: str):
        with self.lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.mqtt_log.append((ts, phase_color, msg))
            if len(self.mqtt_log) > 30:
                self.mqtt_log = self.mqtt_log[-30:]


def build_dashboard(state: DemoState, agg: Aggregator) -> Layout:
    """Build the rich dashboard layout."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=1),
    )
    layout["left"].split_column(
        Layout(name="portfolio", ratio=2),
        Layout(name="dispatch", ratio=1),
    )
    layout["right"].split_column(
        Layout(name="mqtt_log", ratio=2),
        Layout(name="settlement", ratio=1),
    )

    # Header
    phase_colors = {
        "STARTING": "white",
        "OBSERVE": "cyan",
        "PLAN": "yellow",
        "DISPATCH": "red",
        "EXECUTE": "magenta",
        "SETTLE": "green",
        "DONE": "bright_green",
    }
    color = phase_colors.get(state.phase, "white")
    elapsed = ""
    if state.phase == "OBSERVE" and state.observation_start:
        remaining = max(0, OBSERVATION_WINDOW_S - (time.time() - state.observation_start))
        elapsed = f" ({remaining:.0f}s until dispatch)"
    elif state.phase == "EXECUTE" and state.dispatch_start:
        remaining = max(0, DISPATCH_DURATION_S - (time.time() - state.dispatch_start))
        elapsed = f" ({remaining:.0f}s remaining)"

    header_text = Text()
    header_text.append("  Grid-Serving Storage Demo ", style="bold white on blue")
    header_text.append(f"  Phase: ", style="white")
    header_text.append(f"{state.phase}", style=f"bold {color}")
    header_text.append(f"{elapsed}", style="dim")
    if state.phase_detail:
        header_text.append(f"  {state.phase_detail}", style="dim")
    layout["header"].update(Panel(header_text, style="blue"))

    # Portfolio table
    portfolio_table = Table(title="Portfolio (Observe)", expand=True, show_lines=True)
    portfolio_table.add_column("Backend", style="bold")
    portfolio_table.add_column("Devices", justify="right")
    portfolio_table.add_column("Net kW", justify="right")
    portfolio_table.add_column("Flex Down", justify="right", style="red")
    portfolio_table.add_column("Flex Up", justify="right", style="green")
    portfolio_table.add_column("Confidence", justify="right")
    portfolio_table.add_column("Reliability", justify="right")

    total_down = 0
    total_up = 0
    for sid, offer in agg.flex_offers.items():
        snap = agg.snapshots.get(sid)
        devices = str(snap.device_count) if snap else "-"
        net = f"{snap.power.net_kw:+.1f}" if snap else "-"
        conf = f"{offer.envelope.confidence:.0%}"
        rel = f"{offer.reliability.score:.0%}"
        total_down += offer.envelope.flex_down_kw
        total_up += offer.envelope.flex_up_kw
        portfolio_table.add_row(
            sid, devices, net,
            f"{offer.envelope.flex_down_kw:.0f}",
            f"{offer.envelope.flex_up_kw:.0f}",
            conf, rel,
        )

    portfolio_table.add_row(
        "[bold]TOTAL[/bold]", "", "",
        f"[bold red]{total_down:.0f}[/bold red]",
        f"[bold green]{total_up:.0f}[/bold green]",
        "", "",
    )
    layout["portfolio"].update(Panel(portfolio_table, border_style="cyan"))

    # Dispatch / MILP result
    dispatch_table = Table(title="Dispatch (MILP Allocation)", expand=True)
    dispatch_table.add_column("Backend", style="bold")
    dispatch_table.add_column("Allocated kW", justify="right", style="yellow")
    dispatch_table.add_column("ACK Status", justify="center")
    dispatch_table.add_column("Accepted kW", justify="right")

    if state.milp_result:
        for sid, kw in state.milp_result.items():
            ack = agg.acks.get(sid)
            ack_status = ""
            accepted = ""
            if ack:
                if ack.status == "accepted":
                    ack_status = "[green]ACCEPTED[/green]"
                elif ack.status == "partially_accepted":
                    ack_status = "[yellow]PARTIAL[/yellow]"
                else:
                    ack_status = "[red]REJECTED[/red]"
                accepted = f"{ack.accepted_delta_kw:.0f}"
            dispatch_table.add_row(sid, f"{kw:.0f}", ack_status, accepted)

        total_alloc = sum(state.milp_result.values())
        dispatch_table.add_row(
            "[bold]TOTAL[/bold]",
            f"[bold]{total_alloc:.0f}[/bold] / {GRID_OBLIGATION_KW:.0f} target",
            "", "",
        )
    else:
        dispatch_table.add_row("[dim]Waiting for dispatch trigger...[/dim]", "", "", "")

    layout["dispatch"].update(Panel(dispatch_table, border_style="yellow"))

    # MQTT message log
    log_text = Text()
    with state.lock:
        for ts, color, msg in state.mqtt_log[-20:]:
            log_text.append(f"{ts} ", style="dim")
            log_text.append(f"{msg}\n", style=color)

    layout["mqtt_log"].update(Panel(log_text, title="MQTT Messages", border_style="blue"))

    # Settlement
    settle_table = Table(title="Settlement", expand=True)
    settle_table.add_column("Backend", style="bold")
    settle_table.add_column("Requested kWh", justify="right")
    settle_table.add_column("Delivered kWh", justify="right")
    settle_table.add_column("Ratio", justify="right")

    if agg.delivery_reports:
        for sid, report in agg.delivery_reports.items():
            ratio_style = "green" if report.delivery_ratio >= 0.9 else "yellow"
            settle_table.add_row(
                sid,
                f"{report.total_requested_kwh:.2f}",
                f"{report.total_delivered_kwh:.2f}",
                f"[{ratio_style}]{report.delivery_ratio:.1%}[/{ratio_style}]",
            )
    else:
        settle_table.add_row("[dim]No reports yet[/dim]", "", "", "")

    layout["settlement"].update(Panel(settle_table, border_style="green"))

    # Footer
    footer = Text()
    footer.append("  MQTT: ", style="dim")
    footer.append(f"{MQTT_BROKER}:{MQTT_PORT}", style="bold")
    footer.append(f"  |  Aggregator: {AGGREGATOR_ID}", style="dim")
    footer.append(f"  |  Segment: {SEGMENT_ID}", style="dim")
    footer.append(f"  |  Obligation: {GRID_OBLIGATION_KW:.0f}kW {GRID_OBLIGATION_DIRECTION}", style="dim")
    layout["footer"].update(Panel(footer, style="dim"))

    return layout


def main():
    console = Console()
    state = DemoState()

    # --- Set up MQTT clients ---
    backend_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="demo-backends")
    agg_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="demo-aggregator")

    # --- Create backends ---
    backends: list[HEMSBackend] = []
    for cfg in BACKENDS:
        backends.append(HEMSBackend(cfg, backend_client))

    # --- Create aggregator ---
    agg = Aggregator(agg_client)

    # Wire up dashboard callbacks
    def on_snapshot(snap: SiteStateSnapshot):
        state.log("cyan", f"[observe] {snap.site_id}: net={snap.power.net_kw:+.1f}kW devices={snap.device_count}")

    def on_flex_offer(offer: SiteFlexOffer):
        state.log("cyan", f"[observe] {offer.site_id}: flex down={offer.envelope.flex_down_kw:.0f}kW up={offer.envelope.flex_up_kw:.0f}kW")

    def on_ack(ack: DispatchAck):
        state.log("yellow", f"[dispatch] ACK {ack.site_id}: {ack.status} ({ack.accepted_delta_kw:.0f}kW)")

    def on_status(status: FlexStatus):
        state.log("magenta", f"[execute] {status.site_id}: {status.total_actual_power_kw:.0f}kW active, SoC={status.avg_soc_percent:.0f}%")

    def on_delivery(report: DeliveryReport):
        state.log("green", f"[settle] {report.site_id}: delivered {report.delivery_ratio:.1%}")

    def on_milp(result: dict[str, float]):
        state.milp_result = result
        total = sum(result.values())
        state.log("yellow", f"[plan] MILP solved: {total:.0f}kW across {len(result)} backends")
        for sid, kw in result.items():
            if kw > 0.1:
                state.log("yellow", f"[plan]   {sid}: {kw:.0f}kW")

    agg.on_snapshot = on_snapshot
    agg.on_flex_offer = on_flex_offer
    agg.on_ack = on_ack
    agg.on_status = on_status
    agg.on_delivery = on_delivery
    agg.on_milp_result = on_milp

    # --- Backend MQTT setup ---
    def backend_on_connect(client, userdata, flags, rc, properties):
        dispatch_topic = f"{AGGREGATOR_ID}/dispatch/+/request"
        release_topic = f"{AGGREGATOR_ID}/dispatch/+/release"
        client.subscribe([(dispatch_topic, 1), (release_topic, 1)])
        state.log("dim", "Backends connected to MQTT")

    def backend_on_message(client, userdata, msg):
        import json as _json
        payload = msg.payload.decode()
        if "/dispatch/" in msg.topic and "/request" in msg.topic:
            dispatch = AggregatorDispatch.from_json(payload)
            for b in backends:
                if b.id == dispatch.site_id:
                    b.handle_dispatch(dispatch)
                    state.log("red", f"[dispatch] {b.id}: device MILP → {dispatch.target_delta_kw:.0f}kW distributed")
        elif "/dispatch/" in msg.topic and "/release" in msg.topic:
            data = _json.loads(payload)
            dispatch_id = data.get("dispatch_id", "")
            for b in backends:
                b.handle_release(dispatch_id)

    backend_client.on_connect = backend_on_connect
    backend_client.on_message = backend_on_message

    # --- Aggregator MQTT setup ---
    def agg_on_connect(client, userdata, flags, rc, properties):
        client.subscribe([
            (f"{AGGREGATOR_ID}/observe/+/state", 0),
            (f"{AGGREGATOR_ID}/observe/+/flex", 1),
            (f"{AGGREGATOR_ID}/dispatch/+/ack/+", 1),
            (f"{AGGREGATOR_ID}/dispatch/+/status/+", 0),
            (f"{AGGREGATOR_ID}/settle/+/+", 1),
        ])
        state.log("dim", "Aggregator connected to MQTT")

    def agg_on_message(client, userdata, msg):
        agg.handle_message(msg.topic, msg.payload.decode())

    agg_client.on_connect = agg_on_connect
    agg_client.on_message = agg_on_message

    # --- Connect ---
    backend_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    agg_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    backend_client.loop_start()
    agg_client.loop_start()

    state.log("dim", f"Demo starting — {len(backends)} backends, observation window {OBSERVATION_WINDOW_S}s")

    try:
        with Live(build_dashboard(state, agg), console=console, refresh_per_second=2) as live:

            # === Phase 1: Observe ===
            state.phase = "OBSERVE"
            state.phase_detail = "Backends publishing state + flex offers"
            state.observation_start = time.time()

            last_snapshot = 0.0
            last_flex = 0.0
            last_status = 0.0

            while time.time() - state.observation_start < OBSERVATION_WINDOW_S:
                now = time.time()
                if now - last_snapshot >= 3.0:
                    for b in backends:
                        b.publish_snapshot()
                    last_snapshot = now
                if now - last_flex >= 5.0:
                    for b in backends:
                        b.publish_flex_offer()
                    last_flex = now
                live.update(build_dashboard(state, agg))
                time.sleep(0.5)

            # === Phase 2: Plan ===
            state.phase = "PLAN"
            state.phase_detail = "Running aggregator MILP..."
            live.update(build_dashboard(state, agg))

            summary = agg.portfolio_summary()
            state.log("yellow", f"[plan] Portfolio: {summary['backends_online']} backends, "
                       f"flex_down={summary['total_flex_down_kw']:.0f}kW")
            state.log("red", f"[plan] GRID EVENT: congestion in {SEGMENT_ID} — need {GRID_OBLIGATION_KW:.0f}kW {GRID_OBLIGATION_DIRECTION}")

            allocation = agg.run_milp()
            time.sleep(1)
            live.update(build_dashboard(state, agg))

            # === Phase 3: Dispatch ===
            state.phase = "DISPATCH"
            state.phase_detail = "Sending goals to backends"
            live.update(build_dashboard(state, agg))

            dispatch_id = agg.dispatch(allocation)
            for sid, kw in allocation.items():
                if kw > 0.1:
                    state.log("red", f"[dispatch] → {sid}: {kw:.0f}kW {GRID_OBLIGATION_DIRECTION}")

            time.sleep(2)  # Wait for acks
            live.update(build_dashboard(state, agg))

            # === Phase 3b: Execute ===
            state.phase = "EXECUTE"
            state.phase_detail = "Devices executing flex"
            state.dispatch_start = time.time()

            while time.time() - state.dispatch_start < DISPATCH_DURATION_S:
                now = time.time()
                if now - last_snapshot >= 3.0:
                    for b in backends:
                        b.publish_snapshot()
                    last_snapshot = now
                if now - last_status >= 2.0:
                    for b in backends:
                        b.publish_status()
                    last_status = now
                if now - last_flex >= 5.0:
                    for b in backends:
                        b.publish_flex_offer()
                    last_flex = now
                live.update(build_dashboard(state, agg))
                time.sleep(0.5)

            # === Phase 4: Settle ===
            state.phase = "SETTLE"
            state.phase_detail = "Release + delivery reports"
            live.update(build_dashboard(state, agg))

            agg.release(dispatch_id)
            state.log("green", f"[settle] Release sent for {dispatch_id}")

            time.sleep(3)  # Wait for delivery reports
            live.update(build_dashboard(state, agg))

            # === Done ===
            state.phase = "DONE"
            state.phase_detail = "Full cycle complete"
            state.log("bright_green", "Demo complete — full observe→plan→dispatch→settle cycle")
            live.update(build_dashboard(state, agg))

            # Keep displaying for a bit
            time.sleep(10)

    except KeyboardInterrupt:
        console.print("\n[yellow]Demo interrupted[/yellow]")
        if agg.current_dispatch_id:
            agg.release(agg.current_dispatch_id)
    finally:
        backend_client.loop_stop()
        agg_client.loop_stop()
        backend_client.disconnect()
        agg_client.disconnect()


if __name__ == "__main__":
    main()
