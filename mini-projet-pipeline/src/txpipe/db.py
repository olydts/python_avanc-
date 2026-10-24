"""Étape 3 : persistance SQLite (schéma, insertion atomique, idempotence).

Les montants sont stockés en centimes (INTEGER) : les sommes SQL restent exactes.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from txpipe.models import Transaction
from txpipe.processing import analyse

SCHEMA = """
CREATE TABLE IF NOT EXISTS fichiers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nom               TEXT    NOT NULL,
    sha256            TEXT    NOT NULL UNIQUE,   -- identité du CONTENU (idempotence)
    nb_transactions   INTEGER NOT NULL,
    traite_le         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    fichier_id            INTEGER NOT NULL REFERENCES fichiers(id) ON DELETE CASCADE,
    ligne                 INTEGER NOT NULL,      -- rang dans le fichier (1..n)
    datetime_transaction  TEXT    NOT NULL,
    iban_origine          TEXT    NOT NULL,
    pays_source           TEXT    NOT NULL,
    banque_source         TEXT    NOT NULL,
    iban_destinataire     TEXT    NOT NULL,
    pays_destinataire     TEXT    NOT NULL,
    montant_centimes      INTEGER NOT NULL CHECK (montant_centimes > 0),
    devise                TEXT    NOT NULL,
    depasse_seuil         INTEGER NOT NULL CHECK (depasse_seuil IN (0, 1)),
    UNIQUE (fichier_id, ligne)
);

CREATE TABLE IF NOT EXISTS total_envoye_par_iban (
    fichier_id       INTEGER NOT NULL REFERENCES fichiers(id) ON DELETE CASCADE,
    iban             TEXT    NOT NULL,
    total_centimes   INTEGER NOT NULL,
    PRIMARY KEY (fichier_id, iban)
);

CREATE TABLE IF NOT EXISTS total_envoye_par_banque (
    fichier_id       INTEGER NOT NULL REFERENCES fichiers(id) ON DELETE CASCADE,
    banque           TEXT    NOT NULL,
    total_centimes   INTEGER NOT NULL,
    PRIMARY KEY (fichier_id, banque)
);

CREATE TABLE IF NOT EXISTS total_recu_par_iban (
    fichier_id       INTEGER NOT NULL REFERENCES fichiers(id) ON DELETE CASCADE,
    iban             TEXT    NOT NULL,
    total_centimes   INTEGER NOT NULL,
    PRIMARY KEY (fichier_id, iban)
);
"""

_INSERT_FILE = """
INSERT INTO fichiers (nom, sha256, nb_transactions, traite_le)
VALUES (?, ?, ?, ?)
ON CONFLICT (sha256) DO NOTHING
"""

_INSERT_TX = """
INSERT INTO transactions (
    fichier_id, ligne, datetime_transaction, iban_origine, pays_source,
    banque_source, iban_destinataire, pays_destinataire, montant_centimes,
    devise, depasse_seuil
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


@dataclass(frozen=True)
class InsertResult:
    """Résultat d'`insert_file`."""

    inserted: bool
    file_id: int | None  # None si le fichier était déjà traité
    existing_name: str | None  # nom sous lequel le même contenu avait été traité
    nb_transactions: int


def connect(path: str | Path, timeout: float = 5.0) -> sqlite3.Connection:
    """Ouvre une connexion : clés étrangères actives, lignes accessibles par nom.

    `isolation_level=None` : mode autocommit, les transactions sont gérées
    explicitement (BEGIN IMMEDIATE / COMMIT / ROLLBACK) par `transaction()`.
    """
    conn = sqlite3.connect(path, timeout=timeout, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Crée le schéma s'il n'existe pas (peut être appelée plusieurs fois)."""
    conn.executescript(SCHEMA)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Transaction atomique : COMMIT si le bloc réussit, ROLLBACK sinon.

    BEGIN IMMEDIATE prend le verrou d'écriture dès le début : un éventuel
    « database is locked » survient avant la première écriture (rien à défaire).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def to_cents(amount: Decimal) -> int:
    """Convertit un Decimal en centimes entiers ; refuse les fractions de centime."""
    cents = amount.scaleb(2)
    if cents != cents.to_integral_value():
        raise ValueError(f"montant avec plus de 2 décimales : {amount}")
    return int(cents)


def _tx_rows(
    file_id: int, transactions: Sequence[Transaction], flags: Sequence[bool]
) -> Iterator[tuple[int | str, ...]]:
    for position, (tx, flag) in enumerate(zip(transactions, flags, strict=True), start=1):
        yield (
            file_id,
            position,
            tx["datetime_transaction"].isoformat(),
            tx["iban_origine"],
            tx["pays_source"],
            tx["banque_source"],
            tx["iban_destinataire"],
            tx["pays_destinataire"],
            to_cents(tx["montant"]),
            tx["devise"],
            int(flag),
        )


def _totals_rows(file_id: int, totals: dict[str, Decimal]) -> list[tuple[int, str, int]]:
    return [(file_id, key, to_cents(total)) for key, total in totals.items()]


def insert_file(
    conn: sqlite3.Connection,
    name: str,
    sha256: str,
    transactions: Sequence[Transaction],
) -> InsertResult:
    """Insère un fichier ET ses résultats dans UNE transaction : tout ou rien.

    Idempotence : si un fichier de même `sha256` est déjà en base, rien n'est écrit
    et le résultat indique `inserted=False`. L'unicité est garantie par la
    contrainte UNIQUE de la base, donc même en cas de retry ou de concurrence.
    """
    analysis = analyse(transactions)  # pur ; échoue avant toute écriture si besoin

    with transaction(conn):
        cursor = conn.execute(
            _INSERT_FILE,
            (name, sha256, len(transactions), datetime.now(timezone.utc).isoformat()),
        )
        if cursor.rowcount == 0:
            row = conn.execute(
                "SELECT nom FROM fichiers WHERE sha256 = ?", (sha256,)
            ).fetchone()
            existing = str(row[0]) if row is not None else None
            return InsertResult(False, None, existing, 0)

        file_id = cursor.lastrowid
        if file_id is None:  # ne devrait jamais arriver après un INSERT réussi
            raise RuntimeError("lastrowid indisponible après insertion")

        conn.executemany(_INSERT_TX, _tx_rows(file_id, transactions, analysis.large_flags))
        conn.executemany(
            "INSERT INTO total_envoye_par_iban VALUES (?, ?, ?)",
            _totals_rows(file_id, analysis.sent_by_iban),
        )
        conn.executemany(
            "INSERT INTO total_envoye_par_banque VALUES (?, ?, ?)",
            _totals_rows(file_id, analysis.sent_by_bank),
        )
        conn.executemany(
            "INSERT INTO total_recu_par_iban VALUES (?, ?, ?)",
            _totals_rows(file_id, analysis.received_by_iban),
        )

    return InsertResult(True, file_id, None, len(transactions))
