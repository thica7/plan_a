from __future__ import annotations

from packages.enterprise.embedding_index import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, build_evidence_embedding_record
from packages.enterprise.postgres import EnterprisePostgresStore
from packages.schema.enterprise import EvidenceRecord


def evidence():
    return EvidenceRecord(id="evidence-1", workspace_id="workspace-1", project_id="project-1", raw_source_id="source-1", competitor_id="acme", dimension="pricing", source_type="webpage_verified", title="Acme pricing", snippet="企业定价每月二十九元", content_hash="hash")


class Connection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []
        self.committed = False
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        pass
    def cursor(self):
        return self
    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return self
    def fetchall(self):
        return self.rows
    def commit(self):
        self.committed = True


def store(connection):
    store = object.__new__(EnterprisePostgresStore)
    store.database_url = "postgresql://unused"
    store._dict_row = None
    store._connect = lambda *_args, **_kwargs: connection
    store._text = lambda text: text
    store._json = lambda value: value
    return store


def test_postgres_search_filters_model_dimension_and_scope():
    connection = Connection()
    result = store(connection).search_evidence(workspace_id="workspace-1", project_id="project-1", query="企业定价")
    assert result == []
    sql, params = connection.calls[0]
    assert "ee.embedding_model = %s" in sql
    assert "ee.embedding_dimensions = %s" in sql
    assert "e.workspace_id = %s" in sql and "e.project_id = %s" in sql
    assert EMBEDDING_MODEL in params and EMBEDDING_DIMENSIONS in params


def test_embedding_record_ids_change_with_model_version(monkeypatch):
    import packages.enterprise.embedding_index as index
    current = build_evidence_embedding_record(evidence())
    monkeypatch.setattr(index, "EMBEDDING_MODEL", "hashing-384")
    legacy = build_evidence_embedding_record(evidence())
    assert current.id != legacy.id


def test_postgres_scoped_reindex_replaces_old_embeddings_in_one_transaction():
    item = evidence()
    connection = Connection([item.model_dump()])
    repository = store(connection)
    repository._apply_embedding_dedupe = lambda _cur, evidence: evidence
    repository._upsert_evidence = lambda _cur, _item: None
    result = repository.reindex_evidence_embeddings(workspace_id=item.workspace_id, project_id=item.project_id)
    select, delete, insert = connection.calls
    assert "workspace_id = %s" in select[0] and "project_id = %s" in select[0]
    assert select[1] == (item.workspace_id, item.project_id)
    assert "DELETE FROM evidence_embeddings" in delete[0]
    assert "INSERT INTO evidence_embeddings" in insert[0]
    assert EMBEDDING_MODEL in insert[1]
    assert result.indexed_count == 1
    assert connection.committed is True
