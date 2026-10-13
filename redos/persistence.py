"""Safe, versioned SQLite snapshots and idempotent command execution.

The snapshot payload is an explicit JSON graph. It contains only primitive
values, collections, an allowlisted set of canonical model dataclasses, and
the state of the world's seeded ``random.Random`` instance. Loading never
executes code from the database.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, time
import copy
import hashlib
import json
import random
import sqlite3
from pathlib import Path
from typing import Any, TypeVar

from . import model as model_module
from .audit import validate_world
from .living import Recipe
from .market import TradeQuote
from .model import World


SNAPSHOT_SCHEMA_VERSION = 3
_T = TypeVar("_T")
_MODEL_TYPES = {
    cls.__name__: cls
    for cls in vars(model_module).values()
    if isinstance(cls, type) and is_dataclass(cls) and cls.__module__ == model_module.__name__
}
_MODEL_TYPES[Recipe.__name__] = Recipe
_MODEL_TYPES[TradeQuote.__name__] = TradeQuote
_WORLD_FIELDS = frozenset(vars(World()).keys())
_COMMUNITY_FIELDS = frozenset({"social_ties", "institutions", "institutional_rules"})
_M3_WORLD_FIELDS = _WORLD_FIELDS - _COMMUNITY_FIELDS


@dataclass(frozen=True)
class SnapshotInfo:
    snapshot_id: str
    schema_version: int
    created_at: str
    checksum: str
    event_count: int


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value {value!r} is not allowed")


def _stable_set_values(values: set[Any] | frozenset[Any]) -> list[Any]:
    encoded = [_encode_value(value) for value in values]
    return sorted(encoded, key=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")))


def _encode_value(value: Any) -> Any:
    """Encode one supported canonical value into JSON-compatible primitives."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not (value == value and abs(value) != float("inf")):
            raise ValueError("snapshot cannot contain non-finite floats")
        return value
    if isinstance(value, datetime):
        return {"$type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"$type": "date", "value": value.isoformat()}
    if isinstance(value, time):
        return {"$type": "time", "value": value.isoformat()}
    if isinstance(value, random.Random):
        return {"$type": "random", "state": _encode_value(value.getstate())}
    if isinstance(value, World):
        return {
            "$type": "World",
            "fields": {name: _encode_value(field_value) for name, field_value in vars(value).items()},
        }
    if is_dataclass(value):
        type_name = type(value).__name__
        if type_name not in _MODEL_TYPES or type(value).__module__ not in {
            model_module.__name__, Recipe.__module__, TradeQuote.__module__
        }:
            raise TypeError(f"snapshot encountered an unallowlisted dataclass: {type(value)!r}")
        return {
            "$type": type_name,
            "fields": {field.name: _encode_value(getattr(value, field.name)) for field in fields(value)},
        }
    if isinstance(value, dict):
        return {
            "$type": "dict",
            "items": [[_encode_value(key), _encode_value(item)] for key, item in value.items()],
        }
    if isinstance(value, list):
        return {"$type": "list", "items": [_encode_value(item) for item in value]}
    if isinstance(value, tuple):
        return {"$type": "tuple", "items": [_encode_value(item) for item in value]}
    if isinstance(value, set):
        return {"$type": "set", "items": _stable_set_values(value)}
    if isinstance(value, frozenset):
        return {"$type": "frozenset", "items": _stable_set_values(value)}
    raise TypeError(f"snapshot encountered unsupported value: {type(value)!r}")


def _decode_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if not isinstance(value, dict) or "$type" not in value:
        raise ValueError("invalid snapshot value")
    type_name = value["$type"]
    if type_name == "datetime":
        return datetime.fromisoformat(value["value"])
    if type_name == "date":
        return date.fromisoformat(value["value"])
    if type_name == "time":
        return time.fromisoformat(value["value"])
    if type_name == "random":
        generator = random.Random()
        generator.setstate(_decode_value(value["state"]))
        return generator
    if type_name == "World":
        world = World.__new__(World)
        fields_data = value.get("fields")
        if not isinstance(fields_data, dict):
            raise ValueError("invalid World snapshot")
        if set(fields_data) != _WORLD_FIELDS:
            raise ValueError("snapshot World fields do not match this schema")
        for name, field_value in fields_data.items():
            if not isinstance(name, str) or name.startswith("__"):
                raise ValueError("invalid World field")
            setattr(world, name, _decode_value(field_value))
        if not isinstance(getattr(world, "random", None), random.Random):
            raise ValueError("snapshot World is missing random state")
        return world
    if type_name == "dict":
        return {_decode_value(pair[0]): _decode_value(pair[1]) for pair in value["items"]}
    if type_name in {"list", "tuple", "set", "frozenset"}:
        items = [_decode_value(item) for item in value["items"]]
        return {"list": list, "tuple": tuple, "set": set, "frozenset": frozenset}[type_name](items)
    cls = _MODEL_TYPES.get(type_name)
    if cls is None:
        raise ValueError(f"snapshot type {type_name!r} is not allowlisted")
    fields_data = value.get("fields")
    if not isinstance(fields_data, dict):
        raise ValueError(f"invalid {type_name} snapshot")
    expected = {field.name for field in fields(cls)}
    if set(fields_data) != expected:
        raise ValueError(f"invalid fields for {type_name}")
    return cls(**{name: _decode_value(field_value) for name, field_value in fields_data.items()})


def _payload_for(world: World) -> bytes:
    document = {
        "format": "redos.world",
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "world": _encode_value(world),
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS command_ledger (
            command_id TEXT PRIMARY KEY,
            operation TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            result TEXT NOT NULL
        )
        """
    )


def _encoded_command_result(entry: dict[str, Any]) -> str:
    result = entry.get("result")
    return json.dumps(_encode_value(result), sort_keys=True, separators=(",", ":"), allow_nan=False)


def load_command_ledger(path: str | Path) -> dict[str, dict[str, Any]]:
    """Load durable command identities without replacing the canonical world."""
    path = Path(path)
    if not path.exists():
        return {}
    connection = _connect(path)
    try:
        with connection:
            _ensure_schema(connection)
        rows = connection.execute(
            "SELECT command_id, operation, fingerprint, result FROM command_ledger"
        ).fetchall()
    finally:
        connection.close()
    ledger: dict[str, dict[str, Any]] = {}
    for row in rows:
        result = _decode_value(json.loads(row["result"], parse_constant=_reject_json_constant))
        ledger[row["command_id"]] = {
            "operation": row["operation"],
            "fingerprint": row["fingerprint"],
            "result": result,
        }
    return ledger


def persist_command_entry(path: str | Path, command_id: str, entry: dict[str, Any]) -> None:
    """Persist one system-command identity without creating a world snapshot."""
    payload = _encoded_command_result(entry)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = _connect(path)
    try:
        with connection:
            _ensure_schema(connection)
            existing = connection.execute(
                "SELECT operation, fingerprint, result FROM command_ledger WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            if existing is not None:
                existing_entry = {
                    "operation": existing["operation"],
                    "fingerprint": existing["fingerprint"],
                    "result": _decode_value(json.loads(existing["result"], parse_constant=_reject_json_constant)),
                }
                if existing_entry != entry:
                    raise ValueError(f"command ID {command_id!r} has conflicting durable state")
                return
            connection.execute(
                "INSERT INTO command_ledger (command_id, operation, fingerprint, result) VALUES (?, ?, ?, ?)",
                (command_id, entry["operation"], entry["fingerprint"], payload),
            )
    finally:
        connection.close()


def save_snapshot(world: World, path: str | Path, *, snapshot_id: str = "latest") -> SnapshotInfo:
    """Atomically replace one named explicit-format local snapshot."""
    if not snapshot_id:
        raise ValueError("snapshot_id must not be empty")
    errors = validate_world(world)
    if errors:
        raise ValueError(f"cannot snapshot invalid world: {errors[:3]}")
    payload = _payload_for(world)
    checksum = hashlib.sha256(payload).hexdigest()
    info = SnapshotInfo(snapshot_id, SNAPSHOT_SCHEMA_VERSION, world.now.isoformat(), checksum, len(world.events))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
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
            for command_id, entry in world.runtime.get("command_ledger", {}).items():
                if not isinstance(command_id, str) or not isinstance(entry, dict):
                    raise ValueError("world command ledger contains an invalid entry")
                connection.execute(
                    """
                    INSERT INTO command_ledger (command_id, operation, fingerprint, result)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(command_id) DO UPDATE SET
                        operation = excluded.operation,
                        fingerprint = excluded.fingerprint,
                        result = excluded.result
                    """,
                    (command_id, entry["operation"], entry["fingerprint"], _encoded_command_result(entry)),
                )
    finally:
        connection.close()
    return info


def load_snapshot(path: str | Path, *, snapshot_id: str = "latest") -> World:
    """Load one explicit-format snapshot without executing database data."""
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
    if row["schema_version"] not in {2, SNAPSHOT_SCHEMA_VERSION}:
        raise ValueError(f"unsupported snapshot schema {row['schema_version']}")
    payload = bytes(row["payload"])
    if hashlib.sha256(payload).hexdigest() != row["checksum"]:
        raise ValueError(f"snapshot {snapshot_id!r} failed checksum validation")
    try:
        document = json.loads(payload.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"snapshot {snapshot_id!r} is not valid explicit JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("snapshot document must be an object")
    if document.get("format") != "redos.world" or document.get("schema_version") != row["schema_version"]:
        raise ValueError("unsupported snapshot document")
    document = migrate_snapshot_document(document)
    world = _decode_value(document.get("world"))
    if not isinstance(world, World):
        raise TypeError("snapshot payload is not a World")
    # System commands may have been accepted after the snapshot was written.
    # Rehydrate their durable identities before a caller considers a retry.
    durable_commands = load_command_ledger(path)
    if durable_commands:
        world.runtime.setdefault("command_ledger", {}).update(durable_commands)
    errors = validate_world(world)
    if errors:
        raise ValueError(f"snapshot contains invalid world: {errors[:3]}")
    return world


def migrate_snapshot_document(document: dict[str, Any]) -> dict[str, Any]:
    """Migrate frozen M3 schema 2 to 3 without changing its simulation state.

    The migration is in memory; a successful subsequent Save writes schema 3.
    Loading never rewrites the user's snapshot or its durable command ledger.
    """
    if document.get("schema_version") == SNAPSHOT_SCHEMA_VERSION:
        return document
    if document.get("format") != "redos.world" or document.get("schema_version") != 2:
        raise ValueError("unsupported snapshot migration")
    encoded_world = document.get("world")
    if not isinstance(encoded_world, dict) or encoded_world.get("$type") != "World":
        raise ValueError("invalid M3 World snapshot")
    fields_data = encoded_world.get("fields")
    if not isinstance(fields_data, dict) or set(fields_data) != _M3_WORLD_FIELDS:
        raise ValueError("M3 snapshot World fields do not match frozen schema 2")
    migrated = copy.deepcopy(document)
    for name in sorted(_COMMUNITY_FIELDS):
        migrated["world"]["fields"][name] = {"$type": "dict", "items": []}
    migrated["schema_version"] = SNAPSHOT_SCHEMA_VERSION
    return migrated


def _command_fingerprint(world: World, operation_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    def normalize(value: Any) -> Any:
        if value is world:
            return {"$world_argument": True}
        return _encode_value(value)

    document = {
        "operation": operation_name,
        "args": [normalize(value) for value in args],
        "kwargs": {key: normalize(value) for key, value in sorted(kwargs.items())},
    }
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def recorded_command_result(
    world: World,
    command_id: str,
    operation: Callable[..., _T],
    *args: Any,
    **kwargs: Any,
) -> tuple[bool, _T | None]:
    """Return a previously committed command result without executing anything."""
    if not command_id:
        raise ValueError("command_id must not be empty")
    ledger = world.runtime.get("command_ledger", {})
    operation_name = f"{operation.__module__}.{operation.__qualname__}"
    fingerprint = _command_fingerprint(world, operation_name, args, kwargs)
    existing = ledger.get(command_id)
    if existing is None:
        return False, None
    if existing.get("operation") != operation_name:
        raise ValueError(f"command ID {command_id!r} was already used for {existing.get('operation')}")
    if existing.get("fingerprint") != fingerprint:
        raise ValueError(f"command ID {command_id!r} was reused with different arguments")
    return True, copy.deepcopy(existing["result"])


def execute_once_with_status(
    world: World,
    command_id: str,
    operation: Callable[..., _T],
    *args: Any,
    **kwargs: Any,
) -> tuple[_T, bool]:
    """Execute a command once and report whether this call committed it."""
    ledger = world.runtime.setdefault("command_ledger", {})
    operation_name = f"{operation.__module__}.{operation.__qualname__}"
    fingerprint = _command_fingerprint(world, operation_name, args, kwargs)
    recorded, result = recorded_command_result(world, command_id, operation, *args, **kwargs)
    if recorded:
        return result, False  # type: ignore[return-value]
    result = operation(*args, **kwargs)
    ledger[command_id] = {
        "operation": operation_name,
        "fingerprint": fingerprint,
        "result": copy.deepcopy(result),
    }
    world.record(
        "command_executed",
        f"executed idempotent command {command_id}",
        entities=[command_id],
        data={"operation": operation_name, "fingerprint": fingerprint},
    )
    return result, True


def execute_once(
    world: World,
    command_id: str,
    operation: Callable[..., _T],
    *args: Any,
    **kwargs: Any,
) -> _T:
    """Execute a command once and reject conflicting reuse of its ID."""
    result, _executed = execute_once_with_status(world, command_id, operation, *args, **kwargs)
    return result


def execute_save_once(world: World, command_id: str, path: str | Path) -> tuple[dict[str, Any], bool]:
    """Atomically snapshot a Save command and its durable command identity.

    The saved command result intentionally excludes the payload checksum: the
    checksum covers the payload that contains this ledger entry, so including
    it would create a circular value. ``save_snapshot`` still returns the
    checksum to direct callers; web Save responses use this stable metadata.
    """
    if not command_id:
        raise ValueError("command_id must not be empty")
    operation_name = f"{execute_save_once.__module__}.{execute_save_once.__qualname__}"
    fingerprint = _command_fingerprint(world, operation_name, (world, str(path)), {})
    ledger = world.runtime.setdefault("command_ledger", {})
    existing = ledger.get(command_id)
    if existing is not None:
        if existing.get("operation") != operation_name:
            raise ValueError(f"command ID {command_id!r} was already used for {existing.get('operation')}")
        if existing.get("fingerprint") != fingerprint:
            raise ValueError(f"command ID {command_id!r} was reused with different arguments")
        return copy.deepcopy(existing["result"]), False

    previous_events = list(world.events)
    previous_event_number = world._event_number
    result = {
        "snapshot_id": "latest",
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "created_at": world.now.isoformat(),
        "event_count": len(world.events) + 1,
    }
    entry = {"operation": operation_name, "fingerprint": fingerprint, "result": result}
    ledger[command_id] = entry
    try:
        world.record(
            "command_executed",
            f"executed idempotent command {command_id}",
            entities=[command_id],
            data={"operation": operation_name, "fingerprint": fingerprint},
        )
        save_snapshot(world, path)
    except Exception:
        ledger.pop(command_id, None)
        world.events[:] = previous_events
        world._event_number = previous_event_number
        raise
    return copy.deepcopy(result), True
