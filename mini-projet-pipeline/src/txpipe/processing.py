"""Étape 2 (traitement) : fonctions PURES.

Aucune lecture de fichier, aucun print, aucune modification des arguments.
Les montants restent des `Decimal` : jamais de float.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from txpipe.models import Transaction

LARGE_AMOUNT_THRESHOLD = Decimal("5000")


@dataclass(frozen=True)
class Analysis:
    """Résultat complet du traitement d'un lot de transactions."""

    sent_by_iban: dict[str, Decimal]
    sent_by_bank: dict[str, Decimal]
    received_by_iban: dict[str, Decimal]
    large_flags: list[bool]  # large_flags[i] correspond à transactions[i]


def _ensure_single_currency(transactions: Sequence[Transaction]) -> None:
    currencies = {tx["devise"] for tx in transactions}
    if len(currencies) > 1:
        raise ValueError(
            f"devises multiples non supportées : {sorted(currencies)} "
            "(additionner des EUR et des USD n'a pas de sens)"
        )


def _sum_by(
    transactions: Sequence[Transaction], key: Callable[[Transaction], str]
) -> dict[str, Decimal]:
    _ensure_single_currency(transactions)
    totals: dict[str, Decimal] = {}
    for tx in transactions:
        k = key(tx)
        totals[k] = totals.get(k, Decimal(0)) + tx["montant"]
    return totals


def sum_sent_by_iban(transactions: Sequence[Transaction]) -> dict[str, Decimal]:
    """Somme des montants envoyés, par IBAN d'origine."""
    return _sum_by(transactions, lambda tx: tx["iban_origine"])


def sum_sent_by_bank(transactions: Sequence[Transaction]) -> dict[str, Decimal]:
    """Somme des montants envoyés, par banque source."""
    return _sum_by(transactions, lambda tx: tx["banque_source"])


def sum_received_by_iban(transactions: Sequence[Transaction]) -> dict[str, Decimal]:
    """Somme des montants reçus, par IBAN destinataire."""
    return _sum_by(transactions, lambda tx: tx["iban_destinataire"])


def flag_over_threshold(
    transactions: Sequence[Transaction],
    threshold: Decimal = LARGE_AMOUNT_THRESHOLD,
) -> list[bool]:
    """Pour chaque transaction : True si le montant dépasse STRICTEMENT le seuil."""
    return [tx["montant"] > threshold for tx in transactions]


def analyse(transactions: Sequence[Transaction]) -> Analysis:
    """Applique tous les traitements d'un coup."""
    return Analysis(
        sent_by_iban=sum_sent_by_iban(transactions),
        sent_by_bank=sum_sent_by_bank(transactions),
        received_by_iban=sum_received_by_iban(transactions),
        large_flags=flag_over_threshold(transactions),
    )
