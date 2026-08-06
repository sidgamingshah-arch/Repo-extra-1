from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.models import (
    BBox,
    Basis,
    ConfidenceVector,
    ExtractedValue,
    LineItem,
)


def test_bbox_validation_and_union():
    a = BBox(x0=0.1, y0=0.1, x1=0.3, y1=0.2)
    b = BBox(x0=0.2, y0=0.05, x1=0.5, y1=0.25)
    u = a.union(b)
    assert (u.x0, u.y0, u.x1, u.y1) == (0.1, 0.05, 0.5, 0.25)
    with pytest.raises(ValueError):
        BBox(x0=0.5, y0=0.0, x1=0.1, y1=0.2)


def test_confidence_combination_and_validation_modulation():
    cv = ConfidenceVector(ocr=1.0, structure=0.9, mapping=0.8)
    assert cv.overall == pytest.approx(0.72, abs=1e-6)
    cv.validation = 0.5  # a failed balance check caps it low
    assert cv.overall == pytest.approx(0.36, abs=1e-6)
    assert cv.weakest == 0.5


def test_line_item_values_keyed_by_basis_period():
    li = LineItem(source_label="Cash and cash equivalents")
    li.set_value(ExtractedValue(value=Decimal("1204"), basis=Basis.CONSOLIDATED,
                                period_label="FY2024"))
    li.set_value(ExtractedValue(value=Decimal("1180"), basis=Basis.STANDALONE,
                                period_label="FY2024"))
    got = li.get_value(Basis.CONSOLIDATED, period_label="FY2024")
    assert got is not None and got.value == Decimal("1204")
    assert li.get_value(Basis.STANDALONE, period_label="FY2024").value == Decimal("1180")
    assert len(li.values) == 2
