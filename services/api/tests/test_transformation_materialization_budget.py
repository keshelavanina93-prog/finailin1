"""Admission reserves the reviewed complete-set bound, not only the first page."""

from types import SimpleNamespace

import pytest

from finai_api.services.transformation_definitions import estimate_work
from finai_api.services.workspace import WorkspaceError


def node(limit=200, materialized=True, capable=True):
    plan = {
        "request": {"limit": limit},
        "derived_properties": [],
        "implementation": {
            "implementation_id": "ontology.object-set-derived/v1",
            "maximum_rows": 200, "maximum_properties": 8,
        },
    }
    if capable:
        plan["implementation"].update(
            maximum_materialized_rows=1000, maximum_materialized_pages=10
        )
    if materialized:
        plan["materialization"] = {"max_objects": 300, "max_pages": 2}
    return {"function_plan": plan}


def budget(rows):
    return SimpleNamespace(
        resource_budget=SimpleNamespace(max_returned_rows=rows, max_derived_evaluations=0)
    )


def test_reserves_complete_set_bounds_for_source_and_retained_consumer():
    assert estimate_work(budget(600), [node(), node()]) == {
        "returned_rows": 600, "derived_evaluations": 0
    }
    with pytest.raises(WorkspaceError, match="returned-row budget"):
        estimate_work(budget(599), [node(), node()])


def test_admits_only_declared_page_capacity_and_keeps_legacy_page_bounds():
    assert estimate_work(budget(400), [node(limit=100), node(limit=100)]) == {
        "returned_rows": 400, "derived_evaluations": 0
    }
    assert estimate_work(budget(80), [node(40, False), node(40, False)]) == {
        "returned_rows": 80, "derived_evaluations": 0
    }
    with pytest.raises(WorkspaceError, match="does not support"):
        estimate_work(budget(600), [node(capable=False)])
