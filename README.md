# Campus Sensor Monitoring and Alerts

A small, beginner-friendly backend that receives campus sensor readings
(temperature, air quality, occupancy), evaluates them against alert rules, and
lets organizers manage the resulting alerts.

Built with Python 3.14, FastAPI, SQLite (standard library `sqlite3`), Uvicorn and Pytest.

## Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app: validation, endpoints, rule evaluation |
| `database.py` | SQLite connection, transaction helper, schema |
| `sensor_simulator.py` | Generates realistic readings, including alert-triggering ones |
| `load_test.py` | Concurrent load generator that measures real results |
| `test_main.py` | Automated tests |
| `requirements.txt` | Dependencies |

## Setup

```bash
python3.14 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Start the server

```bash
uvicorn main:app --reload
```

The server runs at http://127.0.0.1:8000. Interactive docs are at `/docs`.
The database file `campus_sensors.db` is created automatically. Set a different
path with the `CAMPUS_DB_PATH` environment variable.

## Run the tests

```bash
pytest -v
```

Tests use a temporary database, so they never touch your real data.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check |
| POST | `/readings` | Submit one reading |
| POST | `/readings/batch` | Submit 1-1000 readings (all-or-nothing) |
| GET | `/readings?sensorId=&type=&limit=` | List recent readings |
| POST | `/rules` | Create a rule |
| GET | `/rules?enabled=true` | List rules |
| GET | `/rules/{id}` | Get one rule |
| PATCH | `/rules/{id}` | Edit a rule (partial update) |
| POST | `/rules/{id}/enable` | Enable a rule |
| POST | `/rules/{id}/disable` | Disable a rule |
| GET | `/alerts?status=&ruleId=&sensorId=&limit=` | List alerts |
| GET | `/alerts/{id}` | Get one alert |
| POST | `/alerts/{id}/acknowledge` | open -> acknowledged |
| POST | `/alerts/{id}/resolve` | open/acknowledged -> resolved |

## Example requests

Submit a reading (`timestamp` is ISO 8601; optional, defaults to now; naive times are treated as UTC):

```bash
curl -X POST http://127.0.0.1:8000/readings -H "Content-Type: application/json" \
  -d '{"sensorId":"temp-hall-3","type":"temperature","value":31.4,"timestamp":"2026-01-01T10:05:00Z"}'
```

Submit a batch:

```bash
curl -X POST http://127.0.0.1:8000/readings/batch -H "Content-Type: application/json" \
  -d '{"readings":[
        {"sensorId":"temp-1","type":"temperature","value":22.5},
        {"sensorId":"aq-1","type":"air_quality","value":48}]}'
```

Create a single-reading threshold rule (temperature > 30):

```bash
curl -X POST http://127.0.0.1:8000/rules -H "Content-Type: application/json" \
  -d '{"name":"High temperature","sensorType":"temperature","ruleType":"threshold",
       "operator":"gt","threshold":30,"severity":"critical"}'
```

Create a time-window rule (average temperature > 28 over the previous 10 minutes,
needing at least 3 readings):

```bash
curl -X POST http://127.0.0.1:8000/rules -H "Content-Type: application/json" \
  -d '{"name":"Sustained heat","sensorType":"temperature","ruleType":"window_average",
       "operator":"gt","threshold":28,"windowMinutes":10,"minSamples":3}'
```

Rule fields: `name`, `sensorType`, `sensorId` (optional; omit to apply to every sensor of that type),
`ruleType` (`threshold` | `window_average`), `operator` (`gt`, `gte`, `lt`, `lte`), `threshold`,
`windowMinutes` (required only for window rules), `minSamples` (default 3), `severity`
(`info` | `warning` | `critical`), `enabled`.

Edit, disable, enable:

```bash
curl -X PATCH http://127.0.0.1:8000/rules/1 -H "Content-Type: application/json" -d '{"threshold":32}'
curl -X POST http://127.0.0.1:8000/rules/1/disable
curl -X POST http://127.0.0.1:8000/rules/1/enable
```

Work with alerts:

```bash
curl "http://127.0.0.1:8000/alerts?status=open"
curl -X POST http://127.0.0.1:8000/alerts/1/acknowledge
curl -X POST http://127.0.0.1:8000/alerts/1/resolve
```

Validation errors return HTTP 422, for example:

```json
{"detail": "Validation failed",
 "errors": [{"location": "body.value", "message": "Input should be a valid number, unable to parse string as a number"}]}
