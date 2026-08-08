"""Startup schema reconciliation: an existing DB from before the `owner` column/constraint
is migrated forward in place, without a manual reset."""
from __future__ import annotations

from sqlalchemy import create_engine, inspect, text


def _old_documents_ddl() -> str:
    # The pre-owner schema: unique on (tenant_id, content_hash), no `owner`.
    return (
        "CREATE TABLE documents ("
        " id VARCHAR(36) PRIMARY KEY,"
        " tenant_id VARCHAR(36) DEFAULT 'default',"
        " filename VARCHAR(512) DEFAULT '',"
        " content_hash VARCHAR(64),"
        " byte_size INTEGER DEFAULT 0,"
        " fmt VARCHAR(16) DEFAULT 'unknown',"
        " object_key VARCHAR(128),"
        " status VARCHAR(32) DEFAULT 'uploaded',"
        " locale VARCHAR(8),"
        " page_count INTEGER DEFAULT 0,"
        " integrity_report JSON,"
        " created_at DATETIME,"
        " CONSTRAINT uq_doc_hash UNIQUE (tenant_id, content_hash)"
        ")"
    )


def test_reconcile_adds_owner_and_widens_unique(tmp_path):
    from app.db.base import Base, _reconcile_schema

    db = tmp_path / "old.db"
    eng = create_engine(f"sqlite:///{db}", future=True)

    # Simulate a database created by the previous version, with one existing row.
    with eng.begin() as conn:
        conn.execute(text(_old_documents_ddl()))
        conn.execute(text(
            "INSERT INTO documents (id, tenant_id, content_hash, object_key, created_at) "
            "VALUES ('d1', 'default', 'abc', 'k1', '2024-01-01 00:00:00')"
        ))

    # Forward-migrate, then create_all fills in the rest (indexes, other tables).
    _reconcile_schema(eng)
    Base.metadata.create_all(bind=eng)

    cols = {c["name"] for c in inspect(eng).get_columns("documents")}
    assert "owner" in cols                                   # column added

    with eng.begin() as conn:
        # Existing row survived (owner backfilled to '').
        owner = conn.execute(text("SELECT owner FROM documents WHERE id='d1'")).scalar()
        assert owner == ""
        # The widened constraint lets two different owners hold the same content_hash.
        full = ("INSERT INTO documents "
                "(id, tenant_id, owner, filename, content_hash, byte_size, fmt, object_key, "
                " status, page_count, created_at) VALUES "
                "(:id, 'default', :owner, 'f.pdf', 'xyz', 0, 'pdf', :key, 'ok', 0, '2024-01-02 00:00:00')")
        conn.execute(text(full), {"id": "d2", "owner": "alice", "key": "k2"})
        conn.execute(text(full), {"id": "d3", "owner": "bob", "key": "k3"})

    uniques = inspect(eng).get_unique_constraints("documents")
    assert any("owner" in (uc.get("column_names") or []) for uc in uniques)


def test_reconcile_is_idempotent_on_current_schema(tmp_path):
    """Running against an already-current DB is a no-op (safe to call every startup)."""
    from app.db.base import Base, _reconcile_schema

    eng = create_engine(f"sqlite:///{tmp_path / 'new.db'}", future=True)
    import app.db.models  # noqa: F401 — register tables
    Base.metadata.create_all(bind=eng)
    _reconcile_schema(eng)   # should not raise or change anything
    _reconcile_schema(eng)
    cols = {c["name"] for c in inspect(eng).get_columns("documents")}
    assert "owner" in cols
