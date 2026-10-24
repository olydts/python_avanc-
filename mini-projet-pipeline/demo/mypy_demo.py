"""Démo étape 6 : un bug que mypy voit et que les tests ne voient pas.

`apply_fee` accepte un taux en `float` : or `Decimal * float` lève un TypeError à
l'exécution. Le test ci-contre n'exerce que la branche « sans frais », il passe.
"""

from __future__ import annotations

from decimal import Decimal


def apply_fee(amount: Decimal, fee_rate: float | None = None) -> Decimal:
    if fee_rate is None:
        return amount
    total: Decimal = amount * fee_rate
    return total
