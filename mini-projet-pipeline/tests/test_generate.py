"""Étape 1 : le jeu de données généré respecte le cahier des charges."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path

from txpipe.generate import generate_csv_files
from txpipe.loading import load_file


def test_generation_matches_requirements(tmp_path: Path) -> None:
    paths = generate_csv_files(tmp_path)
    assert len(paths) >= 3

    all_txs = []
    for path in paths:
        _, txs = load_file(path)  # le fichier généré est valide
        assert 5 <= len(txs) <= 10
        all_txs.extend(txs)

    assert sum(1 for tx in all_txs if tx["montant"] > Decimal("5000")) >= 2
    origins = Counter(tx["iban_origine"] for tx in all_txs)
    assert sum(1 for n in origins.values() if n > 1) >= 2
    assert {tx["devise"] for tx in all_txs} == {"EUR"}


def test_generation_is_reproducible(tmp_path: Path) -> None:
    first = {p.name: p.read_bytes() for p in generate_csv_files(tmp_path / "a")}
    second = {p.name: p.read_bytes() for p in generate_csv_files(tmp_path / "b")}
    assert first == second
