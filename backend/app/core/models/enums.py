"""Enumerations shared across the domain model."""
from __future__ import annotations

from enum import Enum


class DocFormat(str, Enum):
    PDF = "pdf"
    XLSX = "xlsx"
    XLS = "xls"
    IMAGE = "image"
    HTML = "html"
    UNKNOWN = "unknown"


class PageKind(str, Enum):
    """Classification of a page after the classify stage."""

    FACE = "face"            # face of a primary statement
    NOTES = "notes"
    OTHER = "other"
    COVER = "cover"
    AUDITOR_REPORT = "auditor_report"
    UNKNOWN = "unknown"


class PageSourceKind(str, Enum):
    """Whether a page's text is natively extractable or needs OCR."""

    NATIVE = "native"
    SCANNED = "scanned"
    MIXED = "mixed"


class StatementType(str, Enum):
    BALANCE_SHEET = "balance_sheet"
    PROFIT_AND_LOSS = "profit_and_loss"
    CASH_FLOW = "cash_flow"
    EQUITY_CHANGES = "equity_changes"


class Basis(str, Enum):
    """Consolidated vs standalone — both are extracted in one pass."""

    CONSOLIDATED = "consolidated"
    STANDALONE = "standalone"


class LineRole(str, Enum):
    LINE = "line"
    SUBTOTAL = "subtotal"
    TOTAL = "total"
    HEADER = "header"
    SPACER = "spacer"


class SignConvention(str, Enum):
    NATURAL = "natural"
    NATURAL_POSITIVE = "natural_positive"
    NATURAL_NEGATIVE = "natural_negative"
    DEBIT_POSITIVE = "debit_positive"
    CREDIT_POSITIVE = "credit_positive"
    CONTEXT = "context"


class ValueSource(str, Enum):
    MACHINE = "machine"
    HUMAN = "human"
    FORMULA = "formula"
    IMPORT = "import"


class ReconciliationRole(str, Enum):
    FACE_AGGREGATE = "face_aggregate"
    NOTE_DETAIL = "note_detail"
    NONE = "none"


class LinkRelationship(str, Enum):
    ONE_TO_ONE = "one_to_one"
    NOTE_SPLITS_TO_MANY_FACE = "note_splits_to_many_face"
    MANY_NOTES_TO_ONE_FACE = "many_notes_to_one_face"
    PARTIAL = "partial"


class Severity(str, Enum):
    BLOCKER = "blocker"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class MappingMethod(str, Enum):
    EXACT = "exact"
    RULE = "rule"
    FUZZY = "fuzzy"
    EMBEDDING = "embedding"
    LLM = "llm"
    UNMATCHED = "unmatched"
