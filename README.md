# Campus Sensor Monitoring and Alerts

A backend service that receives campus sensor readings, evaluates alert rules, and allows organizers to manage alerts.

**Technology Stack:** Python 3.14, FastAPI, SQLite, Uvicorn, HTTPX, and Pytest.

## Features

* Accept individual sensor readings and batches.
* Support temperature, air-quality, and occupancy readings.
* Create, edit, enable, and disable alert rules.
* Support single-reading threshold rules.
* Support time-window average rules.
* Automatically generate alerts when rules are triggered.
* List, acknowledge, and resolve alerts.
* Simulate sensor readings for testing.
* Measure request throughput, reading throughput, and latency.

## Project Structure

| File                  | Purpose                                             |
| --------------------- | --------------------------------------------------- |
| `main.py`             | FastAPI application and API endpoints               |
| `database.py`         | SQLite database and schema                          |
| `sensor_simulator.py` | Generates sample sensor readings                    |
| `load_test.py`        | Sends concurrent requests and measures performance  |
| `test_main.py`        | Automated tests                                     |
| `requirements.txt`    | Project dependencies                                |
| `README.md`           | Documentation and instructions                      |
| `LOAD_TEST_REPORT.md` | Detailed load-test results and performance analysis |

## Installation

Install Python 3.14 and open a terminal in the project directory.

Install the dependencies:

```bash
py -3.14 -m pip install -r requirements.txt
```

## Run the Application

Start the server:

```bash
py -3.14 -m uvicorn main:app --reload
```

The application runs at:

* **Base URL:** `http://127.0.0.1:8000`
* **Interactive API documentation:** `http://127.0.0.1:8000/docs`
* **Health check:** `http://127.0.0.1:8000/health`

## API Endpoints

| Method | Endpoint                   | Description                  |
| ------ | -------------------------- | ---------------------------- |
| GET    | `/health`                  | Check application health     |
| POST   | `/readings`                | Submit an individual reading |
| POST   | `/readings/batch`          | Submit a batch of readings   |
| GET    | `/readings`                | Retrieve readings            |
| POST   | `/rules`                   | Create an alert rule         |
| GET    | `/rules`                   | List alert rules             |
| GET    | `/rules/{id}`              | Retrieve a specific rule     |
| PATCH  | `/rules/{id}`              | Edit a rule                  |
| POST   | `/rules/{id}/enable`       | Enable a rule                |
| POST   | `/rules/{id}/disable`      | Disable a rule               |
| GET    | `/alerts`                  | List alerts                  |
| GET    | `/alerts/{id}`             | Retrieve a specific alert    |
| POST   | `/alerts/{id}/acknowledge` | Acknowledge an alert         |
| POST   | `/alerts/{id}/resolve`     | Resolve an alert             |

## Example Sensor Reading

Example JSON for submitting a temperature reading:

```json
{
  "sensorId": "library-floor-2",
  "type": "temperature",
  "value": 34.5,
  "timestamp": "2026-10-19T10:30:00Z"
}
```

Submit the JSON through `POST /readings` in the interactive API documentation.

**Note:** The timestamp and other fields must satisfy the API's validation rules.

## Sensor Simulator

With the server running, open a second terminal and execute:

```bash
py -3.14 sensor_simulator.py
```

The simulator generates sample sensor readings, including abnormal readings that can trigger alerts.

## Automated Tests

Run the test suite:

```bash
py -3.14 -m pytest -v
```

**Observed result:** 22 tests passed, with 1 warning.

The warning concerned deprecated HTTPX integration with Starlette's test client. The tests completed successfully.

## Load Testing

The load-testing script submits sensor readings to the running API and reports elapsed time, successful and failed requests, request throughput, reading throughput, and latency percentiles.

Each test submits 10,000 readings using different request and batch configurations.

### Test 1: Individual Requests

| Metric              |                Result |
| ------------------- | --------------------: |
| Readings submitted  |                10,000 |
| HTTP requests       |                10,000 |
| Successful requests |                10,000 |
| Failed requests     |                     0 |
| Elapsed time        |         66.11 seconds |
| Request throughput  | 151.3 requests/second |
| Reading throughput  | 151.3 readings/second |

### Test 2: Batch Size 100

| Metric              |                  Result |
| ------------------- | ----------------------: |
| Readings submitted  |                  10,000 |
| HTTP requests       |                     100 |
| Successful requests |                     100 |
| Failed requests     |                       0 |
| Batch size          |            100 readings |
| Elapsed time        |            2.48 seconds |
| Request throughput  |    40.3 requests/second |
| Reading throughput  | 4,031.4 readings/second |
| p50 latency         |                291.5 ms |
| p95 latency         |              2,105.7 ms |
| Maximum latency     |              2,470.1 ms |

### Test 3: Batch Size 1,000 — Earlier Run

| Metric                 |                  Result |
| ---------------------- | ----------------------: |
| Readings submitted     |                  10,000 |
| HTTP requests          |                      10 |
| Successful requests    |                      10 |
| Failed requests        |                       0 |
| Batch size             |          1,000 readings |
| Configured concurrency |                      10 |
| Elapsed time           |            1.07 seconds |
| Request throughput     |     9.3 requests/second |
| Reading throughput     | 9,308.8 readings/second |
| p50 latency            |                426.6 ms |
| p95 latency            |                929.6 ms |
| Maximum latency        |              1,066.2 ms |

