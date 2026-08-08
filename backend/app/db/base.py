"""SQLAlchemy base + session factory.

SQLite by default (zero-setup); swap ``FINEX_DATABASE_URL`` for Postgres in prod.
JSON columns hold the versioned template/ontology/integrity payloads. Alembic would
own DDL in prod; here ``init_db`` uses ``create_all`` to stay runnable out of the box.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
engine = create_engine(_settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def _reconcile_schema(eng: Engine) -> None:
    """Lightweight, idempotent forward-migration for an *existing* database.

    This app uses ``create_all`` (no Alembic), which never ALTERs a table that already
    exists — so a database created before a column/constraint was added would keep the old
    shape and break. Rather than force a manual DB reset, bring an existing ``documents``
    table up to the current model: add the ``owner`` column, and widen the dedup unique
    constraint to ``(tenant_id, owner, content_hash)`` so two owners can hold the same file.
    A brand-new database skips all of this (``create_all`` makes it current).
    """
    from app.db.models import Document

    insp = inspect(eng)
    if "documents" not in insp.get_table_names():
        return

    cols = {c["name"] for c in insp.get_columns("documents")}
    uniques = insp.get_unique_constraints("documents")
    has_owner = "owner" in cols
    owner_in_unique = any("owner" in (uc.get("column_names") or []) for uc in uniques)
    if has_owner and owner_in_unique:
        return  # already current

    with eng.begin() as conn:
        if not has_owner:
            conn.execute(text("ALTER TABLE documents ADD COLUMN owner VARCHAR(128) NOT NULL DEFAULT ''"))
        if not owner_in_unique:
            if eng.dialect.name == "sqlite":
                # SQLite can't alter a table-level UNIQUE in place → rebuild + copy.
                tmp = Document.__table__.to_metadata(MetaData(), name="documents_new")
                tmp.indexes.clear()  # avoid index-name clashes with the live table
                tmp.create(bind=conn)
                shared = [c.name for c in Document.__table__.columns
                          if c.name in {c["name"] for c in inspect(conn).get_columns("documents")}]
                collist = ", ".join(shared)
                conn.execute(text(f"INSERT INTO documents_new ({collist}) SELECT {collist} FROM documents"))
                conn.execute(text("DROP TABLE documents"))
                conn.execute(text("ALTER TABLE documents_new RENAME TO documents"))
            else:  # postgres / others
                conn.execute(text("ALTER TABLE documents DROP CONSTRAINT IF EXISTS uq_doc_hash"))
                conn.execute(text(
                    "ALTER TABLE documents ADD CONSTRAINT uq_doc_hash "
                    "UNIQUE (tenant_id, owner, content_hash)"
                ))


def init_db() -> None:
    # Import models so they are registered on Base.metadata before create_all.
    from app.db import models  # noqa: F401

    _reconcile_schema(engine)          # bring an existing DB up to the current model
    Base.metadata.create_all(bind=engine)  # create anything still missing (indexes, new tables)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
