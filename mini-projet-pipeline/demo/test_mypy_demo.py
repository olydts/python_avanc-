from __future__ import annotations

from decimal import Decimal

from mypy_demo import apply_fee


def test_apply_fee_without_fee() -> None:
    assert apply_fee(Decimal("100.00")) == Decimal("100.00")
