"""Étape 2 (chargement) : lecture et validation des CSV.

Stratégie pour les lignes invalides : REJET GLOBAL. Si une seule ligne (ou l'en-tête)
est invalide, tout le fichier est refusé et rien n'est inséré. Toutes les erreurs du
fichier sont collectées avant de lever `InvalidFileError`, pour tout corriger d'un coup.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from txpipe.models import CSV_COLUMNS, InvalidFileError, Transaction

_IBAN_RE = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}")
_COUNTRY_RE = re.compile(r"[A-Z]{2}")
_CURRENCY_RE = re.compile(r"[A-Z]{3}")
# Nombre décimal positif, 2 décimales maximum (pas de signe, pas d'exposant,
# pas de "NaN", pas de séparateur "_" que Decimal accepterait pourtant).
_AMOUNT_RE = re.compile(r"\d{1,15}(\.\d{1,2})?")


class RowError(ValueError):
    """Une ligne du CSV est invalide."""


def _parse_amount(text: str) -> Decimal:
    if not _AMOUNT_RE.fullmatch(text):
        raise RowError(
            f"montant invalide {text!r} (attendu : nombre positif, 2 décimales max)"
        )
    amount = Decimal(text)
    if amount <= 0:
        raise RowError(f"montant {text!r} doit être strictement positif")
    return amount


def _parse_pattern(text: str, pattern: re.Pattern[str], label: str) -> str:
    value = text.upper()
    if not pattern.fullmatch(value):
        raise RowError(f"{label} invalide : {text!r}")
    return value


def parse_row(row: Mapping[str, str | None], line_no: int) -> Transaction:
    """Convertit une ligne brute (dict de chaînes) en `Transaction` ou lève `RowError`."""

    def field(name: str) -> str:
        value = row.get(name)
        if value is None or not value.strip():
            raise RowError(f"ligne {line_no}: colonne {name!r} manquante ou vide")
        return value.strip()

    try:
        when = datetime.fromisoformat(field("datetime_transaction"))
    except ValueError:
        raise RowError(
            f"ligne {line_no}: date illisible {row.get('datetime_transaction')!r}"
        ) from None

    try:
        return Transaction(
            datetime_transaction=when,
            iban_origine=_parse_pattern(field("iban_origine"), _IBAN_RE, "iban_origine"),
            pays_source=_parse_pattern(field("pays_source"), _COUNTRY_RE, "pays_source"),
            banque_source=field("banque_source"),
            iban_destinataire=_parse_pattern(
                field("iban_destinataire"), _IBAN_RE, "iban_destinataire"
            ),
            pays_destinataire=_parse_pattern(
                field("pays_destinataire"), _COUNTRY_RE, "pays_destinataire"
            ),
            montant=_parse_amount(field("montant")),
            devise=_parse_pattern(field("devise"), _CURRENCY_RE, "devise"),
        )
    except RowError as exc:
        message = str(exc)
        if not message.startswith("ligne "):
            message = f"ligne {line_no}: {message}"
        raise RowError(message) from None


def parse_transactions(text: str, source: str = "<texte>") -> list[Transaction]:
    """Analyse le contenu d'un CSV. Rejet global : lève `InvalidFileError` au moindre souci."""
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None:
        raise InvalidFileError(source, ["fichier vide (pas d'en-tête)"])
    if tuple(reader.fieldnames) != CSV_COLUMNS:
        raise InvalidFileError(
            source,
            [
                "en-tête inattendu : "
                f"{','.join(reader.fieldnames)!r} (attendu : {','.join(CSV_COLUMNS)!r})"
            ],
        )

    transactions: list[Transaction] = []
    errors: list[str] = []
    for line_no, raw in enumerate(reader, start=2):
        if None in raw:  # plus de valeurs que de colonnes
            errors.append(f"ligne {line_no}: trop de colonnes")
            continue
        try:
            transactions.append(parse_row(raw, line_no))
        except RowError as exc:
            errors.append(str(exc))

    if not errors and not transactions:
        errors.append("aucune transaction dans le fichier")
    if errors:
        raise InvalidFileError(source, errors)
    return transactions


def load_file(path: Path) -> tuple[str, list[Transaction]]:
    """Lit un fichier UNE seule fois : renvoie (sha256 du contenu, transactions).

    Le hash et l'analyse portent sur les mêmes octets, ce qui évite qu'un fichier
    modifié entre-temps soit enregistré sous le hash d'un autre contenu.
    """
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    return digest, parse_transactions(content.decode("utf-8-sig"), source=path.name)
