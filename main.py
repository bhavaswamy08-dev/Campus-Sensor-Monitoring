"""Campus Sensor Monitoring and Alerts - FastAPI application."""

import operator
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

import database

# --------------------------------------------------------------------------
# Validation models
# --------------------------------------------------------------------------

SensorId = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:\-]+$")]
SensorType = Annotated[str, Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_\-]+$")]


class CamelModel(BaseModel):
    """JSON uses camelCase (sensorId); Python code uses snake_case."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",  # unknown/misspelled fields produce a clear error
    )


class ReadingIn(CamelModel):
    sensor_id: SensorId
    type: SensorType
    value: float = Field(allow_inf_nan=False)
    timestamp: Optional[datetime] = None  # defaults to "now" when omitted

    @field_validator("type")
    @classmethod
    def lowercase_type(cls, v: str) -> str:
        return v.lower()

    @field_validator("timestamp")
    @classmethod
    def normalise_timestamp(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return v
        if v.tzinfo is None:  # naive timestamps are treated as UTC
            v = v.replace(tzinfo=timezone.utc)
        v = v.astimezone(timezone.utc)
        if v > datetime.now(timezone.utc) + timedelta(minutes=10):
            raise ValueError("timestamp is more than 10 minutes in the future")
        return v


class BatchIn(CamelModel):
    readings: list[ReadingIn] = Field(min_length=1, max_length=1000)


class RuleIn(CamelModel):
    name: str = Field(min_length=1, max_length=100)
    sensor_type: SensorType
    sensor_id: Optional[SensorId] = None
    rule_type: Literal["threshold", "window_average"]
    operator: Literal["gt", "gte", "lt", "lte"] = "gt"
    threshold: float = Field(allow_inf_nan=False)
    window_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    min_samples: int = Field(default=3, ge=1, le=100000)
    severity: Literal["info", "warning", "critical"] = "warning"
    enabled: bool = True

    @field_validator("sensor_type")
    @classmethod
    def lowercase_type(cls, v: str) -> str:
        return v.lower()

    @model_validator(mode="after")
    def check_window_fields(self):
        if self.rule_type == "window_average" and self.window_minutes is None:
            raise ValueError("windowMinutes is required for window_average rules")
        if self.rule_type == "threshold" and self.window_minutes is not None:
            raise ValueError("windowMinutes must not be set for threshold rules")
        return self


class RulePatch(CamelModel):
    """Partial update: only the fields you send are changed."""

    name: Optional[str] = None
    sensor_type: Optional[str] = None
    sensor_id: Optional[str] = None
    rule_type: Optional[str] = None
    operator: Optional[str] = None
    threshold: Optional[float] = None
    window_minutes: Optional[int] = None
    min_samples: Optional[int] = None
    severity: Optional[str] = None
    enabled: Optional[bool] = None


# --------------------------------------------------------------------------
# App setup and error handling
# --------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="Campus Sensor Monitoring and Alerts", version="1.0.0", lifespan=lifespan)


def format_errors(errors) -> list[dict]:
    out = []
    for err in errors:
        location = ".".join(str(part) for part in err["loc"]) or "body"
        message = str(err["msg"]).removeprefix("Value error, ")
        out.append({"location": location, "message": message})
    return out


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": "Validation failed", "errors": format_errors(exc.errors())},
    )


@app.exception_handler(sqlite3.Error)
async def sqlite_handler(_: Request, exc: sqlite3.Error):
    return JSONResponse(
        status_code=503,
        content={"detail": f"Database error, please retry: {exc}"},
    )


# --------------------------------------------------------------------------
# Row -> JSON helpers
# --------------------------------------------------------------------------


def reading_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "sensorId": row["sensor_id"],
        "type": row["type"],
        "value": row["value"],
        "timestamp": row["timestamp"],
    }


def rule_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "sensorType": row["sensor_type"],
        "sensorId": row["sensor_id"],
        "ruleType": row["rule_type"],
        "operator": row["operator"],
        "threshold": row["threshold"],
        "windowMinutes": row["window_minutes"],
        "minSamples": row["min_samples"],
        "severity": row["severity"],
        "enabled": bool(row["enabled"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def alert_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "ruleId": row["rule_id"],
        "readingId": row["reading_id"],
        "sensorId": row["sensor_id"],
        "sensorType": row["sensor_type"],
        "severity": row["severity"],
        "message": row["message"],
        "observedValue": row["observed_value"],
        "status": row["status"],
        "windowStart": row["window_start"],
        "windowEnd": row["window_end"],
        "createdAt": row["created_at"],
        "acknowledgedAt": row["acknowledged_at"],
        "resolvedAt": row["resolved_at"],
    }


# --------------------------------------------------------------------------
# Alert evaluation
# --------------------------------------------------------------------------

OPERATORS = {"gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le}
SYMBOLS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def evaluate_reading(
    conn: sqlite3.Connection,
    reading_id: int,
    sensor_id: str,
    sensor_type: str,
    value: float,
    ts_epoch: float,
    now_iso: str,
) -> int:
    """Check one stored reading against all enabled rules.

    Must be called inside a transaction. Returns how many NEW alerts were created.

    Duplicate prevention (alerts.dedupe_key is UNIQUE, INSERT OR IGNORE):
      * threshold rule:      one alert per (rule, reading)
      * window_average rule: one alert per (rule, sensor, tumbling window bucket)
    """
    rules = conn.execute(
        """SELECT * FROM rules
           WHERE enabled = 1 AND sensor_type = ?
             AND (sensor_id IS NULL OR sensor_id = ?)""",
        (sensor_type, sensor_id),
    ).fetchall()

    created = 0
    for rule in rules:
        compare = OPERATORS[rule["operator"]]
        symbol = SYMBOLS[rule["operator"]]
        window_start = window_end = None

        if rule["rule_type"] == "threshold":
            if not compare(value, rule["threshold"]):
                continue
            dedupe_key = f"rule:{rule['id']}:reading:{reading_id}"
            observed = value
            message = (
                f"{rule['name']}: {sensor_type} reading {value:g} from {sensor_id} "
                f"is {symbol} {rule['threshold']:g}"
            )
        else:  # window_average
            window_seconds = rule["window_minutes"] * 60
            start_epoch = ts_epoch - window_seconds
            stats = conn.execute(
                """SELECT AVG(value) AS avg_value, COUNT(*) AS n FROM readings
                   WHERE sensor_id = ? AND type = ?
                     AND timestamp_epoch > ? AND timestamp_epoch <= ?""",
                (sensor_id, sensor_type, start_epoch, ts_epoch),
            ).fetchone()
            if stats["n"] < rule["min_samples"] or stats["avg_value"] is None:
                continue
            if not compare(stats["avg_value"], rule["threshold"]):
                continue
            bucket = int(ts_epoch // window_seconds)
            dedupe_key = f"rule:{rule['id']}:sensor:{sensor_id}:bucket:{bucket}"
            observed = stats["avg_value"]
            window_start = datetime.fromtimestamp(start_epoch, timezone.utc).isoformat()
            window_end = datetime.fromtimestamp(ts_epoch, timezone.utc).isoformat()
            message = (
                f"{rule['name']}: average {sensor_type} for {sensor_id} over the previous "
                f"{rule['window_minutes']} min is {observed:.2f} ({stats['n']} readings), "
                f"{symbol} {rule['threshold']:g}"
            )

        cur = conn.execute(
            """INSERT OR IGNORE INTO alerts
               (rule_id, reading_id, sensor_id, sensor_type, severity, message,
                observed_value, status, dedupe_key, window_start, window_end, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
            (rule["id"], reading_id, sensor_id, sensor_type, rule["severity"], message,
             observed, dedupe_key, window_start, window_end, now_iso),
        )
        created += cur.rowcount  # 0 when the dedupe_key already existed
    return created


