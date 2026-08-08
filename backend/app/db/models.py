"""SQLAlchemy ORM models (persistence projection of the domain model).

Kept intentionally compact for this foundation: the entities the API needs now
(Document, versioned Template/Ontology, ExtractionRun). The full relational model
(Statement, LineItem, NotesTable, FaceNoteLink, ReviewItem, EditEvent, RuleResult,
Export) is documented in docs/architecture/02-data-model.md and lands with the
extraction persistence phase.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"
    # Dedup is per owner: two analysts uploading the same file each get their own document.
    __table_args__ = (UniqueConstraint("tenant_id", "owner", "content_hash", name="uq_doc_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), default="default")
    owner: Mapped[str] = mapped_column(String(128), default="", index=True)
    filename: Mapped[str] = mapped_column(String(512), default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    fmt: Mapped[str] = mapped_column(String(16), default="unknown")
    object_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    locale: Mapped[str | None] = mapped_column(String(8), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    integrity_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    runs: Mapped[list["ExtractionRun"]] = relationship(back_populates="document")


class TemplateVersion(Base):
    __tablename__ = "template_versions"
    __table_args__ = (UniqueConstraint("template_key", "version", name="uq_tpl_ver"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    template_key: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    definition: Mapped[dict] = mapped_column(JSON)
    is_published: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class OntologyVersion(Base):
    __tablename__ = "ontology_versions"
    __table_args__ = (UniqueConstraint("ontology_key", "version", name="uq_ont_ver"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ontology_key: Mapped[str] = mapped_column(String(128), index=True)
    target_template_key: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, default=1)
    definition: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    # Human-readable id: entity-slug + timestamp (see services.audit.make_run_id);
    # widened past a bare UUID to hold the entity prefix.
    id: Mapped[str] = mapped_column(String(96), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    template_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ontology_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_number: Mapped[int] = mapped_column(Integer, default=1)
    engine_version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    status: Mapped[str] = mapped_column(String(16), default="running")
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    logs: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    document: Mapped["Document"] = relationship(back_populates="runs")
