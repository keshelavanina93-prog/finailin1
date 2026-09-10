from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from finai_api.services import ontology_connections as graph


def test_graph_keeps_pinned_versions_and_omits_invisible_targets(monkeypatch):
    source, target, hidden = uuid4(), uuid4(), uuid4()
    source_version, prior_version, latest_version = uuid4(), uuid4(), uuid4()
    nodes = [
        SimpleNamespace(resource_id=source, version_id=source_version, object_type="Ledger"),
        SimpleNamespace(resource_id=target, version_id=latest_version, object_type="LegalEntity"),
    ]
    rows = [
        (source, source_version, target, prior_version, "FIELD:legal_entity_id"),
        (source, source_version, hidden, uuid4(), "FIELD:currency_id"),
    ]

    @contextmanager
    def connection(_principal):
        yield SimpleNamespace(execute=lambda *_args: SimpleNamespace(fetchall=lambda: rows))

    monkeypatch.setattr(graph, "resource_connection", connection)
    principal = SimpleNamespace(scope=SimpleNamespace(tenant_id=uuid4()))
    result = graph.connections(principal, nodes)
    assert len(result) == 1
    assert result[0]["state"] == "PINNED_PRIOR_VERSION"
    assert result[0]["target_version"] == str(prior_version)
    nodes[1].version_id = prior_version
    assert graph.connections(principal, nodes)[0]["state"] == "CURRENT"


def test_source_connections_do_not_expose_evidence_without_export():
    assert graph.source_connections(SimpleNamespace(permissions=["ontology_read", "read"])) == []