def store_and_evaluate(conn: sqlite3.Connection, items: list[ReadingIn]) -> tuple[list[dict], int]:
    """Insert readings and evaluate rules in ONE transaction (all or nothing)."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    stored = []
    alerts_created = 0

    with database.transaction(conn):
        for item in items:
            ts = item.timestamp or now
            cur = conn.execute(
                """INSERT INTO readings
                   (sensor_id, type, value, timestamp, timestamp_epoch, received_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (item.sensor_id, item.type, item.value, ts.isoformat(), ts.timestamp(), now_iso),
            )
            stored.append({
                "id": cur.lastrowid, "sensorId": item.sensor_id, "type": item.type,
                "value": item.value, "timestamp": ts.isoformat(), "_epoch": ts.timestamp(),
            })
        # Evaluate after all inserts so window averages see the whole batch.
        for r in stored:
            alerts_created += evaluate_reading(
                conn, r["id"], r["sensorId"], r["type"], r["value"], r["_epoch"], now_iso
            )
    for r in stored:
        del r["_epoch"]
    return stored, alerts_created


# --------------------------------------------------------------------------
# Endpoints: health + readings
# --------------------------------------------------------------------------


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/readings", status_code=201)
def create_reading(reading: ReadingIn):
    with database.db_connection() as conn:
        stored, alerts_created = store_and_evaluate(conn, [reading])
    return {**stored[0], "alertsCreated": alerts_created}


@app.post("/readings/batch", status_code=201)
def create_readings_batch(batch: BatchIn):
    """All readings are validated first; if any is invalid nothing is stored."""
    with database.db_connection() as conn:
        stored, alerts_created = store_and_evaluate(conn, batch.readings)
    return {
        "accepted": len(stored),
        "alertsCreated": alerts_created,
        "readingIds": [r["id"] for r in stored],
    }


@app.get("/readings")
def list_readings(
    sensor_id: Optional[str] = Query(None, alias="sensorId"),
    type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
):
    sql = "SELECT * FROM readings WHERE 1=1"
    params: list = []
    if sensor_id:
        sql += " AND sensor_id = ?"
        params.append(sensor_id)
    if type:
        sql += " AND type = ?"
        params.append(type.lower())
    sql += " ORDER BY timestamp_epoch DESC, id DESC LIMIT ?"
    params.append(limit)
    with database.db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [reading_to_dict(r) for r in rows]


