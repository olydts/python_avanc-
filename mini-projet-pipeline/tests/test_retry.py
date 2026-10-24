"""Étape 7 : retry sur erreur transitoire uniquement."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.helpers import make_tx, scalar
from txpipe.db import InsertResult, connect, init_db, insert_file
from txpipe.retry import is_retryable, retry


def _no_sleep(_: float) -> None:
    return None


def test_is_retryable_classification() -> None:
    assert is_retryable(sqlite3.OperationalError("database is locked"))
    assert not is_retryable(sqlite3.OperationalError("no such table: x"))
    assert not is_retryable(sqlite3.IntegrityError("UNIQUE constraint failed"))
    assert not is_retryable(ValueError("boom"))


def test_retry_succeeds_after_transient_errors_with_backoff() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert retry(flaky, attempts=3, base_delay=0.1, sleep=sleeps.append) == "ok"
    assert len(calls) == 3
    assert sleeps == [0.1, 0.2]


def test_retry_gives_up_after_max_attempts() -> None:
    calls: list[int] = []

    def always_locked() -> str:
        calls.append(1)
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        retry(always_locked, attempts=3, sleep=_no_sleep)
    assert len(calls) == 3


def test_integrity_error_is_never_retried() -> None:
    calls: list[int] = []

    def violates() -> str:
        calls.append(1)
        raise sqlite3.IntegrityError("UNIQUE constraint failed: t.c")

    with pytest.raises(sqlite3.IntegrityError):
        retry(violates, attempts=5, sleep=_no_sleep)
    assert len(calls) == 1


def test_simulated_transient_error_then_reinsertion_succeeds() -> None:
    conn = connect(":memory:")
    init_db(conn)
    txs = [make_tx("10.00"), make_tx("6000.00")]
    attempts: list[int] = []

    def flaky_insert() -> InsertResult:
        attempts.append(1)
        if len(attempts) < 3:
            raise sqlite3.OperationalError("database is locked")
        return insert_file(conn, "a.csv", "hash-a", txs)

    result = retry(flaky_insert, sleep=_no_sleep)

    assert result.inserted is True
    assert len(attempts) == 3
    assert scalar(conn, "SELECT COUNT(*) FROM transactions") == 2
    assert scalar(conn, "SELECT COUNT(*) FROM fichiers") == 1
    conn.close()


def test_real_database_lock_is_released_during_retry(tmp_path: Path) -> None:
    db = tmp_path / "lock.db"
    holder = connect(db)
    init_db(holder)
    writer = connect(db, timeout=0.0)  # pas d'attente interne : l'erreur est immédiate
    txs = [make_tx("42.00")]

    holder.execute("BEGIN IMMEDIATE")  # `holder` détient le verrou d'écriture
    with pytest.raises(sqlite3.OperationalError) as info:
        insert_file(writer, "a.csv", "hash-a", txs)
    assert is_retryable(info.value)
    assert scalar(writer, "SELECT COUNT(*) FROM fichiers") == 0  # rien d'écrit

    def release_lock(_: float) -> None:
        holder.execute("ROLLBACK")  # le verrou saute pendant l'attente

    result = retry(lambda: insert_file(writer, "a.csv", "hash-a", txs), sleep=release_lock)

    assert result.inserted is True
    assert scalar(writer, "SELECT COUNT(*) FROM transactions") == 1
    holder.close()
    writer.close()
