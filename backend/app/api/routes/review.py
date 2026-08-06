"""Review-queue endpoints (contract stub).

The queue is populated by the validation stage (RuleResult → ReviewItem), which lands
with the extraction-persistence phase. The routes define the shape now so the frontend
can build against them.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["review"])


@router.get("/extractions/{run_id}/review")
def list_review_items(run_id: str, status: str = "open") -> dict:
    return {"run_id": run_id, "status_filter": status, "items": []}
