"""Tests du chargement/validation : le contenu CSV est construit en mémoire."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from tests.helpers import GOOD_LINE, HEADER, IBAN_A, IBAN_DE, csv_text
from txpipe.loading import parse_transactions
from txpipe.models import InvalidFileError


def _line(**changes: str) -> str:
    fields = {
        "datetime_transaction": "2024-03-01T09:12:00",
        "iban_origine": IBAN_A,
        "pays_source": "FR",
        "banque_source": "BNPPARIBAS",
        "iban_destinataire": IBAN_DE,
        "pays_destinataire": "DE",
        "montant": "1250.00",
        "devise": "EUR",
    }
    fields.update(changes)
    return ",".join(fields.values())


def _errors(text: str) -> list[str]:
    with pytest.raises(InvalidFileError) as info:
        parse_transactions(text, source="test.csv")
    return info.value.errors


def test_valid_file_is_parsed_with_precise_types() -> None:
    txs = parse_transactions(csv_text(GOOD_LINE, _line(montant="7400.5")))
    assert len(txs) == 2
    assert txs[0]["montant"] == Decimal("1250.00")
    assert isinstance(txs[0]["montant"], Decimal)
    assert txs[0]["datetime_transaction"] == datetime(2024, 3, 1, 9, 12)
    assert txs[1]["montant"] == Decimal("7400.5")


def test_non_numeric_amount_is_rejected() -> None:
    errors = _errors(csv_text(GOOD_LINE, _line(montant="abc")))
    assert len(errors) == 1
    assert "ligne 3" in errors[0] and "montant" in errors[0]


@pytest.mark.parametrize("bad", ["-5.00", "0.00", "10.123", "1e3", "NaN", "1_000", "", "12,50"])
def test_bad_amounts_are_rejected(bad: str) -> None:
    assert _errors(csv_text(_line(montant=bad)))


def test_missing_column_in_row_is_rejected() -> None:
    short = ",".join(GOOD_LINE.split(",")[:-1])  # il manque la devise
    errors = _errors(csv_text(short))
    assert "devise" in errors[0]


def test_extra_column_in_row_is_rejected() -> None:
    errors = _errors(csv_text(GOOD_LINE + ",surplus"))
    assert "trop de colonnes" in errors[0]


def test_unreadable_date_is_rejected() -> None:
    errors = _errors(csv_text(_line(datetime_transaction="2024-13-45T99:00:00")))
    assert "date illisible" in errors[0]


@pytest.mark.parametrize(
    ("column", "value"),
    [("iban_origine", "N0TANIBAN"), ("pays_source", "FRA"), ("devise", "EURO")],
)
def test_malformed_identifiers_are_rejected(column: str, value: str) -> None:
    assert _errors(csv_text(_line(**{column: value})))


def test_wrong_header_is_rejected() -> None:
    text = "date,iban\n2024-03-01,FR76\n"
    assert "en-tête inattendu" in _errors(text)[0]


def test_empty_file_is_rejected() -> None:
    assert "vide" in _errors("")[0]


def test_header_only_is_rejected() -> None:
    assert "aucune transaction" in _errors(HEADER + "\n")[0]


def test_global_rejection_one_bad_line_fails_the_whole_file() -> None:
    text = csv_text(GOOD_LINE, _line(montant="oops"), GOOD_LINE)
    with pytest.raises(InvalidFileError):
        parse_transactions(text)


def test_all_errors_are_collected() -> None:
    text = csv_text(_line(montant="oops"), GOOD_LINE, _line(devise="X"))
    errors = _errors(text)
    assert len(errors) == 2
    assert "ligne 2" in errors[0] and "ligne 4" in errors[1]
