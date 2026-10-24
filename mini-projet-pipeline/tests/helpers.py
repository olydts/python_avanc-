"""Outils partagés par les tests (aucune lecture de fichier)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

from txpipe.models import CSV_COLUMNS, Transaction

IBAN_A = "FR7630006000011234567890189"
IBAN_B = "FR1420041010050500013M02606"
IBAN_C = "FR7630004000031234567890143"
IBAN_D = "DE02120300000000202051"

IBAN_DE = "DE89370400440532013000"
IBAN_ES = "ES9121000418450200051332"
IBAN_GB = "GB29NWBK60161331926819"
IBAN_IT = "IT60X0542811101000000123456"
IBAN_NL = "NL91ABNA0417164300"

HEADER = ",".join(CSV_COLUMNS)
GOOD_LINE = f"2024-03-01T09:12:00,{IBAN_A},FR,BNPPARIBAS,{IBAN_DE},DE,1250.00,EUR"


def make_tx(
    montant: str = "100.00",
    iban_origine: str = IBAN_A,
    banque: str = "BNPPARIBAS",
    iban_dest: str = IBAN_DE,
    devise: str = "EUR",
    when: str = "2024-03-01T09:00:00",
) -> Transaction:
    """Construit une transaction directement en mémoire."""
    return Transaction(
        datetime_transaction=datetime.fromisoformat(when),
        iban_origine=iban_origine,
        pays_source=iban_origine[:2],
        banque_source=banque,
        iban_destinataire=iban_dest,
        pays_destinataire=iban_dest[:2],
        montant=Decimal(montant),
        devise=devise,
    )


def csv_text(*lines: str) -> str:
    """En-tête + lignes, comme le contenu d'un fichier CSV."""
    return "\n".join([HEADER, *lines]) + "\n"


def scalar(conn: sqlite3.Connection, sql: str) -> int:
    """Exécute une requête qui renvoie une seule valeur entière."""
    row = conn.execute(sql).fetchone()
    assert row is not None
    return int(row[0])
