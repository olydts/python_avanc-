"""Étape 6 : comportement en cas d'échec (code de retour + base propre)."""

from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from tests.helpers import GOOD_LINE, csv_text, scalar
from txpipe.db import connect
from txpipe.pipeline import main

SRC = Path(__file__).resolve().parent.parent / "src"


def _write_good(data: Path) -> None:
    data.mkdir(parents=True, exist_ok=True)
    (data / "a_good.csv").write_text(csv_text(GOOD_LINE), newline="\n")


def _write_buggy_generation(data: Path) -> None:
    """Simule un bug du générateur : montant non numérique dans la 2e ligne."""
    data.mkdir(parents=True, exist_ok=True)
    broken = GOOD_LINE.replace("1250.00", "N/A")
    (data / "b_bug.csv").write_text(csv_text(GOOD_LINE, broken), newline="\n")


def test_invalid_file_gives_nonzero_exit_and_clean_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data, db = tmp_path / "data", tmp_path / "p.db"
    _write_good(data)
    _write_buggy_generation(data)

    code = main(["--data-dir", str(data), "--db", str(db), "--no-generate"])

    assert code != 0
    captured = capsys.readouterr()
    assert "FAIL  b_bug.csv" in captured.err and "montant" in captured.err
    conn = connect(db)
    names = [r[0] for r in conn.execute("SELECT nom FROM fichiers")]
    assert names == ["a_good.csv"]  # le bon fichier est traité, le mauvais absent
    assert scalar(conn, "SELECT COUNT(*) FROM transactions") == 1  # AUCUNE ligne du fichier en échec
    conn.close()


def test_failure_in_the_middle_of_insertion_is_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data, db = tmp_path / "data", tmp_path / "p.db"
    data.mkdir()
    (data / "c.csv").write_text(csv_text(GOOD_LINE, GOOD_LINE, GOOD_LINE, GOOD_LINE), newline="\n")
    calls: list[int] = []

    def exploding_to_cents(amount: Decimal) -> int:
        calls.append(1)
        if len(calls) == 3:  # 2 lignes déjà écrites quand ça casse
            raise RuntimeError("panne simulée pendant l'insertion")
        return int(amount * 100)

    monkeypatch.setattr("txpipe.db.to_cents", exploding_to_cents)

    code = main(["--data-dir", str(data), "--db", str(db), "--no-generate"])

    assert code != 0
    assert "panne simulée" in capsys.readouterr().err
    conn = connect(db)
    for table in ("fichiers", "transactions", "total_envoye_par_iban", "total_recu_par_iban"):
        assert scalar(conn, f"SELECT COUNT(*) FROM {table}") == 0, table
    conn.close()


def test_empty_directory_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "vide").mkdir()
    assert main(["--data-dir", str(tmp_path / "vide"), "--db", str(tmp_path / "p.db"), "--no-generate"]) != 0


def _cli(data: Path, db: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run(
        [sys.executable, "-m", "txpipe", "--data-dir", str(data), "--db", str(db), "--no-generate"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_command_line_exit_codes(tmp_path: Path) -> None:
    good, bad = tmp_path / "good", tmp_path / "bad"
    _write_good(good)
    _write_good(bad)
    _write_buggy_generation(bad)

    assert _cli(good, tmp_path / "g.db").returncode == 0
    failed = _cli(bad, tmp_path / "b.db")
    assert failed.returncode == 1
    assert "FAIL  b_bug.csv" in failed.stderr
