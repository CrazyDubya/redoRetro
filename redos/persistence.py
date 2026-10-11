"""Durable snapshots and idempotent command execution for the canonical World.

Snapshots are local application data, not a network interchange format. The
SQLite row contains a checksummed pickle of the in-memory World so every
existing dataclass, tuple, datetime, seeded RNG, and runtime registry survives
without introducing a second persistence-shaped object graph. Loading verifies
the checksum and world invariants before returning the snapshot.
"""

from __future__ import annotations

from collections.abc import Callable
import copy
from dataclasses import dataclass
import hashlib
import pickle
import sqlite3
from pathlib import Path
from typing import Any, TypeVar

from .audit import validate_world
from .model import World


SNAPSHOT_SCHEMA_VERSION = 1
_T = TypeVar("_T")


@dataclass(frozen=True)
class SnapshotInfo:
    snapshot_id: str
    schema_version: int
    created_at: str
    checksum: str
    event_count: int


def _connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS world_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            checksum TEXT NOT NULL,
            event_count INTEGER NOT NULL,
            payload BLOB NOT NULL
        )
        """
    )


def save_snapshot(world: World, path: str | Path, *, snapshot_id: str = "latest") -> SnapshotInfo:
    """Atomically replace one named local snapshot and return its metadata."""
    if not snapshot_id:
        raise ValueError("snapshot_id must not be empty")
    errors = validate_world(world)
    if errors:
        raise ValueError(f"cannot snapshot invalid world: {errors[:3]}")
    payload = pickle.dumps(world, protocol=pickle.HIGHEST_PROTOCOL)
    checksum = hashlib.sha256(payload).hexdigest()
    info = SnapshotInfo(
        snapshot_id=snapshot_id,
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        created_at=world.now.isoformat(),
        checksum=checksum,
        event_count=len(world.events),
    )
    connection = _connect(path)
    try:
        with connection:
            _ensure_schema(connection)
            connection.execute(
                """
                INSERT INTO world_snapshots
                    (snapshot_id, schema_version, created_at, checksum, event_count, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    created_at = excluded.created_at,
                    checksum = excluded.checksum,
                    event_count = excluded.event_count,
                    payload = excluded.payload
                """,
                (info.snapshot_id, info.schema_version, info.created_at, info.checksum, info.event_count, payload),
            )
    finally:
        connection.close()
    return info


def load_snapshot(path: str | Path, *, snapshot_id: str = "latest") -> World:
    """Load and validate one named local snapshot."""
    connection = _connect(path)
    try:
        row = connection.execute(
            "SELECT schema_version, checksum, payload FROM world_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise KeyError(f"snapshot {snapshot_id!r} not found")
    if row["schema_version"] != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(f"unsupported snapshot schema {row['schema_version']}")
    payload = bytes(row["payload"])
    if hashlib.sha256(payload).hexdigest() != row["checksum"]:
        raise ValueError(f"snapshot {snapshot_id!r} failed checksum validation")
    world = pickle.loads(payload)
    if not isinstance(world, World):
        raise TypeError("snapshot payload is not a World")
    errors = validate_world(world)
    if errors:
        raise ValueError(f"snapshot contains invalid world: {errors[:3]}")
    return world


def execute_once(
    world: World,
    command_id: str,
    operation: Callable[..., _T],
    *args: Any,
    **kwargs: Any,
) -> _T:
    """Execute a command once, returning the original result on retry.

    The command ledger is ordinary canonical runtime state and therefore is
    included in snapshots. Reusing an ID for a different operation is rejected
    instead of silently turning an idempotency key into a general cache.
    """
    if not command_id:
        raise ValueError("command_id must not be empty")
    ledger = world.runtime.setdefault("command_ledger", {})
    operation_name = f"{operation.__module__}.{operation.__qualname__}"
    existing = ledger.get(command_id)
    if existing is not None:
        if existing["operation"] != operation_name:
            raise ValueError(f"command ID {command_id!r} was already used for {existing['operation']}")
        return copy.deepcopy(existing["result"])
    result = operation(*args, **kwargs)
    ledger[command_id] = {"operation": operation_name, "result": copy.deepcopy(result)}
    world.record(
        "command_executed",
        f"executed idempotent command {command_id}",
        entities=[command_id],
        data={"operation": operation_name},
    )
    return result