# --------------------------------------------------------------------------
# Endpoints: rules
# --------------------------------------------------------------------------

RULE_COLUMNS = (
    "name", "sensor_type", "sensor_id", "rule_type", "operator", "threshold",
    "window_minutes", "min_samples", "severity", "enabled",
)


def get_rule_or_404(conn: sqlite3.Connection, rule_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return row


@app.post("/rules", status_code=201)
def create_rule(rule: RuleIn):
    now = database.utc_now_iso()
    values = [getattr(rule, c) for c in RULE_COLUMNS]
    values[RULE_COLUMNS.index("enabled")] = int(rule.enabled)
    with database.db_connection() as conn:
        with database.transaction(conn):
            cur = conn.execute(
                f"""INSERT INTO rules ({", ".join(RULE_COLUMNS)}, created_at, updated_at)
                    VALUES ({", ".join("?" * len(RULE_COLUMNS))}, ?, ?)""",
                (*values, now, now),
            )
            row = get_rule_or_404(conn, cur.lastrowid)
    return rule_to_dict(row)


@app.get("/rules")
def list_rules(enabled: Optional[bool] = None):
    sql, params = "SELECT * FROM rules", []
    if enabled is not None:
        sql += " WHERE enabled = ?"
        params.append(int(enabled))
    sql += " ORDER BY id"
    with database.db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [rule_to_dict(r) for r in rows]


@app.get("/rules/{rule_id}")
def get_rule(rule_id: int):
    with database.db_connection() as conn:
        return rule_to_dict(get_rule_or_404(conn, rule_id))


@app.patch("/rules/{rule_id}")
def edit_rule(rule_id: int, patch: RulePatch):
    changes = patch.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields to update were provided")

    with database.db_connection() as conn:
        with database.transaction(conn):
            existing = get_rule_or_404(conn, rule_id)
            merged = {c: existing[c] for c in RULE_COLUMNS}
            merged["enabled"] = bool(existing["enabled"])
            merged.update(changes)
            try:
                # Re-validate the merged result with the full rule model.
                rule = RuleIn(**merged)
            except ValidationError as exc:
                errors = [{"loc": ("body", *e["loc"]), "msg": e["msg"]} for e in exc.errors()]
                raise RequestValidationError(errors)

            values = [getattr(rule, c) for c in RULE_COLUMNS]
            values[RULE_COLUMNS.index("enabled")] = int(rule.enabled)
            assignments = ", ".join(f"{c} = ?" for c in RULE_COLUMNS)
            conn.execute(
                f"UPDATE rules SET {assignments}, updated_at = ? WHERE id = ?",
                (*values, database.utc_now_iso(), rule_id),
            )
            row = get_rule_or_404(conn, rule_id)
    return rule_to_dict(row)


def set_rule_enabled(rule_id: int, enabled: bool) -> dict:
    with database.db_connection() as conn:
        with database.transaction(conn):
            get_rule_or_404(conn, rule_id)
            conn.execute(
                "UPDATE rules SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), database.utc_now_iso(), rule_id),
            )
            row = get_rule_or_404(conn, rule_id)
    return rule_to_dict(row)


@app.post("/rules/{rule_id}/enable")
def enable_rule(rule_id: int):
    return set_rule_enabled(rule_id, True)


@app.post("/rules/{rule_id}/disable")
def disable_rule(rule_id: int):
    return set_rule_enabled(rule_id, False)


# --------------------------------------------------------------------------
# Endpoints: alerts
# --------------------------------------------------------------------------


@app.get("/alerts")
def list_alerts(
    status: Optional[Literal["open", "acknowledged", "resolved"]] = None,
    rule_id: Optional[int] = Query(None, alias="ruleId"),
    sensor_id: Optional[str] = Query(None, alias="sensorId"),
    limit: int = Query(100, ge=1, le=1000),
):
    sql = "SELECT * FROM alerts WHERE 1=1"
    params: list = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if rule_id is not None:
        sql += " AND rule_id = ?"
        params.append(rule_id)
    if sensor_id:
        sql += " AND sensor_id = ?"
        params.append(sensor_id)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with database.db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [alert_to_dict(r) for r in rows]


@app.get("/alerts/{alert_id}")
def get_alert(alert_id: int):
    with database.db_connection() as conn:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return alert_to_dict(row)


def change_alert_status(alert_id: int, new_status: str, allowed_from: tuple[str, ...]) -> dict:
    column = "acknowledged_at" if new_status == "acknowledged" else "resolved_at"
    with database.db_connection() as conn:
        with database.transaction(conn):
            row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
            if row["status"] not in allowed_from:
                raise HTTPException(
                    status_code=409,
                    detail=f"Alert {alert_id} is '{row['status']}' and cannot be set to '{new_status}'",
                )
            conn.execute(
                f"UPDATE alerts SET status = ?, {column} = ? WHERE id = ?",
                (new_status, database.utc_now_iso(), alert_id),
            )
            row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    return alert_to_dict(row)


@app.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int):
    return change_alert_status(alert_id, "acknowledged", ("open",))


@app.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int):
    return change_alert_status(alert_id, "resolved", ("open", "acknowledged"))


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000)