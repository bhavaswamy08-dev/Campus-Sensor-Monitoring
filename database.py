"""SQLite helpers: connections, transactions and schema creation."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DEFAULT_DB_PATH = "campus_sensors.db"


def get_db_path() -> str:
    # Read on every call so tests can point to a temporary database.
    return os.environ.get("CAMPUS_DB_PATH", DEFAULT_DB_PATH)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    """Open a new connection.

    isolation_level=None puts the sqlite3 module in autocommit mode so we
    control transactions explicitly with BEGIN / COMMIT (see transaction()).
    """
    conn = sqlite3.connect(get_db_path(), timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def db_connection():
    """Yield a connection and always close it."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection):
    """Run a block inside one write transaction.

    BEGIN IMMEDIATE takes the write lock up front, which avoids "database is
    locked" errors caused by upgrading a read lock to a write lock midway.
    Any exception rolls everything back.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id       TEXT NOT NULL,
    type            TEXT NOT NULL,
    value           REAL NOT NULL,
    timestamp       TEXT NOT NULL,          -- ISO 8601, UTC
    timestamp_epoch REAL NOT NULL,          -- same instant, for fast range queries
    received_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_readings_lookup
    ON readings (sensor_id, type, timestamp_epoch);

CREATE TABLE IF NOT EXISTS rules (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    sensor_type    TEXT NOT NULL,
    sensor_id      TEXT,                    -- NULL = applies to every sensor of this type
    rule_type      TEXT NOT NULL CHECK (rule_type IN ('threshold', 'window_average')),
    operator       TEXT NOT NULL CHECK (operator IN ('gt', 'gte', 'lt', 'lte')),
    threshold      REAL NOT NULL,
    window_minutes INTEGER,
    min_samples    INTEGER NOT NULL DEFAULT 1,
    severity       TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    enabled        INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rules_enabled ON rules (enabled, sensor_type);

CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id         INTEGER NOT NULL REFERENCES rules (id),
    reading_id      INTEGER REFERENCES readings (id),
    sensor_id       TEXT NOT NULL,
    sensor_type     TEXT NOT NULL,
    severity        TEXT NOT NULL,
    message         TEXT NOT NULL,
    observed_value  REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'acknowledged', 'resolved')),
    dedupe_key      TEXT NOT NULL UNIQUE,   -- guarantees no duplicate alerts
    window_start    TEXT,
    window_end      TEXT,
    created_at      TEXT NOT NULL,
    acknowledged_at TEXT,
    resolved_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts (status, id);
"""


def init_db() -> None:
    """Create tables and indexes if they do not exist yet."""
    with db_connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer
        conn.executescript(SCHEMA)