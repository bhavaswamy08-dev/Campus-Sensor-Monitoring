"""Basic automated tests. Run with:  pytest -v"""

import pytest
from fastapi.testclient import TestClient

import database
import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPUS_DB_PATH", str(tmp_path / "test.db"))
    with TestClient(main.app) as c:  # entering the context runs the startup (init_db)
        yield c


def reading(sensor="temp-1", type_="temperature", value=22.0, ts="2026-01-01T10:01:00Z"):
    return {"sensorId": sensor, "type": type_, "value": value, "timestamp": ts}


def make_threshold_rule(client, **overrides):
    body = {"name": "Hot", "sensorType": "temperature", "ruleType": "threshold",
            "operator": "gt", "threshold": 30}
    body.update(overrides)
    resp = client.post("/rules", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------- readings ----------

def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_single_reading(client):
    resp = client.post("/readings", json=reading())
    assert resp.status_code == 201
    body = resp.json()
    assert body["sensorId"] == "temp-1" and body["alertsCreated"] == 0
    assert len(client.get("/readings").json()) == 1


def test_timestamp_is_optional(client):
    resp = client.post("/readings", json={"sensorId": "s1", "type": "occupancy", "value": 10})
    assert resp.status_code == 201


@pytest.mark.parametrize("payload, field", [
    ({"type": "temperature", "value": 1}, "sensorId"),
    ({"sensorId": "s1", "type": "temperature", "value": "hot"}, "value"),
    ({"sensorId": "s1", "type": "temperature", "value": 1, "timestamp": "yesterday-ish"}, "timestamp"),
    ({"sensorId": "s1", "type": "bad type!", "value": 1}, "type"),
    ({"sensorId": "s1", "type": "temperature", "value": 1, "extra": 1}, "extra"),
])
def test_invalid_reading_returns_useful_error(client, payload, field):
    resp = client.post("/readings", json=payload)
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "Validation failed"
    assert any(field in e["location"] for e in body["errors"])


def test_batch_is_all_or_nothing(client):
    bad = {"readings": [reading(), {"sensorId": "s2", "type": "temperature"}]}
    resp = client.post("/readings/batch", json=bad)
    assert resp.status_code == 422
    assert any("readings.1.value" in e["location"] for e in resp.json()["errors"])
    assert client.get("/readings").json() == []


def test_batch_success(client):
    good = {"readings": [reading(value=20), reading(value=21, ts="2026-01-01T10:02:00Z")]}
    resp = client.post("/readings/batch", json=good)
    assert resp.status_code == 201
    assert resp.json()["accepted"] == 2


# ---------- rules ----------

def test_rule_lifecycle(client):
    rule = make_threshold_rule(client)
    rid = rule["id"]
    assert rule["enabled"] is True
    assert len(client.get("/rules").json()) == 1

    edited = client.patch(f"/rules/{rid}", json={"threshold": 35, "name": "Very hot"}).json()
    assert edited["threshold"] == 35 and edited["name"] == "Very hot"

    assert client.post(f"/rules/{rid}/disable").json()["enabled"] is False
    assert client.get("/rules", params={"enabled": True}).json() == []
    assert client.post(f"/rules/{rid}/enable").json()["enabled"] is True


def test_window_rule_requires_window_minutes(client):
    resp = client.post("/rules", json={"name": "x", "sensorType": "temperature",
                                       "ruleType": "window_average", "threshold": 28})
    assert resp.status_code == 422
    assert "windowMinutes" in str(resp.json()["errors"])


def test_patch_that_makes_rule_invalid_is_rejected(client):
    rule = make_threshold_rule(client)
    resp = client.patch(f"/rules/{rule['id']}", json={"ruleType": "window_average"})
    assert resp.status_code == 422
    assert client.get(f"/rules/{rule['id']}").json()["ruleType"] == "threshold"


def test_unknown_rule_404(client):
    assert client.get("/rules/999").status_code == 404
    assert client.post("/rules/999/enable").status_code == 404


# ---------- alerts ----------

def test_threshold_alert_created_only_when_exceeded(client):
    make_threshold_rule(client)
    assert client.post("/readings", json=reading(value=25)).json()["alertsCreated"] == 0
    assert client.post("/readings", json=reading(value=31.5)).json()["alertsCreated"] == 1
    alerts = client.get("/alerts").json()
    assert len(alerts) == 1
    assert alerts[0]["status"] == "open" and alerts[0]["observedValue"] == 31.5


def test_disabled_rule_creates_no_alerts(client):
    rule = make_threshold_rule(client)
    client.post(f"/rules/{rule['id']}/disable")
    assert client.post("/readings", json=reading(value=40)).json()["alertsCreated"] == 0


def test_rule_scoped_to_sensor(client):
    make_threshold_rule(client, sensorId="temp-1")
    assert client.post("/readings", json=reading(sensor="temp-2", value=40)).json()["alertsCreated"] == 0
    assert client.post("/readings", json=reading(sensor="temp-1", value=40)).json()["alertsCreated"] == 1


def test_same_reading_never_alerts_twice(client):
    make_threshold_rule(client)
    rid = client.post("/readings", json=reading(value=40)).json()["id"]
    with database.db_connection() as conn:
        row = conn.execute("SELECT * FROM readings WHERE id = ?", (rid,)).fetchone()
        with database.transaction(conn):
            again = main.evaluate_reading(conn, rid, row["sensor_id"], row["type"], row["value"],
                                          row["timestamp_epoch"], database.utc_now_iso())
    assert again == 0
    assert len(client.get("/alerts").json()) == 1


def test_window_rule_alerts_once_per_window(client):
    client.post("/rules", json={"name": "Avg heat", "sensorType": "temperature",
                                "ruleType": "window_average", "operator": "gt",
                                "threshold": 30, "windowMinutes": 10, "minSamples": 3})
    created = []
    for minute in range(1, 6):  # 10:01 .. 10:05, all inside the same 10-minute window
        resp = client.post("/readings", json=reading(value=33, ts=f"2026-01-01T10:0{minute}:00Z"))
        created.append(resp.json()["alertsCreated"])
    assert created == [0, 0, 1, 0, 0]  # needs 3 samples, then no duplicates
    alerts = client.get("/alerts").json()
    assert len(alerts) == 1 and alerts[0]["observedValue"] == pytest.approx(33)


def test_window_rule_not_triggered_when_average_is_low(client):
    client.post("/rules", json={"name": "Avg heat", "sensorType": "temperature",
                                "ruleType": "window_average", "threshold": 30,
                                "windowMinutes": 10, "minSamples": 2})
    for minute, value in enumerate([20, 21, 50], start=1):  # average is ~30.3 only at the end
        client.post("/readings", json=reading(value=value, ts=f"2026-01-01T10:0{minute}:00Z"))
    # average of 20, 21, 50 = 30.33 -> exceeds 30, so exactly one alert on the last reading
    assert len(client.get("/alerts").json()) == 1


def test_alert_acknowledge_and_resolve_flow(client):
    make_threshold_rule(client)
    client.post("/readings", json=reading(value=40))
    alert_id = client.get("/alerts").json()[0]["id"]

    ack = client.post(f"/alerts/{alert_id}/acknowledge")
    assert ack.status_code == 200 and ack.json()["status"] == "acknowledged"
    assert client.post(f"/alerts/{alert_id}/acknowledge").status_code == 409

    res = client.post(f"/alerts/{alert_id}/resolve")
    assert res.status_code == 200 and res.json()["resolvedAt"] is not None
    assert client.post(f"/alerts/{alert_id}/resolve").status_code == 409
    assert client.get("/alerts", params={"status": "resolved"}).json()[0]["id"] == alert_id


def test_alert_not_found(client):
    assert client.post("/alerts/12345/acknowledge").status_code == 404
    assert client.get("/alerts/12345").status_code == 404