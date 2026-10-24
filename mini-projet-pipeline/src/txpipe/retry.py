"""Étape 7 : retry limité aux erreurs TRANSITOIRES de sqlite3.

Retry : `sqlite3.OperationalError` de type « base verrouillée / occupée »
(SQLITE_BUSY, SQLITE_LOCKED). L'état de la base peut changer d'une seconde à
l'autre : réessayer plus tard peut réussir.

Jamais de retry : `sqlite3.IntegrityError` (contrainte violée), `ProgrammingError`,
OperationalError « no such table »... Ces erreurs sont DÉTERMINISTES : les mêmes
données produiront la même erreur, réessayer ne fait que perdre du temps.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

_TRANSIENT_NAMES = frozenset({"SQLITE_BUSY", "SQLITE_LOCKED"})


def is_retryable(exc: BaseException) -> bool:
    """True uniquement pour une OperationalError de verrouillage."""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    if getattr(exc, "sqlite_errorname", None) in _TRANSIENT_NAMES:
        return True
    # Exceptions construites à la main (tests) : pas de code, on lit le message.
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def retry(
    func: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Appelle `func` jusqu'à `attempts` fois, avec attente exponentielle.

    Seules les erreurs `is_retryable` déclenchent une nouvelle tentative ; toute
    autre exception remonte immédiatement. `func` doit être atomique (comme
    `insert_file`) pour qu'un nouvel essai soit sans danger.
    """
    if attempts < 1:
        raise ValueError("attempts doit être >= 1")
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except sqlite3.Error as exc:
            if not is_retryable(exc) or attempt == attempts:
                raise
            sleep(base_delay * 2 ** (attempt - 1))
    raise AssertionError("inatteignable")  # pragma: no cover
