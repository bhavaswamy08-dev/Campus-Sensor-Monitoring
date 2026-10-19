"""Generate realistic campus sensor data and send it to the API.

Examples:
    python sensor_simulator.py                       # 30 rounds, 1 s apart, with anomalies
    python sensor_simulator.py --rounds 60 --interval 0.5
    python sensor_simulator.py --no-anomalies        # normal data only
"""

import argparse
import math
import random
import sys
import time
from datetime import datetime, timezone

import httpx

TEMP_SENSORS = ["temp-library-1", "temp-lab-2", "temp-hall-3"]
AIR_SENSORS = ["aq-cafeteria-1", "aq-lab-2"]
OCCUPANCY_CAPACITY = {"occ-lecture-hall-A": 120, "occ-library-floor-2": 80}

SAMPLE_RULES = [
    {"name": "High temperature (single reading)", "sensorType": "temperature",
     "ruleType": "threshold", "operator": "gt", "threshold": 30, "severity": "critical"},
    {"name": "Sustained heat (10 min average)", "sensorType": "temperature",
     "ruleType": "window_average", "operator": "gt", "threshold": 28,
     "windowMinutes": 10, "minSamples": 3, "severity": "warning"},
    {"name": "Poor air quality", "sensorType": "air_quality",
     "ruleType": "threshold", "operator": "gt", "threshold": 150, "severity": "warning"},
    {"name": "Lecture hall over capacity", "sensorType": "occupancy",
     "sensorId": "occ-lecture-hall-A", "ruleType": "threshold", "operator": "gt",
     "threshold": 120, "severity": "critical"},
    {"name": "Library floor 2 over capacity", "sensorType": "occupancy",
     "sensorId": "occ-library-floor-2", "ruleType": "threshold", "operator": "gt",
     "threshold": 80, "severity": "warning"},
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_round(round_no: int, total: int, rng: random.Random, anomalies: bool) -> list[dict]:
    readings = []
    heat_wave = anomalies and int(total * 0.4) <= round_no < int(total * 0.7)
    air_event = anomalies and round_no >= int(total * 0.75)
    overcrowd = anomalies and round_no in (int(total * 0.5), int(total * 0.5) + 1)

    for sensor in TEMP_SENSORS:  # degrees Celsius
        value = 22 + 2 * math.sin(round_no / 8) + rng.gauss(0, 0.4)
        if heat_wave and sensor == "temp-hall-3":
            value = 31.5 + rng.gauss(0, 0.8)           # sustained heat
        if anomalies and sensor == "temp-lab-2" and round_no == 5:
            value = 35.0                                # one-off spike
        readings.append({"sensorId": sensor, "type": "temperature",
                         "value": round(value, 2), "timestamp": now_iso()})

    for sensor in AIR_SENSORS:  # air quality index
        value = max(0.0, 40 + rng.gauss(0, 6))
        if air_event and sensor == "aq-lab-2":
            value = 165 + rng.gauss(0, 10)
        readings.append({"sensorId": sensor, "type": "air_quality",
                         "value": round(value, 1), "timestamp": now_iso()})

    for sensor, capacity in OCCUPANCY_CAPACITY.items():  # people in the room
        value = round(capacity * rng.uniform(0.3, 0.6))
        if overcrowd and sensor == "occ-lecture-hall-A":
            value = capacity + 8
        readings.append({"sensorId": sensor, "type": "occupancy",
                         "value": value, "timestamp": now_iso()})
    return readings


def create_sample_rules(client: httpx.Client) -> None:
    existing = {r["name"] for r in client.get("/rules").json()}
    for rule in SAMPLE_RULES:
        if rule["name"] in existing:
            continue
        resp = client.post("/rules", json=rule)
        status = "created" if resp.status_code == 201 else f"FAILED ({resp.text})"
        print(f"  rule '{rule['name']}': {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between rounds")
    parser.add_argument("--mode", choices=["batch", "single"], default="batch")
    parser.add_argument("--no-anomalies", action="store_true")
    parser.add_argument("--no-rules", action="store_true", help="do not create sample rules")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    with httpx.Client(base_url=args.url, timeout=10.0) as client:
        try:
            client.get("/health").raise_for_status()
        except httpx.HTTPError as exc:
            print(f"Cannot reach the server at {args.url}: {exc}", file=sys.stderr)
            return 2

        if not args.no_rules:
            print("Ensuring sample alert rules exist...")
            create_sample_rules(client)

        total_alerts = 0
        for round_no in range(args.rounds):
            readings = generate_round(round_no, args.rounds, rng, not args.no_anomalies)
            if args.mode == "batch":
                resp = client.post("/readings/batch", json={"readings": readings})
                if resp.status_code != 201:
                    print(f"round {round_no}: error {resp.status_code} {resp.text}", file=sys.stderr)
                    continue
                new_alerts = resp.json()["alertsCreated"]
            else:
                new_alerts = 0
                for reading in readings:
                    resp = client.post("/readings", json=reading)
                    if resp.status_code != 201:
                        print(f"round {round_no}: error {resp.status_code} {resp.text}", file=sys.stderr)
                        continue
                    new_alerts += resp.json()["alertsCreated"]
            total_alerts += new_alerts
            print(f"round {round_no + 1}/{args.rounds}: sent {len(readings)} readings, "
                  f"{new_alerts} new alert(s)")
            time.sleep(args.interval)

    print(f"Done. {total_alerts} alert(s) created. View them at {args.url}/alerts")
    return 0


if __name__ == "__main__":
    sys.exit(main())