from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Mapping as ABCMapping
from datetime import date, datetime
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator, Mapping, Sequence

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, Result
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import QueuePool

from .config import (
    BACKEND_ROOT,
    DATABASE_URL,
    DB_MAX_OVERFLOW,
    DB_POOL_RECYCLE_SECONDS,
    DB_POOL_SIZE,
    DB_POOL_TIMEOUT,
    ensure_workspace_layout,
)

_ENGINE: Engine | None = None
_ENGINE_CONFIG_KEY: tuple[str, int, int, int, int] | None = None

_PRIMARY_KEY_BY_TABLE = {
    "manufacturers": "manufacturer_id",
    "suppliers": "supplier_id",
    "items_master": "item_id",
    "inventory_ledger": "ledger_id",
    "quotations": "quotation_id",
    "purchase_orders": "purchase_order_id",
    "orders": "order_id",
    "order_lineage_events": "event_id",
    "transaction_log": "log_id",
    "projects": "project_id",
    "reservations": "reservation_id",
    "reservation_allocations": "allocation_id",
    "assemblies": "assembly_id",
    "location_assembly_usage": "usage_id",
    "project_requirements": "requirement_id",
    "procurement_batches": "batch_id",
    "procurement_lines": "line_id",
    "rfq_batches": "rfq_id",
    "rfq_lines": "line_id",
    "purchase_candidates": "candidate_id",
    "supplier_item_aliases": "alias_id",
    "import_jobs": "import_job_id",
    "import_job_effects": "effect_id",
    "users": "user_id",
    "registration_requests": "request_id",
}

_MANUAL_SAVEPOINT_SQL = re.compile(r"^\s*(SAVEPOINT|ROLLBACK\s+TO|RELEASE)\b", re.IGNORECASE)


def _normalize_db_url(db_url: str | None = None) -> str:
    return (db_url or DATABASE_URL).strip()


def get_engine(database_url: str | None = None) -> Engine:
    global _ENGINE, _ENGINE_CONFIG_KEY
    normalized = _normalize_db_url(database_url)
    engine_config_key = (
        normalized,
        DB_POOL_SIZE,
        DB_MAX_OVERFLOW,
        DB_POOL_TIMEOUT,
        DB_POOL_RECYCLE_SECONDS,
    )
    if _ENGINE is None or _ENGINE_CONFIG_KEY != engine_config_key:
        if _ENGINE is not None:
            _ENGINE.dispose()
        engine_kwargs: dict[str, Any] = {
            "poolclass": QueuePool,
            "pool_size": DB_POOL_SIZE,
            "max_overflow": DB_MAX_OVERFLOW,
            "pool_timeout": DB_POOL_TIMEOUT,
            "pool_pre_ping": True,
            "future": True,
        }
        if DB_POOL_RECYCLE_SECONDS > 0:
            engine_kwargs["pool_recycle"] = DB_POOL_RECYCLE_SECONDS
        _ENGINE = create_engine(
            normalized,
            **engine_kwargs,
        )
        _ENGINE_CONFIG_KEY = engine_config_key
    return _ENGINE


def dispose_engine() -> None:
    global _ENGINE, _ENGINE_CONFIG_KEY
    if _ENGINE is not None:
        _ENGINE.dispose()
        _ENGINE = None
        _ENGINE_CONFIG_KEY = None


def _build_alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def run_migrations(database_url: str | None = None) -> None:
    config = _build_alembic_config(_normalize_db_url(database_url))
    command.upgrade(config, "head")


class DBRow(ABCMapping[str, Any]):
    def __init__(self, mapping: Mapping[str, Any], values: Sequence[Any] | None = None):
        self._mapping = dict(mapping)
        self._values = tuple(values if values is not None else tuple(mapping.values()))

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def __iter__(self):
        return iter(self._mapping)

    def __len__(self) -> int:
        return len(self._mapping)

    def keys(self):
        return self._mapping.keys()

    def items(self):
        return self._mapping.items()

    def values(self):
        return self._mapping.values()

    def __contains__(self, key: object) -> bool:
        return key in self._mapping


class DBCursor:
    def __init__(
        self,
        rows: list[DBRow] | None = None,
        *,
        rowcount: int = -1,
        lastrowid: int | None = None,
    ) -> None:
        self._rows = rows or []
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self) -> DBRow | None:
        if not self._rows:
            return None
        return self._rows.pop(0)

    def fetchall(self) -> list[DBRow]:
        rows = list(self._rows)
        self._rows.clear()
        return rows


