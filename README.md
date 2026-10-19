# Campus Sensor Monitoring and Alerts

A backend service that receives campus sensor readings, evaluates alert rules, and allows organizers to manage alerts.

**Technology stack:** Python 3.14, FastAPI, SQLite, Uvicorn, and Pytest.

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

| File                  | Purpose                                            |
| --------------------- | -------------------------------------------------- |
| `main.py`             | FastAPI application and API endpoints              |
| `database.py`         | SQLite database and schema                         |
| `sensor_simulator.py` | Generates sample sensor readings                   |
| `load_test.py`        | Sends concurrent requests and measures performance |
| `test_main.py`        | Automated tests                                    |
| `requirements.txt`    | Project dependencies                               |
| `README.md`           | Documentation and instructions                     |

## Installation

Install Python and open a terminal in the project directory.

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

`http://127.0.0.1:8000`

Interactive API documentation:

`http://127.0.0.1:8000/docs`

Health check:

`http://127.0.0.1:8000/health`

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

```json
{
  "sensorId": "library-floor-2",
  "type": "temperature",
  "value": 34.5,
  "timestamp": "2026-10-19T10:30:00Z"
}
```

Submit the JSON through `POST /readings` in the interactive API documentation.

**Note:** The timestamp must satisfy the API's validation rules.

## Sensor Simulator

With the server running, open a second terminal and execute:

```bash
py -3.14 sensor_simulator.py
```

The simulator generates sensor readings, including abnormal readings that can trigger alerts.

## Automated Tests

Run the test suite:

```bash
py -3.14 -m pytest -v
```

**Observed result:** 22 tests passed, with 1 warning.

The warning concerned the deprecated `httpx` integration with Starlette's test client. The tests completed successfully.

## Load Testing

The load-testing script sends sensor readings to the running API and reports elapsed time, accepted readings, request throughput, reading throughput, and latency percentiles.

### Test 1: Individual Requests

| Metric              |                Result |
| ------------------- | --------------------: |
| Readings submitted  |                10,000 |
| Successful requests |                10,000 |
| Failed requests     |                     0 |
| Elapsed time        |         66.11 seconds |
| Request throughput  | 151.3 requests/second |
| Reading throughput  | 151.3 readings/second |

### Test 2: Batch Requests

| Metric              |                  Result |
| ------------------- | ----------------------: |
| Readings submitted  |                  10,000 |
| Successful requests |                     100 |
| Failed requests     |                       0 |
| Batch size          |            100 readings |
| Elapsed time        |            2.48 seconds |
| Request throughput  |    40.3 requests/second |
| Reading throughput  | 4,031.4 readings/second |

### Test 3: Larger Batches

| Metric              |                  Result |
| ------------------- | ----------------------: |
| Readings submitted  |                  10,000 |
| Successful requests |                      10 |
| Failed requests     |                       0 |
| Batch size          |          1,000 readings |
| Elapsed time        |            2.24 seconds |
| Request throughput  |     4.5 requests/second |
| Reading throughput  | 4,457.8 readings/second |

**Interpretation:** All three tests accepted 10,000 readings without failed requests. Batch processing improved reading throughput substantially compared with individual requests.

However, these tests did not demonstrate that the system can process 10,000 readings in one second. Further optimization and testing are needed to establish that performance target.

Results depend on hardware, database state, rule evaluation, and concurrency settings. These are measurements from local test runs, not guaranteed production performance.

### Run the Load Test

Run 10,000 individual requests:

```bash
py -3.14 load_test.py
```

Run 10,000 readings in batches of 100:

```bash
py -3.14 load_test.py --batch-size 100
```

Run 10,000 readings in batches of 1,000:

```bash
py -3.14 load_test.py --batch-size 1000 --concurrency 20
```

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

1. The API receives a sensor reading or batch.
2. The backend validates the incoming data.
3. Valid readings are stored in SQLite.
4. Enabled matching alert rules are evaluated.
5. Alerts are created when rule conditions are satisfied.
6. Organizers can view, acknowledge, and resolve alerts.

## Design Trade-offs

**SQLite:** Easy to configure and provides persistent storage. However, concurrent writes can become a bottleneck because SQLite allows only one writer at a time.

**Batch processing:** Reduces the number of HTTP requests required to submit many readings. The tests showed higher reading throughput with batches than with individual requests.

**Synchronous rule evaluation:** Alerts can be created during reading ingestion, making the behavior straightforward to understand. However, evaluating rules during ingestion adds processing time.

**Alert deduplication:** Prevents repeated alerts for the same rule and deduplication key.

**Scalability:** A production system handling sustained high-volume traffic could use a message queue, background workers, and a database designed for higher concurrent write throughput.

**Reliability:** Persistent SQLite storage retains application data across normal application restarts. Additional monitoring, backups, and recovery procedures would be needed for production deployment.

## Limitations

* The tested implementation has not demonstrated 10,000 readings per second.
* SQLite may limit throughput under heavy concurrent write workloads.
* The project does not include authentication.
* The load-test results represent local measurements and may differ on other machines.

## Conclusion

Campus Sensor Monitoring and Alerts demonstrates sensor data ingestion, configurable alert rules, automatic alert generation, alert lifecycle management, automated testing, and performance measurement.

The load tests show that batching improves throughput, while also identifying performance limitations that would need to be addressed for a high-volume deployment.