```

## Sensor simulator

With the server running, in a second terminal:

```bash
python sensor_simulator.py                 # creates sample rules, sends 30 rounds with anomalies
python sensor_simulator.py --no-anomalies  # normal readings only
python sensor_simulator.py --help
```

It simulates 3 temperature sensors, 2 air-quality sensors and 2 occupancy sensors.
Unless `--no-anomalies` is set it includes a one-off temperature spike, a sustained
heat wave on one sensor, an air-quality event and a room exceeding capacity.
Then check `GET /alerts`.

## Performance testing

Use a throwaway database so test data does not pollute your real one:

```bash
CAMPUS_DB_PATH=load_test.db uvicorn main:app          # terminal 1 (no --reload)
python load_test.py                                   # terminal 2: 10,000 single requests
python load_test.py --concurrency 100                 # more parallel connections
python load_test.py --batch-size 100                  # 100 batch requests of 100 readings
```

The script prints elapsed time, successful and failed requests, accepted readings,
throughput and latency percentiles. **All numbers come from your own run;
this README intentionally contains no benchmark results.** Results depend on your
hardware, disk, Python version and the number of enabled rules. The script exits
with a non-zero code if any request fails.

## Architecture

```
sensor / simulator / load_test
          |  HTTP + JSON
          v
   FastAPI (main.py)  --- Pydantic validation (camelCase JSON, clear 422 errors)
          |
          v
   one transaction per request (database.py)
     1. insert reading(s)
     2. load enabled matching rules
     3. evaluate each rule
     4. INSERT OR IGNORE alerts (UNIQUE dedupe_key)
          |
          v
   SQLite file (WAL mode): readings, rules, alerts
```

Tables: `readings`, `rules`, `alerts`. Indexes cover reading lookups by
(sensor, type, time), rules by (enabled, type) and alerts by status.

**Alert rules**

* `threshold`: fires when a single reading satisfies the comparison.
* `window_average`: after each reading, averages that sensor's readings of the
  same type in the previous N minutes (up to the new reading's timestamp) and fires
  if the average satisfies the comparison and at least `minSamples` readings exist.

**Duplicate prevention**

* Threshold alerts: key = rule + reading id.
* Window alerts: key = rule + sensor + fixed time bucket (epoch / window length),
  so a sensor produces at most one alert per rule per window bucket.
* The database enforces this with a `UNIQUE` column, so it also holds under concurrent requests.

**Alert lifecycle**: `open` -> `acknowledged` -> `resolved`. Invalid transitions return 409.

## Design trade-offs

* **SQLite**: zero setup and durable, but only one writer at a time. WAL mode,
  `BEGIN IMMEDIATE` and a busy timeout make concurrent requests queue politely.
  For many writes per second or multiple servers, switch to PostgreSQL or a
  time-series database.
* **Synchronous evaluation on ingest**: alerts are available as soon as the request
  returns and logic stays easy to follow, but each request does extra reads and
  writes. A queue plus background worker would raise throughput at the cost of complexity.
* **Tumbling-window dedupe**: simple and deterministic, but a sustained problem that
  crosses a bucket boundary produces a second alert, and an alert that was resolved
  will not re-fire in the same bucket.
* **Batch is all-or-nothing**: one bad item rejects the whole batch (clear errors, no
  partial state). The alternative, partial acceptance, is friendlier for flaky
  devices but harder to reason about.
* **No backfill**: a newly created or re-enabled rule only evaluates readings that
  arrive afterwards.
* **No authentication**: fine for a learning project, but add API keys or OAuth
  before exposing it on a real network.
* **A new SQLite connection per request**: simple and thread-safe; a connection
  pool would be slightly faster.
* **Readings are never deleted or compacted**: add a retention job for long-running deployments.