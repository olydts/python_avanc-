"""Types de données partagés par tous les modules."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TypedDict

CSV_COLUMNS: tuple[str, ...] = (
    "datetime_transaction",
    "iban_origine",
    "pays_source",
    "banque_source",
    "iban_destinataire",
    "pays_destinataire",
    "montant",
    "devise",
)


class Transaction(TypedDict):
    """Une transaction financière. Le montant est un Decimal (jamais un float)."""

    datetime_transaction: datetime
    iban_origine: str
    pays_source: str
    banque_source: str
    iban_destinataire: str
    pays_destinataire: str
    montant: Decimal
    devise: str


class InvalidFileError(Exception):
    """Fichier rejeté globalement : au moins une ligne (ou l'en-tête) est invalide."""

    def __init__(self, source: str, errors: list[str]) -> None:
        super().__init__(f"{len(errors)} erreur(s) de validation")
        self.source = source
        self.errors = errors
