"""Send many sensor readings concurrently and report measured results.

Examples:
    python load_test.py                                   # 10,000 single POST /readings
    python load_test.py --concurrency 100
    python load_test.py --batch-size 100                  # 100 POST /readings/batch calls

Tip: point the server at a throwaway database so test data does not mix with real data:
    CAMPUS_DB_PATH=load_test.db uvicorn main:app
"""

import argparse
import asyncio
import random
import sys
import time
from datetime import datetime, timezone

import httpx


def build_reading(rng: random.Random, anomaly_rate: float) -> dict:
    kind = rng.choice(["temperature", "air_quality", "occupancy"])
    sensor = f"load-{kind}-{rng.randint(1, 50):02d}"
    if kind == "temperature":
        value = rng.gauss(22, 2)
        if rng.random() < anomaly_rate:
            value = rng.uniform(31, 38)
    elif kind == "air_quality":
        value = max(0.0, rng.gauss(40, 8))
        if rng.random() < anomaly_rate:
            value = rng.uniform(160, 220)
    else:
        value = rng.randint(5, 60)
    return {
        "sensorId": sensor,
        "type": kind,
        "value": round(value, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def worker(client, queue, endpoint, results):
    while True:
        try:
            payload, size = queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        started = time.perf_counter()
        try:
            resp = await client.post(endpoint, json=payload)
            ok = resp.status_code == 201
            if not ok:
                results["errors"][f"HTTP {resp.status_code}"] = results["errors"].get(f"HTTP {resp.status_code}", 0) + 1
        except httpx.HTTPError as exc:
            ok = False
            name = type(exc).__name__
            results["errors"][name] = results["errors"].get(name, 0) + 1
        results["latencies"].append(time.perf_counter() - started)
        if ok:
            results["ok_requests"] += 1
            results["ok_readings"] += size
        else:
            results["failed_requests"] += 1
            results["failed_readings"] += size


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    return sorted_values[int(pct * (len(sorted_values) - 1))]


async def run(args) -> int:
    rng = random.Random(args.seed)
    readings = [build_reading(rng, args.anomaly_rate) for _ in range(args.total)]

    if args.batch_size > 1:
        endpoint = "/readings/batch"
        chunks = [readings[i:i + args.batch_size] for i in range(0, len(readings), args.batch_size)]
        work = [({"readings": chunk}, len(chunk)) for chunk in chunks]
    else:
        endpoint = "/readings"
        work = [(r, 1) for r in readings]

    queue: asyncio.Queue = asyncio.Queue()
    for item in work:
        queue.put_nowait(item)

    results = {"ok_requests": 0, "failed_requests": 0, "ok_readings": 0,
               "failed_readings": 0, "latencies": [], "errors": {}}
    limits = httpx.Limits(max_connections=args.concurrency,
                          max_keepalive_connections=args.concurrency)

    async with httpx.AsyncClient(base_url=args.url, limits=limits, timeout=30.0) as client:
        try:
            (await client.get("/health")).raise_for_status()
        except httpx.HTTPError as exc:
            print(f"Cannot reach the server at {args.url}: {exc}", file=sys.stderr)
            return 2

        print(f"Sending {args.total} readings to {endpoint} "
              f"({len(work)} requests, concurrency {args.concurrency})...")
        start = time.perf_counter()
        await asyncio.gather(*(worker(client, queue, endpoint, results)
                               for _ in range(args.concurrency)))
        elapsed = time.perf_counter() - start

    lat = sorted(results["latencies"])
    total_requests = results["ok_requests"] + results["failed_requests"]
    print("\n--- Load test results (measured on this run) ---")
    print(f"Elapsed time:        {elapsed:.2f} s")
    print(f"Requests:            {total_requests} "
          f"(successful: {results['ok_requests']}, failed: {results['failed_requests']})")
    print(f"Readings accepted:   {results['ok_readings']} of {args.total}")
    print(f"Request throughput:  {total_requests / elapsed:.1f} requests/s")
    print(f"Reading throughput:  {results['ok_readings'] / elapsed:.1f} readings/s (accepted only)")
    if lat:
        print(f"Latency p50 / p95 / max: {percentile(lat, 0.5) * 1000:.1f} / "
              f"{percentile(lat, 0.95) * 1000:.1f} / {lat[-1] * 1000:.1f} ms")
    if results["errors"]:
        print(f"Error breakdown:     {results['errors']}")
    return 0 if results["failed_requests"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--total", type=int, default=10_000)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=1,
                        help="1 = one request per reading; >1 uses /readings/batch (max 1000)")
    parser.add_argument("--anomaly-rate", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1000:
        parser.error("--batch-size must be between 1 and 1000")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())