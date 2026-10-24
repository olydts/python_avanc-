"""Tests unitaires des fonctions pures : les données sont construites dans le test."""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from tests.helpers import IBAN_A, IBAN_B, IBAN_DE, IBAN_ES, make_tx
from txpipe.processing import (
    analyse,
    flag_over_threshold,
    sum_received_by_iban,
    sum_sent_by_bank,
    sum_sent_by_iban,
)


def test_sum_sent_by_iban() -> None:
    txs = [
        make_tx("100.10", iban_origine=IBAN_A),
        make_tx("200.20", iban_origine=IBAN_A),
        make_tx("50.00", iban_origine=IBAN_B),
    ]
    assert sum_sent_by_iban(txs) == {IBAN_A: Decimal("300.30"), IBAN_B: Decimal("50.00")}


def test_sum_sent_by_bank_groups_several_ibans() -> None:
    txs = [
        make_tx("10.00", iban_origine=IBAN_A, banque="BNP"),
        make_tx("20.00", iban_origine=IBAN_B, banque="BNP"),
        make_tx("5.00", iban_origine=IBAN_B, banque="SOCGEN"),
    ]
    assert sum_sent_by_bank(txs) == {"BNP": Decimal("30.00"), "SOCGEN": Decimal("5.00")}


def test_sum_received_by_iban() -> None:
    txs = [
        make_tx("10.00", iban_dest=IBAN_DE),
        make_tx("15.50", iban_dest=IBAN_DE),
        make_tx("7.25", iban_dest=IBAN_ES),
    ]
    assert sum_received_by_iban(txs) == {IBAN_DE: Decimal("25.50"), IBAN_ES: Decimal("7.25")}


def test_sums_are_exact_not_float() -> None:
    # 0.1 + 0.2 != 0.3 en float ; avec Decimal le total est exact.
    txs = [make_tx("0.10"), make_tx("0.20")]
    assert sum_sent_by_iban(txs)[IBAN_A] == Decimal("0.30")


def test_empty_input_gives_empty_results() -> None:
    assert sum_sent_by_iban([]) == {}
    assert sum_sent_by_bank([]) == {}
    assert sum_received_by_iban([]) == {}
    assert flag_over_threshold([]) == []


def test_flag_is_strictly_above_threshold() -> None:
    txs = [make_tx("5000.00"), make_tx("5000.01"), make_tx("4999.99"), make_tx("7400.50")]
    assert flag_over_threshold(txs) == [False, True, False, True]


def test_flag_custom_threshold() -> None:
    txs = [make_tx("99.99"), make_tx("100.01")]
    assert flag_over_threshold(txs, threshold=Decimal("100")) == [False, True]


def test_functions_do_not_mutate_their_arguments() -> None:
    txs = [make_tx("6000.00"), make_tx("10.00", iban_origine=IBAN_B)]
    before = copy.deepcopy(txs)
    analyse(txs)
    sum_sent_by_iban(txs)
    sum_sent_by_bank(txs)
    sum_received_by_iban(txs)
    flag_over_threshold(txs)
    assert txs == before


def test_analyse_bundles_all_results() -> None:
    txs = [make_tx("6000.00"), make_tx("10.00")]
    result = analyse(txs)
    assert result.sent_by_iban == {IBAN_A: Decimal("6010.00")}
    assert result.sent_by_bank == {"BNPPARIBAS": Decimal("6010.00")}
    assert result.received_by_iban == {IBAN_DE: Decimal("6010.00")}
    assert result.large_flags == [True, False]


def test_mixed_currencies_are_refused() -> None:
    txs = [make_tx("10.00", devise="EUR"), make_tx("10.00", devise="USD")]
    with pytest.raises(ValueError, match="devises multiples"):
        sum_sent_by_iban(txs)
    with pytest.raises(ValueError, match="devises multiples"):
        analyse(txs)
