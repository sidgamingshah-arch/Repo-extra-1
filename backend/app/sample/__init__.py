"""Seeded demo project (Reliance Industries Ind-AS FY2024-25).

This module encodes the illustrative dataset from the design handoff so the whole
product runs end-to-end against real API responses (statements, notes, review checks,
integrity, page scope, template/ontology, export) without requiring a real filing.
The figures are placeholder sample data, not sourced from an actual filing.

Uploaded documents flow through the real pipeline (ingest → integrity → scope); the
workspace/review/notes/export views are populated by this seeded project until the
OCR + table-reconstruction stages (scaffolded) produce live extracted values.
"""
from __future__ import annotations

from .demo import DEMO

__all__ = ["DEMO"]