def _sequence_params_to_mapping(statement: str, params: Sequence[Any]) -> tuple[str, dict[str, Any]]:
    index = 0

    def _replace(_match: re.Match[str]) -> str:
        nonlocal index
        token = f"p{index}"
        index += 1
        return f":{token}"

    rewritten = re.sub(r"\?", _replace, statement)
    mapping = {f"p{i}": value for i, value in enumerate(params)}
    return rewritten, mapping


def _append_returning_clause(statement: str) -> tuple[str, str | None]:
    if re.search(r"\bRETURNING\b", statement, flags=re.IGNORECASE):
        return statement, None
    match = re.search(r"^\s*INSERT\s+INTO\s+([a-zA-Z_][a-zA-Z0-9_]*)", statement, flags=re.IGNORECASE)
    if not match:
        return statement, None
    table = match.group(1)
    primary_key = _PRIMARY_KEY_BY_TABLE.get(table)
    if primary_key is None:
        return statement, None
    stripped = statement.rstrip().rstrip(";")
    return f"{stripped} RETURNING {primary_key}", primary_key


def _materialize_rows(result: Result[Any]) -> list[DBRow]:
    if not result.returns_rows:
        return []
    materialized: list[DBRow] = []
    for row in result.fetchall():
        normalized_mapping = {key: _normalize_value(value) for key, value in row._mapping.items()}
        normalized_values = tuple(_normalize_value(value) for value in tuple(row))
        materialized.append(DBRow(normalized_mapping, normalized_values))
    return materialized


def _normalize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


class DBConnection:
    def __init__(self, connection: Connection):
        self._connection = connection
        self._actor_user_id: int | None = None
        self._actor_applied = False
        self._root_transaction = self._connection.begin()

    def set_actor(self, user_id: int | None) -> None:
        self._actor_user_id = user_id
        self._actor_applied = False

    def _ensure_actor(self) -> None:
        if self._actor_applied:
            return
        actor_value = "" if self._actor_user_id is None else str(int(self._actor_user_id))
        self._connection.execute(
            text("SELECT set_config('app.user_id', :user_id, false)"),
            {"user_id": actor_value},
        )
        self._actor_applied = True

    def execute(self, statement: str, params: Sequence[Any] | Mapping[str, Any] | None = None) -> DBCursor:
        self._ensure_actor()
        sql = statement
        bind_params: Mapping[str, Any]
        if params is None:
            bind_params = {}
        elif isinstance(params, Mapping):
            bind_params = dict(params)
        else:
            sql, bind_params = _sequence_params_to_mapping(statement, list(params))

        lastrowid: int | None = None
        sql_to_run, returning_pk = _append_returning_clause(sql)
        if _MANUAL_SAVEPOINT_SQL.match(sql_to_run):
            result = self._connection.execute(text(sql_to_run), bind_params)
            rows = _materialize_rows(result)
            if returning_pk and rows:
                lastrowid = int(rows[0][returning_pk])
            return DBCursor(rows, rowcount=result.rowcount, lastrowid=lastrowid)
        nested = self._connection.begin_nested()
        try:
            result = self._connection.execute(text(sql_to_run), bind_params)
            rows = _materialize_rows(result)
            if returning_pk and rows:
                lastrowid = int(rows[0][returning_pk])
            nested.commit()
            return DBCursor(rows, rowcount=result.rowcount, lastrowid=lastrowid)
        except IntegrityError as exc:
            nested.rollback()
            raise sqlite3.IntegrityError(str(exc)) from exc
        except Exception:
            nested.rollback()
            raise

    def commit(self) -> None:
        self._root_transaction.commit()
        self._root_transaction = self._connection.begin()
        self._actor_applied = False

    def rollback(self) -> None:
        self._root_transaction.rollback()
        self._root_transaction = self._connection.begin()
        self._actor_applied = False

    def close(self) -> None:
        if self._root_transaction.is_active:
            self._root_transaction.rollback()
        self._connection.close()

    @property
    def connection(self) -> Connection:
        return self._connection


def init_db(database_url: str | None = None) -> str:
    ensure_workspace_layout()
    normalized = _normalize_db_url(database_url)
    get_engine(normalized)
    run_migrations(normalized)
    return normalized


def get_connection(database_url: str | None = None) -> DBConnection:
    engine = get_engine(database_url)
    return DBConnection(engine.connect())


@contextmanager
def transaction(conn: DBConnection) -> Iterator[DBConnection]:
    tx = conn.connection.begin_nested() if conn.connection.in_transaction() else conn.connection.begin()
    try:
        yield conn
    except Exception:
        tx.rollback()
        raise
    else:
        tx.commit()
