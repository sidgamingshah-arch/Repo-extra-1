"""Azure AI Document Intelligence adapter for the OcrProvider port.

Azure AI Document Intelligence (the document-extraction service in Azure AI Foundry,
formerly Form Recognizer) does cloud layout + OCR + table structure. This adapter uses its
``prebuilt-layout`` / ``prebuilt-read`` model over the REST API (async analyze + poll) and
maps the returned words to the ``OcrProvider`` contract — word-level tokens with normalized
[0,1] top-left bounding boxes — so scanned pages feed the same ``row_reconstruct`` logic as
the native-PDF, Docling and PaddleOCR paths.

Config (``[ocr]`` in config.toml, ``FINEX_OCR__*`` env): ``engine = "azure"``,
``azure_endpoint``, ``azure_model``, ``azure_api_version``. The subscription key is read at
call time from the env var named by ``azure_api_key_env`` (default ``AZURE_DI_KEY``) — the
secret never lives in config or the UI, matching the LLM-key policy.

Uses ``httpx`` (already a dependency) — no vendor SDK required. Lazy: importing this module
touches no network and needs no key; a missing endpoint/key fails loudly on first use.
"""
from __future__ import annotations

import os
import time

from app.adapters._structured import LlmConfigError
from app.core.models.geometry import BBox
from app.ports.ocr import OcrResult, OcrWord

__all__ = ["AzureDocIntelligenceProvider", "words_from_analyze_result"]


def _bbox_from_polygon(poly: list[float], pw: float, ph: float) -> BBox | None:
    """An Azure polygon is 8 numbers (4 corner points, x,y). Reduce to an axis-aligned,
    normalized top-left box. Azure page coordinates share the page's own unit, so dividing
    by page width/height yields [0,1] regardless of pixels-vs-inches."""
    if not poly or len(poly) < 8 or pw <= 0 or ph <= 0:
        return None
    xs = poly[0::2]
    ys = poly[1::2]
    x0, x1 = min(xs) / pw, max(xs) / pw
    y0, y1 = min(ys) / ph, max(ys) / ph
    return BBox(
        x0=min(max(x0, 0.0), 1.0), y0=min(max(y0, 0.0), 1.0),
        x1=min(max(x1, 0.0), 1.0), y1=min(max(y1, 0.0), 1.0),
    )


def words_from_analyze_result(payload: dict) -> OcrResult:
    """Map an Azure Document Intelligence analyze result to the OcrProvider contract.

    Accepts either the full poll body (``{"status": ..., "analyzeResult": {...}}``) or the
    ``analyzeResult`` object directly. Uses the first page (this adapter OCRs one rasterized
    page per call). Supports both the ``polygon`` (current) and ``boundingBox`` (legacy)
    word geometry keys.
    """
    ar = payload.get("analyzeResult", payload)
    pages = ar.get("pages") or []
    if not pages:
        return {"words": [], "angle": 0.0}
    page = pages[0]
    pw = float(page.get("width") or 0.0)
    ph = float(page.get("height") or 0.0)
    angle = float(page.get("angle") or 0.0)

    words: list[OcrWord] = []
    for w in page.get("words", []) or []:
        text = (w.get("content") or "").strip()
        if not text:
            continue
        poly = w.get("polygon") or w.get("boundingBox")
        box = _bbox_from_polygon(poly, pw, ph)
        if box is None:
            continue
        words.append({"text": text, "bbox": box, "confidence": float(w.get("confidence", 1.0))})
    return {"words": words, "angle": angle}


class AzureDocIntelligenceProvider:
    id = "azure"

    def __init__(self, settings=None):
        from app.config import get_settings

        self._settings = settings or get_settings()

    def _config(self) -> tuple[str, str, str, str]:
        ocr = self._settings.ocr
        endpoint = (ocr.azure_endpoint or "").rstrip("/")
        if not endpoint:
            raise LlmConfigError(
                "Azure Document Intelligence endpoint is not set. Configure "
                "config.toml [ocr].azure_endpoint (or FINEX_OCR__AZURE_ENDPOINT)."
            )
        key = os.environ.get(ocr.azure_api_key_env)
        if not key:
            raise LlmConfigError(
                f"No Azure Document Intelligence key found. Set the {ocr.azure_api_key_env} "
                f"environment variable (configured via config.toml [ocr].azure_api_key_env)."
            )
        return endpoint, key, ocr.azure_model, ocr.azure_api_version

    def recognize(self, image_bytes: bytes, *, lang: str = "en") -> OcrResult:  # pragma: no cover - needs Azure + network
        import httpx

        endpoint, key, model, api_version = self._config()
        url = f"{endpoint}/documentintelligence/documentModels/{model}:analyze"
        headers = {"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/octet-stream"}
        with httpx.Client(timeout=60.0) as client:
            started = client.post(url, params={"api-version": api_version},
                                  headers=headers, content=image_bytes)
            started.raise_for_status()
            op = started.headers.get("operation-location") or started.headers.get("Operation-Location")
            if not op:
                raise LlmConfigError("Azure analyze did not return an Operation-Location to poll.")
            for _ in range(60):
                poll = client.get(op, headers={"Ocp-Apim-Subscription-Key": key})
                poll.raise_for_status()
                body = poll.json()
                status = body.get("status")
                if status == "succeeded":
                    return words_from_analyze_result(body)
                if status == "failed":
                    raise LlmConfigError(f"Azure analyze failed: {body.get('error')}")
                time.sleep(1.0)
            raise LlmConfigError("Azure analyze timed out waiting for the result.")

    def detect_orientation(self, image_bytes: bytes) -> float:
        return 0.0
