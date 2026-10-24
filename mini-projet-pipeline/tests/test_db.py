"""Tests de la persistance : base SQLite en mémoire."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from decimal import Decimal

import pytest

from tests.helpers import IBAN_A, IBAN_B, scalar, make_tx
from txpipe.db import connect, init_db, insert_file, to_cents

TABLES = (
    "fichiers",
    "transactions",
    "total_envoye_par_iban",
    "total_envoye_par_banque",
    "total_recu_par_iban",
)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: scalar(conn, f"SELECT COUNT(*) FROM {t}") for t in TABLES}


def test_init_db_is_idempotent(conn: sqlite3.Connection) -> None:
    init_db(conn)
    init_db(conn)
    assert _counts(conn) == dict.fromkeys(TABLES, 0)


def test_insert_file_stores_rows_flags_and_totals(conn: sqlite3.Connection) -> None:
    txs = [make_tx("7400.50"), make_tx("10.25", iban_origine=IBAN_B)]
    result = insert_file(conn, "a.csv", "hash-a", txs)

    assert result.inserted is True and result.nb_transactions == 2
    assert scalar(conn, "SELECT COUNT(*) FROM transactions") == 2
    assert scalar(conn, "SELECT SUM(depasse_seuil) FROM transactions") == 1
    assert scalar(conn, "SELECT SUM(montant_centimes) FROM transactions") == 741075
    totals = dict(conn.execute("SELECT iban, total_centimes FROM total_envoye_par_iban").fetchall())
    assert totals == {IBAN_A: 740050, IBAN_B: 1025}


def test_same_content_under_another_name_is_not_inserted_twice(conn: sqlite3.Connection) -> None:
    txs = [make_tx("10.00")]
    insert_file(conn, "original.csv", "same-hash", txs)
    before = _counts(conn)

    result = insert_file(conn, "copie.csv", "same-hash", txs)

    assert result.inserted is False
    assert result.existing_name == "original.csv"
    assert _counts(conn) == before


def test_same_name_with_different_content_is_inserted(conn: sqlite3.Connection) -> None:
    insert_file(conn, "jour.csv", "hash-v1", [make_tx("10.00")])
    result = insert_file(conn, "jour.csv", "hash-v2", [make_tx("20.00")])

    assert result.inserted is True
    assert scalar(conn, "SELECT COUNT(*) FROM fichiers") == 2
    assert scalar(conn, "SELECT COUNT(*) FROM transactions") == 2


def test_failed_insertion_leaves_no_partial_data(conn: sqlite3.Connection) -> None:
    # 3e transaction : montant négatif, refusé par le CHECK de la base
    # (le chargeur l'aurait déjà rejeté : on teste ici la défense en profondeur).
    txs = [make_tx("10.00"), make_tx("20.00"), make_tx("-5.00")]

    with pytest.raises(sqlite3.IntegrityError):
        insert_file(conn, "bad.csv", "hash-bad", txs)

    assert _counts(conn) == dict.fromkeys(TABLES, 0)
    assert conn.in_transaction is False


def test_foreign_keys_are_enforced(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO total_recu_par_iban (fichier_id, iban, total_centimes) VALUES (999, 'X', 1)"
        )


@pytest.mark.parametrize(
    ("amount", "cents"),
    [("12.34", 1234), ("0.10", 10), ("5000", 500000), ("7400.5", 740050)],
)
def test_to_cents(amount: str, cents: int) -> None:
    assert to_cents(Decimal(amount)) == cents


def test_to_cents_refuses_fractions_of_cent() -> None:
    with pytest.raises(ValueError, match="2 décimales"):
        to_cents(Decimal("1.234"))