### Test 4: Batch Size 1,000 — Latest Run

| Metric              |                   Result |
| ------------------- | -----------------------: |
| Readings submitted  |                   10,000 |
| HTTP requests       |                       10 |
| Successful requests |                       10 |
| Failed requests     |                        0 |
| Batch size          |           1,000 readings |
| Elapsed time        |             0.70 seconds |
| Request throughput  |     14.3 requests/second |
| Reading throughput  | 14,268.8 readings/second |
| p50 latency         |                 258.1 ms |
| p95 latency         |                 474.4 ms |
| Maximum latency     |                 688.9 ms |

*The latest run's configured concurrency should be confirmed against the command used to execute it. Results are measurements from individual local test runs and may vary depending on system activity, database state, rule evaluation, and concurrency settings.*

### Performance Analysis

The results demonstrate that batch processing substantially improved measured reading throughput compared with individual requests.

* **Individual requests:** 151.3 readings per second.
* **Batch size 100:** 4,031.4 readings per second.
* **Batch size 1,000 — earlier run:** 9,308.8 readings per second.
* **Batch size 1,000 — latest run:** 14,268.8 readings per second.

In the latest run, all 10,000 readings were accepted in 0.70 seconds through 10 successful HTTP requests, with zero failed requests.

Batch processing reduces HTTP request overhead by submitting multiple readings in each request. However, increasing concurrency does not necessarily improve performance. A separate run using batch size 1,000 and concurrency 20 took 2.24 seconds.

These measurements demonstrate the performance observed in the tested configurations; they are not guarantees of sustained production throughput.

### Run the Load Test

Make sure the FastAPI server is running in a separate terminal.

Run 10,000 individual requests:

```bash
py -3.14 load_test.py
```

Run 10,000 readings in batches of 100:

```bash
py -3.14 load_test.py --batch-size 100
```

Run 10,000 readings in batches of 1,000 with concurrency 10:

```bash
py -3.14 load_test.py --batch-size 1000 --concurrency 10
```

Run 10,000 readings in batches of 1,000 with concurrency 20:

```bash
py -3.14 load_test.py --batch-size 1000 --concurrency 20
```

The measured results may differ between runs.

## Architecture

```text
Sensor Simulator / External Sensor
                |
                v
           HTTP + JSON
                |
                v
          FastAPI Backend
                |
                v
         Input Validation
                |
                v
        Reading Ingestion
                |
                v
          Rule Evaluation
                |
                v
          Alert Generation
                |
                v
          SQLite Database
                |
                v
       Alert Management APIs
```

### Processing Flow

1. The API receives an individual sensor reading or a batch.
2. The backend validates the incoming data.
3. Valid readings are stored in SQLite.
4. Enabled matching alert rules are evaluated.
5. Alerts are created when rule conditions are satisfied.
6. Organizers can view, acknowledge, and resolve alerts.

## Design Trade-offs

**SQLite:** Easy to configure and provides persistent storage. However, concurrent writes can become a bottleneck because SQLite generally allows only one active writer at a time.

**Batch processing:** Reduces the number of HTTP requests needed to submit many readings. The tests showed higher measured reading throughput with batches than with individual requests.

**Synchronous rule evaluation:** Allows alerts to be created during reading ingestion, making the behavior straightforward to understand. However, evaluating rules during ingestion adds processing time.

**Alert deduplication:** Helps prevent repeated alerts for the same rule and deduplication key.

**Scalability:** A production system handling sustained high-volume traffic could use a message queue, background workers, and a database designed for higher concurrent write throughput.

**Reliability:** SQLite provides persistent storage across normal application restarts. Production deployment would also require suitable monitoring, backups, and recovery procedures.

## Limitations and Future Improvements

* The latest load-test run completed in 0.70 seconds for 10,000 readings. However, the script does not explicitly verify that all 10,000 readings arrive within the same one-second arrival window.
* A dedicated burst test is needed to conclusively verify the requirement to handle 10,000 readings arriving within one second.
* SQLite may limit throughput under heavy concurrent write workloads.
* The project does not include authentication.
* Load-test results represent local measurements and may differ on other machines.
* Further improvements could include optimizing database transactions, reducing unnecessary database operations, and performing repeated burst tests under controlled conditions.

## Conclusion

Campus Sensor Monitoring and Alerts demonstrates sensor data ingestion, configurable alert rules, automatic alert generation, alert lifecycle management, automated testing, and performance measurement.

The latest load-test run accepted 10,000 readings in 0.70 seconds, achieving a measured throughput of 14,268.8 readings per second with zero failed requests.

This result is promising, but a dedicated burst test is still required to conclusively demonstrate that the backend can reliably handle 10,000 readings arriving within a one-second window.

For detailed test results and further performance analysis, see [`LOAD_TEST_REPORT.md`](LOAD_TEST_REPORT.md).
