"""Étape 5 : test d'intégration — la pipeline complète puis vérification de la base."""

from __future__ import annotations

import shutil
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from tests.helpers import (
    IBAN_A,
    IBAN_B,
    IBAN_C,
    IBAN_D,
    IBAN_DE,
    IBAN_ES,
    IBAN_GB,
    IBAN_IT,
    IBAN_NL,
    scalar,
)
from txpipe.db import connect
from txpipe.pipeline import main

# Valeurs attendues, calculées à la main à partir du jeu de données (en centimes).
EXPECTED_ROWS = 18
EXPECTED_LARGE = 6
EXPECTED_TOTAL_CENTS = 6424998
EXPECTED_SENT_BY_IBAN = {IBAN_A: 2645080, IBAN_B: 1240086, IBAN_C: 1129000, IBAN_D: 1410832}
EXPECTED_SENT_BY_BANK = {"BNPPARIBAS": 3774080, "SOCGEN": 1240086, "DKB": 1410832}
EXPECTED_RECEIVED = {
    IBAN_DE: 847500,
    IBAN_ES: 1305050,
    IBAN_GB: 2732075,
    IBAN_IT: 1028049,
    IBAN_NL: 512324,
}


def _consolidated(conn: sqlite3.Connection, table: str, key: str) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {key}, SUM(total_centimes) FROM {table} GROUP BY {key}"
    ).fetchall()
    return {str(k): int(v) for k, v in rows}


@pytest.fixture
def paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "data", tmp_path / "pipeline.db"


def _run(data: Path, db: Path, *extra: str) -> int:
    return main(["--data-dir", str(data), "--db", str(db), *extra])


def test_pipeline_inserts_the_expected_data(paths: tuple[Path, Path]) -> None:
    data, db = paths
    assert _run(data, db) == 0

    conn = connect(db)
    assert scalar(conn, "SELECT COUNT(*) FROM fichiers") == 3
    assert scalar(conn, "SELECT COUNT(*) FROM transactions") == EXPECTED_ROWS
    assert scalar(conn, "SELECT SUM(depasse_seuil) FROM transactions") == EXPECTED_LARGE
    assert scalar(conn, "SELECT SUM(montant_centimes) FROM transactions") == EXPECTED_TOTAL_CENTS
    assert _consolidated(conn, "total_envoye_par_iban", "iban") == EXPECTED_SENT_BY_IBAN
    assert _consolidated(conn, "total_envoye_par_banque", "banque") == EXPECTED_SENT_BY_BANK
    assert _consolidated(conn, "total_recu_par_iban", "iban") == EXPECTED_RECEIVED
    conn.close()


def test_totals_stored_in_database_are_exact_decimals(paths: tuple[Path, Path]) -> None:
    data, db = paths
    _run(data, db)
    conn = connect(db)
    total = _consolidated(conn, "total_envoye_par_iban", "iban")[IBAN_A]
    assert Decimal(total).scaleb(-2) == Decimal("26450.80")
    conn.close()


def test_boundary_amounts_are_flagged_correctly(paths: tuple[Path, Path]) -> None:
    data, db = paths
    _run(data, db)
    conn = connect(db)
    flags = dict(
        conn.execute(
            "SELECT montant_centimes, depasse_seuil FROM transactions "
            "WHERE montant_centimes IN (500000, 500001)"
        ).fetchall()
    )
    assert flags == {500000: 0, 500001: 1}  # 5000.00 : non ; 5000.01 : oui
    conn.close()


def test_rerunning_the_pipeline_creates_no_duplicates(
    paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    data, db = paths
    assert _run(data, db) == 0
    capsys.readouterr()

    assert _run(data, db) == 0  # le retry de toute la pipeline

    out = capsys.readouterr().out
    assert out.count("SKIP") == 3 and "déjà traité" in out
    conn = connect(db)
    assert scalar(conn, "SELECT COUNT(*) FROM fichiers") == 3
    assert scalar(conn, "SELECT COUNT(*) FROM transactions") == EXPECTED_ROWS
    assert scalar(conn, "SELECT SUM(total_centimes) FROM total_envoye_par_iban") == (
        EXPECTED_TOTAL_CENTS
    )
    conn.close()


def test_same_content_under_another_name_is_skipped(paths: tuple[Path, Path]) -> None:
    data, db = paths
    _run(data, db)
    shutil.copy(data / "transactions_2024-03-01.csv", data / "copie_renommee.csv")

    assert _run(data, db, "--no-generate") == 0

    conn = connect(db)
    assert scalar(conn, "SELECT COUNT(*) FROM fichiers") == 3
    assert scalar(conn, "SELECT COUNT(*) FROM transactions") == EXPECTED_ROWS
    conn.close()


def test_same_name_with_different_content_is_processed(paths: tuple[Path, Path]) -> None:
    data, db = paths
    _run(data, db)
    target = data / "transactions_2024-03-01.csv"
    target.write_text(target.read_text().replace("1250.00", "1251.00"), newline="\n")

    assert _run(data, db, "--no-generate") == 0

    conn = connect(db)
    assert scalar(conn, "SELECT COUNT(*) FROM fichiers") == 4
    assert scalar(conn, "SELECT COUNT(*) FROM transactions") == EXPECTED_ROWS + 6
    conn.close()
