"""Shared configuration for the grid-serving storage demo."""

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
AGGREGATOR_ID = "agg-01"
SEGMENT_ID = "seg-LA-0142"

# Demo timing (accelerated for demo — real system would be 60s+)
SNAPSHOT_INTERVAL_S = 3.0
FLEX_OFFER_INTERVAL_S = 5.0
STATUS_INTERVAL_S = 2.0
OBSERVATION_WINDOW_S = 15.0  # How long to observe before triggering dispatch
DISPATCH_DURATION_S = 20.0   # How long a dispatch event lasts in demo

# Energy profile scaling (adjusts PV output and consumption levels)
#   PV_SCALE:   1.0 = full rated output, 0.4 = overcast/autumn, 0.15 = winter
#   CONS_SCALE: 1.0 = baseline, 1.3 = autumn (heating), 1.6 = winter (heavy heating)
PV_SCALE = 0.4
CONS_SCALE = 1.3

# Simulated grid obligation
GRID_OBLIGATION_KW = 200.0   # "Reduce 200 kW in segment"
GRID_OBLIGATION_DIRECTION = "down"
GRID_OBLIGATION_REASON = "congestion"

# MQTT topic patterns
TOPIC_STATE = "{agg_id}/observe/{backend_id}/state"
TOPIC_FLEX = "{agg_id}/observe/{backend_id}/flex"
TOPIC_DISPATCH = "{agg_id}/dispatch/{segment_id}/request"
TOPIC_ACK = "{agg_id}/dispatch/{segment_id}/ack/{backend_id}"
TOPIC_STATUS = "{agg_id}/dispatch/{segment_id}/status/{backend_id}"
TOPIC_RELEASE = "{agg_id}/dispatch/{segment_id}/release"
TOPIC_SETTLE = "{agg_id}/settle/{backend_id}/{dispatch_id}"
TOPIC_COMMAND = "{agg_id}/command/{action}"
TOPIC_AGG_STATE = "{agg_id}/state/portfolio"

# Backend configurations — realistic Austrian HEMS portfolios
BACKENDS = [
    {
        "id": "kern-01",
        "name": "KERN Residential",
        "device_count": 47,
        "device_type": "residential",
        "avg_battery_kw": 5.0,
        "avg_battery_kwh": 10.0,
        "has_pv": True,
        "avg_pv_kw": 8.0,
    },
    {
        "id": "solar-02",
        "name": "Solar Commercial",
        "device_count": 12,
        "device_type": "commercial",
        "avg_battery_kw": 25.0,
        "avg_battery_kwh": 50.0,
        "has_pv": True,
        "avg_pv_kw": 40.0,
    },
    {
        "id": "flex-03",
        "name": "FlexPower Mixed",
        "device_count": 25,
        "device_type": "mixed",
        "avg_battery_kw": 8.0,
        "avg_battery_kwh": 15.0,
        "has_pv": True,
        "avg_pv_kw": 12.0,
    },
]
