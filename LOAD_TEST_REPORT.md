# Campus Sensor Monitoring and Alerts

## Load-Test Report

### 1. Objective

The objective of this test is to evaluate the performance and reliability of the Campus Sensor Monitoring and Alerts backend when processing 10,000 sensor readings. The tests compare individual HTTP requests with batch processing to measure the effect of batch size on throughput, latency, and reliability.

### 2. Testing Environment

* **Backend framework:** FastAPI
* **Database:** SQLite
* **HTTP client:** HTTPX
* **Load-testing script:** `load_test.py`
* **Total readings per test:** 10,000

### 3. Test Results

| Metric                 | Individual Requests | Batch Size 100 | Batch Size 1,000 — Run 1 | Batch Size 1,000 — Latest Run |
| ---------------------- | ------------------: | -------------: | -----------------------: | ----------------------------: |
| Total readings         |              10,000 |         10,000 |                   10,000 |                        10,000 |
| HTTP requests          |              10,000 |            100 |                       10 |                            10 |
| Configured concurrency |                  50 |             50 |                       10 |                           10* |
| Elapsed time           |             66.11 s |         2.48 s |                   1.07 s |                        0.70 s |
| Request throughput     |             151.3/s |         40.3/s |                    9.3/s |                        14.3/s |
| Reading throughput     |             151.3/s |      4,031.4/s |                9,308.8/s |                    14,268.8/s |
| Successful requests    |              10,000 |            100 |                       10 |                            10 |
| Failed requests        |                   0 |              0 |                        0 |                             0 |
| p50 latency            |            183.2 ms |       291.5 ms |                 426.6 ms |                      258.1 ms |
| p95 latency            |          1,090.1 ms |     2,105.7 ms |                 929.6 ms |                      474.4 ms |
| Maximum latency        |          5,174.7 ms |     2,470.1 ms |               1,066.2 ms |                      688.9 ms |

*The latest run is assumed to use concurrency 10 based on the earlier batch-size-1,000 configuration. Confirm this against the command used for the latest run.

**Note:** These measurements come from individual test runs in the development environment. Performance may vary with system activity, database state, and workload.

### 4. Performance Analysis

The results show that batch processing substantially improved the measured reading throughput.

* **Individual requests:** Processed 10,000 readings in 66.11 seconds, achieving 151.3 readings per second.
* **Batch size 100:** Processed 10,000 readings in 2.48 seconds, achieving 4,031.4 readings per second.
* **Batch size 1,000 — Run 1:** Processed 10,000 readings in 1.07 seconds, achieving 9,308.8 readings per second.
* **Batch size 1,000 — Latest run:** Processed 10,000 readings in 0.70 seconds, achieving 14,268.8 readings per second.

In the latest observed run, all 10,000 readings were accepted through 10 successful HTTP requests, with zero failed requests. The measured p95 latency was 474.4 ms.

Batching reduces HTTP request overhead by sending multiple readings in one request. However, the results also show that increasing concurrency does not necessarily improve performance. A separate test using a batch size of 1,000 and concurrency 20 took 2.24 seconds, demonstrating that system conditions and concurrency settings can affect results.

### 5. Reliability Observations

All readings were accepted with zero failed requests in the reported test runs.

This demonstrates successful ingestion during these specific tests. However, a small number of successful runs does not guarantee reliability under every workload or sustained production conditions.

### 6. Architecture and Trade-offs

The backend uses FastAPI to expose REST API endpoints and SQLite for persistent storage.

* **Individual requests:** Simple to process, but each reading incurs HTTP request overhead.
* **Batch processing:** Reduces the number of HTTP requests and improves measured throughput.
* **Larger batches:** Can improve throughput but may increase the processing time of individual requests.
* **Concurrency:** More concurrent workers do not necessarily improve performance and may introduce additional overhead.
* **SQLite:** Provides straightforward persistent storage but can experience write contention under heavier concurrent workloads.

### 7. Limitations and Future Improvements

The target requirement is to handle a burst of 10,000 readings within one second.

The latest load-test run completed in 0.70 seconds, with all 10,000 readings accepted and zero failed requests. This is a promising result and is within the one-second duration target for the measured test.

However, the load-testing script measures the duration of concurrent submissions. It does not explicitly verify that all 10,000 readings arrive within the same one-second arrival window under a controlled burst workload. Therefore, the result alone does not conclusively establish that the burst requirement has been met.

Future improvements include:

* Optimizing database transactions and reducing unnecessary database operations.
* Repeating the test under consistent conditions to evaluate performance stability.
* Implementing a dedicated burst test with a defined one-second arrival window.
* Measuring ingestion completion time, accepted readings, failed readings, and latency during the burst.

### 8. Conclusion

Batch processing significantly improved the measured throughput of the Campus Sensor Monitoring and Alerts backend.

The best observed run accepted all 10,000 readings in 0.70 seconds, achieving a measured throughput of 14,268.8 readings per second with 10 successful requests and zero failures.

This result meets the one-second duration target for that particular load-test run. However, a dedicated burst test is still needed to conclusively verify that the system can reliably handle 10,000 readings arriving within a one-second window.

