#!/usr/bin/env python3
"""Grid-Serving Storage Demo — Orchestrator.

Runs the full four-phase loop with clear sequential terminal output:
  Phase 1: Observe  — backends publish state + flex offers
  Phase 2: Plan     — aggregator runs MILP
  Phase 3: Dispatch — aggregator sends goals, backends distribute to devices
  Phase 4: Settle   — delivery reports, reliability scoring
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from config import (
    AGGREGATOR_ID, BACKENDS, DISPATCH_DURATION_S, GRID_OBLIGATION_DIRECTION,
    GRID_OBLIGATION_KW, MQTT_BROKER, MQTT_PORT, OBSERVATION_WINDOW_S,
    SEGMENT_ID, STATUS_INTERVAL_S,
)
from aggregator import Aggregator
from backend_simulator import HEMSBackend
from models import (
    AggregatorDispatch, DeliveryReport, DispatchAck, FlexStatus,
    SiteFlexOffer, SiteStateSnapshot,
)

console = Console()


def phase_header(number: int, name: str, description: str):
    """Print a prominent phase header."""
    console.print()
    console.rule(f"[bold]Phase {number}: {name}[/bold]", style="bright_blue")
    console.print(f"  [dim]{description}[/dim]")
    console.print()


def timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def main():
    # ---------------------------------------------------------------
    # Title
    # ---------------------------------------------------------------
    console.print()
    console.print(Panel(
        "[bold white]Grid-Serving Storage Demo[/bold white]\n"
        "[dim]Four-phase interoperability profile: Observe → Plan → Dispatch → Settle\n"
        f"MQTT broker: {MQTT_BROKER}:{MQTT_PORT}  |  Aggregator: {AGGREGATOR_ID}  |  Segment: {SEGMENT_ID}\n"
        f"Grid obligation: {GRID_OBLIGATION_KW:.0f} kW {GRID_OBLIGATION_DIRECTION}[/dim]",
        style="blue",
        expand=True,
    ))

    # ---------------------------------------------------------------
    # Setup: MQTT clients, backends, aggregator
    # ---------------------------------------------------------------
    backend_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="demo-backends")
    agg_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="demo-aggregator")

    backends: list[HEMSBackend] = []
    for cfg in BACKENDS:
        backends.append(HEMSBackend(cfg, backend_client))

    agg = Aggregator(agg_client)

    # Backend MQTT wiring
    def backend_on_connect(client, userdata, flags, rc, properties):
        client.subscribe([
            (f"{AGGREGATOR_ID}/dispatch/+/request", 1),
            (f"{AGGREGATOR_ID}/dispatch/+/release", 1),
        ])

    def backend_on_message(client, userdata, msg):
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

    backend_client.on_connect = backend_on_connect
    backend_client.on_message = backend_on_message

    # Aggregator MQTT wiring
    def agg_on_connect(client, userdata, flags, rc, properties):
        client.subscribe([
            (f"{AGGREGATOR_ID}/observe/+/state", 0),
            (f"{AGGREGATOR_ID}/observe/+/flex", 1),
            (f"{AGGREGATOR_ID}/dispatch/+/ack/+", 1),
            (f"{AGGREGATOR_ID}/dispatch/+/status/+", 0),
            (f"{AGGREGATOR_ID}/settle/+/+", 1),
        ])

    def agg_on_message(client, userdata, msg):
        agg.handle_message(msg.topic, msg.payload.decode())

    agg_client.on_connect = agg_on_connect
    agg_client.on_message = agg_on_message

    # Connect
    backend_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    agg_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    backend_client.loop_start()
    agg_client.loop_start()
    time.sleep(1)  # Let connections establish

    console.print(f"  [green]Connected to MQTT broker[/green]")
    console.print(f"  [dim]Backends: {', '.join(b.id for b in backends)} ({sum(len(b.devices) for b in backends)} devices total)[/dim]")

    try:
        # ===========================================================
        # PHASE 1: OBSERVE
        # ===========================================================
        phase_header(1, "OBSERVE", "HEMS Backends publish state and flexibility offers to the Aggregator (bottom-up)")

        console.print(f"  [dim]Backends will publish SiteStateSnapshot + SiteFlexOffer every few seconds.[/dim]")
        console.print(f"  [dim]The Aggregator receives and builds its portfolio model.[/dim]")
        console.print(f"  [dim]Observing for {OBSERVATION_WINDOW_S:.0f}s...[/dim]")
        console.print()

        observation_start = time.time()
        last_snapshot = 0.0
        last_flex = 0.0
        snap_count = 0

        with console.status("[cyan]Observing portfolio...[/cyan]") as status:
            while time.time() - observation_start < OBSERVATION_WINDOW_S:
                now = time.time()
                remaining = OBSERVATION_WINDOW_S - (now - observation_start)
                status.update(f"[cyan]Observing portfolio... {remaining:.0f}s remaining[/cyan]")

                if now - last_snapshot >= 3.0:
                    for b in backends:
                        b.publish_snapshot()
                    last_snapshot = now
                    snap_count += 1

                if now - last_flex >= 5.0:
                    for b in backends:
                        b.publish_flex_offer()
                    last_flex = now

                time.sleep(0.5)

        console.print(f"  [green]Observation complete[/green] — {snap_count} snapshot cycles received\n")

        # Show portfolio table
        portfolio = Table(
            title="Portfolio State (as seen by Aggregator)",
            box=box.ROUNDED, expand=True, show_lines=True,
        )
        portfolio.add_column("Backend", style="bold")
        portfolio.add_column("Type", style="dim")
        portfolio.add_column("Devices", justify="right")
        portfolio.add_column("Net Power", justify="right")
        portfolio.add_column("Flex Down (kW)", justify="right", style="red")
        portfolio.add_column("Flex Up (kW)", justify="right", style="green")
        portfolio.add_column("Confidence", justify="right")
        portfolio.add_column("Reliability", justify="right")

        total_down = 0.0
        total_up = 0.0
        for b in backends:
            snap = agg.snapshots.get(b.id)
            offer = agg.flex_offers.get(b.id)
            if not offer:
                continue
            devices = str(snap.device_count) if snap else "?"
            net = f"{snap.power.net_kw:+.1f} kW" if snap else "?"
            total_down += offer.envelope.flex_down_kw
            total_up += offer.envelope.flex_up_kw
            portfolio.add_row(
                b.id,
                b.cfg["device_type"],
                devices,
                net,
                f"{offer.envelope.flex_down_kw:.0f}",
                f"{offer.envelope.flex_up_kw:.0f}",
                f"{offer.envelope.confidence:.0%}",
                f"{offer.reliability.score:.0%}",
            )

        portfolio.add_row(
            "[bold]TOTAL[/bold]", "", "", "",
            f"[bold red]{total_down:.0f}[/bold red]",
            f"[bold green]{total_up:.0f}[/bold green]",
            "", "",
        )
        console.print(portfolio)

        summary = agg.portfolio_summary()
        can_meet = "[green]YES[/green]" if summary["can_meet"] else "[red]NO[/red]"
        console.print(f"\n  Obligation: {GRID_OBLIGATION_KW:.0f} kW {GRID_OBLIGATION_DIRECTION}")
        console.print(f"  Available (confidence-weighted): {summary['total_flex_down_kw']:.0f} kW down / {summary['total_flex_up_kw']:.0f} kW up")
        console.print(f"  Can meet obligation: {can_meet}")

        # ===========================================================
        # PHASE 2: PLAN
        # ===========================================================
        phase_header(2, "PLAN", "Aggregator runs portfolio-level MILP to allocate grid obligation across backends")

        console.print(f"  [yellow]GRID EVENT:[/yellow] Congestion detected in segment [bold]{SEGMENT_ID}[/bold]")
        console.print(f"  [yellow]Obligation:[/yellow] Reduce {GRID_OBLIGATION_KW:.0f} kW in this segment")
        console.print()
        console.print("  [dim]Running MILP optimizer (PuLP + HiGHS)...[/dim]")
        console.print("  [dim]  Objective: meet obligation, minimize dispatch to unreliable backends[/dim]")
        console.print("  [dim]  Constraints: per-backend flex bounds, confidence-weighted capacity[/dim]")
        console.print()

        allocation = agg.run_milp()

        # Show MILP result
        milp_table = Table(
            title="MILP Result: Dispatch Allocation",
            box=box.ROUNDED, expand=True,
        )
        milp_table.add_column("Backend", style="bold")
        milp_table.add_column("Allocated (kW)", justify="right", style="yellow")
        milp_table.add_column("Available (kW)", justify="right", style="dim")
        milp_table.add_column("Reliability", justify="right")
        milp_table.add_column("Dispatched?", justify="center")

        total_alloc = 0.0
        for sid, kw in allocation.items():
            offer = agg.flex_offers.get(sid)
            available = offer.envelope.flex_down_kw if offer else 0
            rel = f"{offer.reliability.score:.0%}" if offer else "?"
            dispatched = "[green]YES[/green]" if kw > 0.1 else "[dim]no[/dim]"
            total_alloc += kw
            milp_table.add_row(sid, f"{kw:.0f}", f"{available:.0f}", rel, dispatched)

        milp_table.add_row(
            "[bold]TOTAL[/bold]",
            f"[bold]{total_alloc:.0f} / {GRID_OBLIGATION_KW:.0f} target[/bold]",
            "", "", "",
        )
        console.print(milp_table)

        # ===========================================================
        # PHASE 3: DISPATCH
        # ===========================================================
        phase_header(3, "DISPATCH", "Aggregator sends goals to backends. Each backend runs device-level MILP and distributes to HEMS devices")

        console.print("  [bold]Step 1:[/bold] Aggregator publishes AggregatorDispatch per backend via MQTT")
        dispatch_id = agg.dispatch(allocation)

        for sid, kw in allocation.items():
            if kw > 0.1:
                console.print(f"    [yellow]MQTT →[/yellow] {sid}: {kw:.0f} kW {GRID_OBLIGATION_DIRECTION}  [dim](topic: {AGGREGATOR_ID}/dispatch/{SEGMENT_ID}/request)[/dim]")

        console.print()
        console.print("  [bold]Step 2:[/bold] Each backend runs its own MILP to distribute across devices")
        console.print("  [dim]  (Backend MILP respects per-device SoC, battery limits, ramp rates, prosumer preferences)[/dim]")
        console.print()

        time.sleep(2)  # Wait for acks

        console.print("  [bold]Step 3:[/bold] Backends simulate OpenADR events to devices and publish DispatchAck")
        console.print()

        # Show acks
        ack_table = Table(
            title="Dispatch Acknowledgments",
            box=box.ROUNDED, expand=True,
        )
        ack_table.add_column("Backend", style="bold")
        ack_table.add_column("Status", justify="center")
        ack_table.add_column("Accepted (kW)", justify="right")
        ack_table.add_column("Requested (kW)", justify="right", style="dim")
        ack_table.add_column("Detail", style="dim")

        for sid, ack in agg.acks.items():
            if ack.status == "accepted":
                status = "[green]ACCEPTED[/green]"
            elif ack.status == "partially_accepted":
                status = "[yellow]PARTIAL[/yellow]"
            else:
                status = "[red]REJECTED[/red]"
            requested = allocation.get(sid, 0)
            detail = ack.rejection_reason or "all devices opted in"
            ack_table.add_row(sid, status, f"{ack.accepted_delta_kw:.0f}", f"{requested:.0f}", detail)

        console.print(ack_table)

        # ===========================================================
        # PHASE 3b: EXECUTE
        # ===========================================================
        console.print()
        console.rule("[bold]Executing...[/bold]", style="magenta")
        console.print(f"  [dim]Devices are now executing the flex. Backends publish periodic FlexStatus via MQTT.[/dim]")
        console.print(f"  [dim]Duration: {DISPATCH_DURATION_S:.0f}s (real-world: 15–120 minutes)[/dim]")
        console.print()

        dispatch_start = time.time()
        last_snapshot = 0.0
        last_status = 0.0
        last_flex = 0.0
        status_count = 0

        with console.status("[magenta]Devices executing flex...[/magenta]") as spinner:
            while time.time() - dispatch_start < DISPATCH_DURATION_S:
                now = time.time()
                remaining = DISPATCH_DURATION_S - (now - dispatch_start)
                spinner.update(f"[magenta]Devices executing flex... {remaining:.0f}s remaining[/magenta]")

                if now - last_snapshot >= 3.0:
                    for b in backends:
                        b.publish_snapshot()
                    last_snapshot = now

                if now - last_status >= STATUS_INTERVAL_S:
                    for b in backends:
                        b.publish_status()
                    last_status = now
                    status_count += 1

                if now - last_flex >= 5.0:
                    for b in backends:
                        b.publish_flex_offer()
                    last_flex = now

                time.sleep(0.5)

        # Show final execution status
        exec_table = Table(
            title=f"Execution Summary ({status_count} status updates received)",
            box=box.ROUNDED, expand=True,
        )
        exec_table.add_column("Backend", style="bold")
        exec_table.add_column("Active Devices", justify="right")
        exec_table.add_column("Actual Power (kW)", justify="right", style="magenta")
        exec_table.add_column("Avg SoC", justify="right")

        for sid, status in agg.statuses.items():
            exec_table.add_row(
                sid,
                str(status.active_devices),
                f"{status.total_actual_power_kw:.0f}",
                f"{status.avg_soc_percent:.0f}%",
            )

        console.print(exec_table)

        # ===========================================================
        # PHASE 4: SETTLE
        # ===========================================================
        phase_header(4, "SETTLE", "Aggregator releases dispatch. Backends generate delivery reports for settlement")

        console.print("  [bold]Step 1:[/bold] Aggregator publishes FlexRelease")
        agg.release(dispatch_id)
        console.print(f"    [green]MQTT →[/green] FlexRelease for {dispatch_id}")
        console.print()

        console.print("  [bold]Step 2:[/bold] Backends generate DeliveryReport (requested vs. delivered)")
        time.sleep(3)  # Wait for delivery reports
        console.print()

        # Show delivery reports
        settle_table = Table(
            title="Settlement: Delivery Reports",
            box=box.ROUNDED, expand=True, show_lines=True,
        )
        settle_table.add_column("Backend", style="bold")
        settle_table.add_column("Requested (kWh)", justify="right")
        settle_table.add_column("Delivered (kWh)", justify="right")
        settle_table.add_column("Delivery Ratio", justify="right")
        settle_table.add_column("Rebound (kWh)", justify="right", style="dim")
        settle_table.add_column("Baseline Method", style="dim")

        total_req = 0.0
        total_del = 0.0
        for sid, report in agg.delivery_reports.items():
            ratio_style = "green" if report.delivery_ratio >= 0.9 else "yellow" if report.delivery_ratio >= 0.7 else "red"
            settle_table.add_row(
                sid,
                f"{report.total_requested_kwh:.2f}",
                f"{report.total_delivered_kwh:.2f}",
                f"[{ratio_style}]{report.delivery_ratio:.1%}[/{ratio_style}]",
                f"{report.rebound_kwh:.2f}",
                report.baseline_method,
            )
            total_req += report.total_requested_kwh
            total_del += report.total_delivered_kwh

        if total_req > 0:
            overall_ratio = total_del / total_req
            ratio_style = "green" if overall_ratio >= 0.9 else "yellow"
            settle_table.add_row(
                "[bold]TOTAL[/bold]",
                f"[bold]{total_req:.2f}[/bold]",
                f"[bold]{total_del:.2f}[/bold]",
                f"[bold {ratio_style}]{overall_ratio:.1%}[/bold {ratio_style}]",
                "", "",
            )

        console.print(settle_table)

        # ===========================================================
        # DECISION STATE ACROSS ENTITIES
        # ===========================================================
        console.print()
        console.rule("[bold]Decision State Across Entities[/bold]", style="bright_blue")
        console.print()
        console.print("  [dim]What each entity knew, decided, and the impact at each phase:[/dim]")
        console.print()

        # Per-entity decision trace
        for b in backends:
            offer = agg.flex_offers.get(b.id)
            ack = agg.acks.get(b.id)
            status = agg.statuses.get(b.id)
            report = agg.delivery_reports.get(b.id)
            alloc_kw = allocation.get(b.id, 0)

            if not offer:
                continue

            was_dispatched = alloc_kw > 0.1

            entity_table = Table(
                title=f"{b.id} ({b.cfg['name']}  —  {b.cfg['device_count']} devices, {b.cfg['device_type']})",
                box=box.ROUNDED, expand=True, show_header=False,
                title_style="bold",
            )
            entity_table.add_column("Phase", style="bold", width=20)
            entity_table.add_column("What it knew / decided", ratio=2)
            entity_table.add_column("Impact", ratio=1)

            # Observe
            entity_table.add_row(
                "[cyan]1. Observe[/cyan]",
                f"Reported: flex_down={offer.envelope.flex_down_kw:.0f}kW, "
                f"flex_up={offer.envelope.flex_up_kw:.0f}kW\n"
                f"Confidence: {offer.envelope.confidence:.0%}, "
                f"Reliability: {offer.reliability.score:.0%}\n"
                f"Constraints: ramp {offer.constraints.ramp_rate_up_kw_per_h:.0f}kW/h, "
                f"min duration {offer.constraints.min_activation_duration_min}min",
                f"Aggregator sees this\n"
                f"backend as a {offer.envelope.flex_down_kw * offer.envelope.confidence:.0f}kW\n"
                f"firm-capacity resource",
            )

            # Plan
            if was_dispatched:
                plan_decision = (
                    f"[yellow]Aggregator allocated {alloc_kw:.0f}kW[/yellow] "
                    f"(of {offer.envelope.flex_down_kw:.0f}kW available)\n"
                    f"Reason: reliability={offer.reliability.score:.0%} "
                    f"(higher = more dispatch)"
                )
                plan_impact = (
                    f"Will receive dispatch\n"
                    f"goal for {alloc_kw:.0f}kW"
                )
            else:
                plan_decision = (
                    f"[dim]Aggregator allocated 0kW[/dim]\n"
                    f"Skipped: reliability={offer.reliability.score:.0%} "
                    f"(MILP preferred other backends)"
                )
                plan_impact = "[dim]No dispatch sent[/dim]"

            entity_table.add_row("[yellow]2. Plan[/yellow]", plan_decision, plan_impact)

            # Dispatch
            if was_dispatched and ack:
                accepted_pct = ack.accepted_delta_kw / alloc_kw * 100 if alloc_kw > 0 else 0
                dispatch_decision = (
                    f"Received: {alloc_kw:.0f}kW {GRID_OBLIGATION_DIRECTION}\n"
                    f"Backend MILP distributed across {b.cfg['device_count']} devices\n"
                    f"Result: [green]{ack.status}[/green] — {ack.accepted_delta_kw:.0f}kW "
                    f"({accepted_pct:.0f}% of requested)\n"
                    f"OpenADR: oadrDistributeEvent → each device, optIn/optOut"
                )
                dispatch_impact = (
                    f"Devices adjust\n"
                    f"charge/discharge\n"
                    f"setpoints"
                )
            elif was_dispatched:
                dispatch_decision = f"Received {alloc_kw:.0f}kW but no ACK received"
                dispatch_impact = "Unknown"
            else:
                dispatch_decision = "[dim]Not dispatched[/dim]"
                dispatch_impact = "[dim]Normal operation[/dim]"

            entity_table.add_row("[red]3. Dispatch[/red]", dispatch_decision, dispatch_impact)

            # Execute
            if status:
                exec_decision = (
                    f"Active: {status.active_devices} devices executing flex\n"
                    f"Delivering: {status.total_actual_power_kw:.0f}kW actual\n"
                    f"Avg SoC drifting: {status.avg_soc_percent:.0f}%"
                )
                exec_impact = (
                    f"Grid relief:\n"
                    f"{status.total_actual_power_kw:.0f}kW from\n"
                    f"this backend"
                )
            else:
                exec_decision = "[dim]No active dispatch[/dim]"
                exec_impact = "[dim]No grid relief[/dim]"

            entity_table.add_row("[magenta]   Execute[/magenta]", exec_decision, exec_impact)

            # Settle
            if report:
                ratio_style = "green" if report.delivery_ratio >= 0.9 else "yellow"
                settle_decision = (
                    f"Requested: {report.total_requested_kwh:.2f}kWh\n"
                    f"Delivered: {report.total_delivered_kwh:.2f}kWh\n"
                    f"Ratio: [{ratio_style}]{report.delivery_ratio:.1%}[/{ratio_style}]\n"
                    f"Rebound: {report.rebound_kwh:.2f}kWh expected"
                )
                settle_impact = (
                    f"Reliability score\n"
                    f"updated for future\n"
                    f"MILP planning"
                )
            else:
                settle_decision = "[dim]No delivery report (not dispatched)[/dim]"
                settle_impact = "[dim]No score update[/dim]"

            entity_table.add_row("[green]4. Settle[/green]", settle_decision, settle_impact)

            console.print(entity_table)
            console.print()

        # Conclusions / Takeaways
        dispatched_backends = [sid for sid, kw in allocation.items() if kw > 0.1]
        skipped_backends = [sid for sid, kw in allocation.items() if kw <= 0.1]

        console.rule("[bold]Conclusions & Takeaways[/bold]", style="bright_green")
        console.print()

        conclusions = Table(box=box.SIMPLE, show_header=False, expand=True, padding=(0, 2))
        conclusions.add_column("", width=3)
        conclusions.add_column("")

        conclusions.add_row(
            "[bold green]1[/bold green]",
            f"[bold]Two-level MILP works:[/bold] Aggregator allocated {total_alloc:.0f}/{GRID_OBLIGATION_KW:.0f}kW "
            f"across {len(dispatched_backends)} of {len(allocation)} backends. "
            f"Each backend independently distributed to its devices.",
        )
        conclusions.add_row(
            "[bold green]2[/bold green]",
            f"[bold]Reliability-weighted dispatch:[/bold] The MILP preferred backends with higher "
            f"reliability scores. "
            + (f"[dim]{', '.join(skipped_backends)}[/dim] was skipped despite having capacity "
               f"— its lower reliability score made it less attractive." if skipped_backends else
               "All backends were dispatched."),
        )
        conclusions.add_row(
            "[bold green]3[/bold green]",
            f"[bold]Prosumer sovereignty preserved:[/bold] Devices decided locally via OpenADR optIn/optOut. "
            f"The aggregator requested {total_alloc:.0f}kW but backends accepted "
            f"{sum(a.accepted_delta_kw for a in agg.acks.values()):.0f}kW — devices at SoC limits opted out.",
        )
        conclusions.add_row(
            "[bold green]4[/bold green]",
            f"[bold]Delivery verified:[/bold] Overall delivery ratio "
            f"{'[green]' if overall_ratio >= 0.9 else '[yellow]'}{overall_ratio:.1%}"
            f"{'[/green]' if overall_ratio >= 0.9 else '[/yellow]'}. "
            f"This feeds back into reliability scores for future MILP cycles.",
        )
        conclusions.add_row(
            "[bold green]5[/bold green]",
            f"[bold]Privacy maintained:[/bold] The aggregator never saw per-device data. "
            f"It only received backend-level aggregates "
            f"(SiteFlexOffer envelopes, DispatchAck totals, DeliveryReport summaries).",
        )
        console.print(conclusions)

        # ===========================================================
        # DONE
        # ===========================================================
        console.print()
        console.rule("[bold bright_green]Demo Complete[/bold bright_green]", style="green")
        console.print()
        console.print(Panel(
            "[bold]Full cycle completed: Observe → Plan → Dispatch → Settle[/bold]\n\n"
            f"  Backends observed:    {len(agg.flex_offers)}\n"
            f"  MILP allocation:      {total_alloc:.0f} kW across {sum(1 for v in allocation.values() if v > 0.1)} backends\n"
            f"  Devices activated:    {sum(s.active_devices for s in agg.statuses.values())}\n"
            f"  Energy delivered:     {total_del:.2f} / {total_req:.2f} kWh\n"
            f"  Overall delivery:     {overall_ratio:.1%}\n\n"
            "[dim]The aggregator MILP optimized across backends (portfolio level).\n"
            "Each backend MILP optimized across its devices (device level).\n"
            "OpenADR device interactions were simulated in-process.[/dim]",
            title="Summary",
            style="green",
            expand=True,
        ))

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
