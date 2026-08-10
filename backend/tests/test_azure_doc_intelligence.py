"""Azure AI Document Intelligence OCR adapter: analyze-result parsing, config errors,
registration. The live REST call (analyze + poll) needs an Azure resource and can't run in
CI, so we test the pure mapping from an Azure analyze payload to the OcrProvider contract."""
from __future__ import annotations

import pytest

from app.adapters._structured import LlmConfigError
from app.adapters.azure_doc_intelligence import (
    AzureDocIntelligenceProvider,
    words_from_analyze_result,
)
from app.config import OcrSettings, Settings


def _payload() -> dict:
    # Page 100 wide × 40 high; three words on one line: "Trade", "receivables", "3410".
    return {
        "status": "succeeded",
        "analyzeResult": {
            "modelId": "prebuilt-layout",
            "pages": [
                {
                    "pageNumber": 1,
                    "width": 100.0,
                    "height": 40.0,
                    "unit": "pixel",
                    "angle": 0.0,
                    "words": [
                        {"content": "Trade", "polygon": [10, 8, 24, 8, 24, 12, 10, 12], "confidence": 0.98},
                        {"content": "receivables", "polygon": [26, 8, 52, 8, 52, 12, 26, 12], "confidence": 0.97},
                        {"content": "3410", "polygon": [80, 8, 92, 8, 92, 12, 80, 12], "confidence": 0.99},
                    ],
                }
            ],
        },
    }


def test_parses_words_with_normalized_bboxes():
    result = words_from_analyze_result(_payload())
    words = result["words"]
    assert [w["text"] for w in words] == ["Trade", "receivables", "3410"]
    first = words[0]["bbox"]
    assert first.x0 == pytest.approx(0.10) and first.x1 == pytest.approx(0.24)   # /100
    assert first.y0 == pytest.approx(0.20) and first.y1 == pytest.approx(0.30)   # /40
    assert all(0.0 <= w["bbox"].x0 <= 1.0 and 0.0 <= w["bbox"].y1 <= 1.0 for w in words)
    assert words[0]["confidence"] == pytest.approx(0.98)


def test_accepts_analyze_result_directly_and_legacy_boundingbox_key():
    ar = _payload()["analyzeResult"]
    ar["pages"][0]["words"][0]["boundingBox"] = ar["pages"][0]["words"][0].pop("polygon")
    result = words_from_analyze_result(ar)                       # unwrapped analyzeResult
    assert result["words"][0]["text"] == "Trade"                 # legacy key still parsed


def test_empty_or_pageless_payload_is_safe():
    assert words_from_analyze_result({})["words"] == []
    assert words_from_analyze_result({"analyzeResult": {"pages": []}})["words"] == []


def test_azure_words_feed_row_reconstruction():
    from app.core.models.enums import Basis
    from app.services.row_reconstruct import Word, build_line_items

    ocr = words_from_analyze_result(_payload())
    words = [Word(text=w["text"], bbox=w["bbox"]) for w in ocr["words"]]
    items, _ = build_line_items(words, page_index=0, document_id="d", source_kind="ocr")
    assert len(items) == 1
    assert items[0].source_label == "Trade receivables"
    val = items[0].get_value(Basis.CONSOLIDATED, period_label="current")
    assert val is not None and int(val.value) == 3410


def test_missing_endpoint_fails_loudly():
    settings = Settings()
    settings.ocr = OcrSettings(engine="azure", azure_endpoint="")
    with pytest.raises(LlmConfigError, match="endpoint is not set"):
        AzureDocIntelligenceProvider(settings)._config()


def test_missing_key_fails_loudly(monkeypatch):
    monkeypatch.delenv("AZURE_DI_KEY", raising=False)
    settings = Settings()
    settings.ocr = OcrSettings(engine="azure", azure_endpoint="https://x.cognitiveservices.azure.com")
    with pytest.raises(LlmConfigError, match="No Azure Document Intelligence key"):
        AzureDocIntelligenceProvider(settings)._config()


def test_azure_registered_in_registry():
    from app.ports.registry import registry

    assert registry.get("ocr", "azure").id == "azure"
    assert registry.get("ocr", "azure_document_intelligence").id == "azure"
