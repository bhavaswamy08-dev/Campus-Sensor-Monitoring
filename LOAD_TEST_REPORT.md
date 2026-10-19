# Campus Sensor Monitoring and Alerts

## Load-Test Report

### 1. Objective

The objective of this test is to evaluate the performance and reliability of the Campus Sensor Monitoring and Alerts backend when processing 10,000 sensor readings. The tests compare individual HTTP requests with batch processing.

### 2. Testing Environment

* **Backend framework:** FastAPI
* **Database:** SQLite
* **HTTP client:** HTTPX
* **Load-testing script:** `load_test.py`
* **Total readings per test:** 10,000

### 3. Test Results

| Metric                 | Individual Requests | Batch Size 100 | Batch Size 1,000 |
| ---------------------- | ------------------: | -------------: | ---------------: |
| Total readings         |              10,000 |         10,000 |           10,000 |
| HTTP requests          |              10,000 |            100 |               10 |
| Configured concurrency |                  50 |             50 |               10 |
| Elapsed time           |             66.11 s |         2.48 s |           1.07 s |
| Reading throughput     |             151.3/s |      4,031.4/s |        9,308.8/s |
| Successful requests    |              10,000 |            100 |               10 |
| Failed requests        |                   0 |              0 |                0 |
| p50 latency            |            183.2 ms |       291.5 ms |         426.6 ms |
| p95 latency            |          1,090.1 ms |     2,105.7 ms |         929.6 ms |
| Maximum latency        |          5,174.7 ms |     2,470.1 ms |       1,066.2 ms |

*These measurements are from individual test runs on the development environment. Results may vary between runs.*

### 4. Performance Analysis

The tests show that batch processing significantly improved the measured throughput.

* Individual requests achieved 151.3 readings per second.
* Batches of 100 achieved 4,031.4 readings per second.
* Batches of 1,000 achieved 9,308.8 readings per second.

In the best observed run, all 10,000 readings were accepted in 1.07 seconds, with no failed requests.

Batching reduces HTTP request overhead by sending multiple readings in a single request. However, increasing concurrency does not always improve performance. A subsequent test using a batch size of 1,000 and configured concurrency of 20 took 2.24 seconds.

### 5. Reliability Observations

All 10,000 readings were accepted in each of the three reported test runs, with zero failed requests.

These results demonstrate successful ingestion during the tested runs, but do not guarantee reliability under every workload or sustained production conditions.

### 6. Architecture and Trade-offs

The backend uses FastAPI to expose REST API endpoints and SQLite for persistent storage.

* **Individual requests:** Simple to handle but incur HTTP overhead for each reading.
* **Batch processing:** Reduces request overhead and improves measured throughput.
* **Larger batches:** Can improve throughput but may increase the processing time of individual requests.
* **Concurrency:** More concurrent workers do not necessarily improve performance and may introduce additional overhead.
* **SQLite:** Provides simple persistent storage but may experience write contention under heavier concurrent workloads.

### 7. Limitations and Future Improvements

The requirement specifies handling a burst of 10,000 readings in one second. The best observed test took 1.07 seconds, so the current results do not demonstrate that the requirement has been met.

The load-testing script measures the duration of concurrent submissions but does not explicitly verify that all 10,000 readings arrive within the same one-second interval.

Future improvements include optimizing database transactions, reducing unnecessary database operations, and implementing a dedicated burst test that measures ingestion performance over a defined one-second arrival window.

### 8. Conclusion

Batch processing substantially improved the measured throughput of the Campus Sensor Monitoring and Alerts backend. The best observed configuration accepted all 10,000 readings in 1.07 seconds, achieving 9,308.8 readings per second with no failed requests.

Further optimization and dedicated burst testing are required to demonstrate the target of 10,000 readings in one second.
