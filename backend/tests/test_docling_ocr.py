"""Docling OCR adapter: word-splitting/normalization logic and lazy-import behaviour.

The Docling engine itself (models, layout) can't run in CI, so the actual conversion is
exercised elsewhere; here we test the pure mapping from Docling text items to the
OcrProvider word contract, and that selecting the adapter without the extra fails loudly.
"""
from __future__ import annotations

import pytest

from app.adapters._structured import LlmConfigError
from app.adapters.docling_ocr import DoclingOcrProvider, _split_into_words
from app.core.models.geometry import BBox


def _box(x0, x1):
    return BBox(x0=x0, y0=0.2, x1=x1, y1=0.24)


def test_single_word_keeps_the_whole_box():
    words = _split_into_words("Goodwill", _box(0.1, 0.3))
    assert len(words) == 1
    assert words[0]["text"] == "Goodwill"
    assert words[0]["bbox"].x0 == 0.1 and words[0]["bbox"].x1 == 0.3


def test_multi_word_line_is_split_left_to_right_within_the_box():
    box = _box(0.10, 0.50)
    words = _split_into_words("Trade receivables 3,410", box)
    assert [w["text"] for w in words] == ["Trade", "receivables", "3,410"]
    # words are ordered left→right and stay inside the original box
    xs = [w["bbox"].x0 for w in words]
    assert xs == sorted(xs)
    assert words[0]["bbox"].x0 >= box.x0
    assert words[-1]["bbox"].x1 <= box.x1 + 1e-9
    # y is shared (same visual line) → row grouping keeps them together
    assert all(w["bbox"].y0 == box.y0 and w["bbox"].y1 == box.y1 for w in words)


def test_split_words_feed_row_reconstruction():
    """The whole point: Docling line items, split into words, reconstruct into a line item
    with a label and a value (the same path native-PDF/PaddleOCR words take)."""
    from app.core.models.enums import Basis
    from app.services.row_reconstruct import Word, build_line_items

    ocr_words = _split_into_words("Trade receivables 3410", _box(0.10, 0.80))
    words = [Word(text=w["text"], bbox=w["bbox"]) for w in ocr_words]
    items, _ = build_line_items(words, page_index=0, document_id="d", source_kind="ocr")
    assert len(items) == 1
    assert items[0].source_label == "Trade receivables"
    val = items[0].get_value(Basis.CONSOLIDATED, period_label="current")
    assert val is not None and int(val.value) == 3410


def test_empty_text_yields_no_words():
    assert _split_into_words("   ", _box(0.1, 0.3)) == []


def test_selecting_docling_without_the_extra_fails_loudly():
    provider = DoclingOcrProvider()
    with pytest.raises(LlmConfigError, match="Docling is not installed"):
        provider._converter_or_raise()


def test_docling_registered_in_registry():
    from app.ports.registry import registry

    provider = registry.get("ocr", "docling")
    assert provider.id == "docling"
