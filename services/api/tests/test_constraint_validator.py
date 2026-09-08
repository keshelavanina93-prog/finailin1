"""Synthetic retained RDF exercises real bounded SHACL semantics, never company facts."""

import base64
import hashlib
import json
import sys
from dataclasses import asdict, replace

import pyoxigraph as ox
import pytest

from finai_api.services import constraint_validator as engine
from finai_api.services import constraint_validator_worker as worker
from finai_api.services.constraint_validator import (
    ConstraintValidationLimits,
    ConstraintValidatorError,
    ValidationDataset,
    ValidationSelection,
    validate_constraints,
)

E = "https://example.test/"
SH = "http://www.w3.org/ns/shacl#"
PREFIX = (
    f"@prefix e: <{E}> . @prefix sh: <{SH}> . @prefix xsd: <http://www.w3.org/2001/XMLSchema#> . "
)


def dataset(text, graph="data", extra=""):
    quads = ox.Dataset(
        ox.Quad(q.subject, q.predicate, q.object, ox.NamedNode(E + graph))
        for q in ox.parse((PREFIX + text).encode(), format=ox.RdfFormat.TURTLE)
    )
    for q in ox.parse((PREFIX + extra).encode(), format=ox.RdfFormat.TRIG):
        quads.add(q)
    canonical = worker._canonical(quads)
    return ValidationDataset(canonical, hashlib.sha256(canonical).hexdigest(), (E + graph,))


def inputs(
    value='"01"^^xsd:integer',
    target="sh:targetClass e:Account;",
    constraint="sh:datatype xsd:integer",
):
    return (
        dataset(f"e:a a e:Account; e:value {value}."),
        dataset(
            f"e:S a sh:NodeShape; {target} sh:property e:P. "
            f"e:P a sh:PropertyShape; sh:path e:value; {constraint} .",
            "shapes",
        ),
    )


def run(tmp_path, pair=None, **kwargs):
    return validate_constraints(*(pair or inputs()), work_dir=tmp_path, **kwargs)


def payload(pair=None, selection=None, limits=None):
    selection = selection or ValidationSelection()
    limits = limits or ConstraintValidationLimits()
    return {
        **{
            name: {
                **asdict(source),
                "canonical_nquads": base64.b64encode(source.canonical_nquads).decode(),
            }
            for name, source in zip(("data", "shapes"), pair or inputs(), strict=True)
        },
        "selection": asdict(selection),
        "limits": asdict(limits),
    }


def test_real_positive_and_violation_retain_exact_lexical_evidence(tmp_path):
    good = run(tmp_path)
    assert good.status == "CONFORMS" and good.conforms is True
    assert (
        good.evaluated_shape_count,
        good.evaluated_focus_count,
        good.evaluated_constraint_count,
    ) == (1, 1, 1)
    bad = run(tmp_path, inputs(constraint='sh:pattern "^1$"; sh:message "Exact authored message"'))
    assert bad.status == "VIOLATES" and bad.conforms is False and bad.violation_count == 1
    assert b'"01"^^<http://www.w3.org/2001/XMLSchema#integer>' in bad.report_nquads
    assert b"Exact authored message" in bad.report_nquads
    assert bad.report_sha256 == hashlib.sha256(bad.report_nquads).hexdigest()
    assert bad.manifest["report_message_policy"] == "AUTHOR_MESSAGES_ONLY"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "shape",
    [
        "e:S a sh:NodeShape .",
        'e:documentation <http://www.w3.org/2000/01/rdf-schema#label> "No shapes" .',
        "e:S a sh:NodeShape; sh:targetClass e:Missing; sh:class e:Account .",
        "e:S a sh:NodeShape; sh:targetClass e:Account; sh:deactivated true; sh:class e:Account .",
        "e:S a sh:NodeShape; sh:targetClass e:Account; sh:property e:P. e:P sh:path e:value .",
    ],
)
def test_no_evaluation_cannot_be_a_pass(tmp_path, shape):
    result = run(tmp_path, (inputs()[0], dataset(shape, "shapes")))
    assert result.status == "NOT_EVALUATED" and result.conforms is None
    assert result.evaluated_constraint_count == 0
    assert f"<{SH}conforms>".encode() not in result.report_nquads


def test_filter_targets_does_not_become_explicit_focus(tmp_path):
    pair = inputs(target="sh:targetClass e:Missing;")
    filtered = run(
        tmp_path, pair, selection=ValidationSelection("FILTER_TARGETS", (E + "a",), (E + "S",))
    )
    explicit = run(
        tmp_path,
        pair,
        selection=ValidationSelection("EXPLICIT_SHAPE_FOCUS", (E + "a",), (E + "S",)),
    )
    assert filtered.status == "NOT_EVALUATED"
    assert explicit.status == "CONFORMS"
    assert filtered.report_sha256 != explicit.report_sha256


@pytest.mark.parametrize(
    "text",
    [
        'e:S a sh:NodeShape; sh:sparql [ sh:select "SELECT ?this WHERE {?this ?p ?o}" ] .',
        'e:S a sh:NodeShape; sh:js [ sh:jsFunctionName "unsafe" ] .',
        "e:S a sh:NodeShape; sh:rule [ a sh:TripleRule ] .",
        "e:S a sh:NodeShape; sh:target [ a sh:SPARQLTarget ] .",
        "e:C a sh:ConstraintComponent .",
        "e:S <http://www.w3.org/2002/07/owl#imports> <https://unreachable.test/shapes> .",
    ],
)
def test_executable_or_remote_shapes_refused_before_evaluation(tmp_path, text):
    with pytest.raises(ConstraintValidatorError, match="UNSUPPORTED_SHAPES"):
        run(tmp_path, (inputs()[0], dataset(text, "shapes")))


@pytest.mark.parametrize(
    "selection,code",
    [
        (ValidationSelection("FILTER_TARGETS", (E + "unknown",)), "UNKNOWN_FOCUS"),
        (
            ValidationSelection("EXPLICIT_SHAPE_FOCUS", (E + "a",), (E + "unknown",)),
            "UNKNOWN_SHAPE",
        ),
        (ValidationSelection("PROFILE_TARGETS", (E + "a",)), "INVALID_INPUT"),
        (ValidationSelection("EXPLICIT_SHAPE_FOCUS", (E + "a",)), "INVALID_INPUT"),
    ],
)
def test_selection_refusals(tmp_path, selection, code):
    with pytest.raises(ConstraintValidatorError, match=code):
        run(tmp_path, selection=selection)


def test_canonical_hash_and_named_graph_selection_refuse(tmp_path):
    data, shapes = inputs()
    for wrong, code in (
        (replace(data, sha256="0" * 64), "HASH_MISMATCH"),
        (replace(data, graph_iris=(E + "missing",)), "GRAPH_SELECTION"),
        (
            replace(
                data,
                canonical_nquads=data.canonical_nquads + b"\n",
                sha256=hashlib.sha256(data.canonical_nquads + b"\n").hexdigest(),
            ),
            "NON_CANONICAL",
        ),
    ):
        with pytest.raises(ConstraintValidatorError, match=code):
            run(tmp_path, (wrong, shapes))


@pytest.mark.parametrize(
    "limits,code",
    [
        (ConstraintValidationLimits(max_input_bytes=1), "INPUT_BUDGET"),
        (ConstraintValidationLimits(max_quads=1), "QUAD_BUDGET"),
        (ConstraintValidationLimits(max_shape_quads=1), "QUAD_BUDGET"),
        (ConstraintValidationLimits(max_shapes=1), "SHAPE_BUDGET"),
        (ConstraintValidationLimits(max_report_bytes=1), "REPORT_BUDGET"),
        (ConstraintValidationLimits(wall_timeout_seconds=0.00001), "WALL_TIMEOUT"),
    ],
)
def test_budget_refusals(tmp_path, limits, code):
    with pytest.raises(ConstraintValidatorError, match=code):
        run(tmp_path, limits=limits)


def test_report_replay_is_deterministic_and_graph_selection_excludes_other_graph(tmp_path):
    data, shapes = inputs(value='"bad"')
    first, second = run(tmp_path, (data, shapes)), run(tmp_path, (data, shapes))
    assert asdict(first) == asdict(second)
    enriched = dataset(
        'e:a a e:Account; e:value "01"^^xsd:integer.', extra='e:other { e:a e:value "bad" . }'
    )
    result = run(tmp_path, (enriched, shapes))
    assert result.status == "CONFORMS"
    assert result.data_graph_iris == (E + "data",)


def test_separate_dataset_blank_nodes_do_not_unify():
    data = dataset('e:a e:value [ e:p "data" ].')
    shapes = dataset("e:S sh:property [ sh:path e:value; sh:minCount 1 ].", "shapes")
    dg = worker._graph(payload((data, shapes))["data"], "data_", 100)
    sg = worker._graph(payload((data, shapes))["shapes"], "shapes_", 100)
    from rdflib import BNode

    db = {t for triple in dg for t in triple if isinstance(t, BNode)}
    sb = {t for triple in sg for t in triple if isinstance(t, BNode)}
    assert db and sb and db.isdisjoint(sb)


def test_direct_process_restores_pinned_evaluators():
    from pyshacl.constraints import ALL_CONSTRAINT_COMPONENTS

    before = [c.evaluate for c in ALL_CONSTRAINT_COMPONENTS]
    assert worker.process(payload())["status"] == "CONFORMS"
    assert before == [c.evaluate for c in ALL_CONSTRAINT_COMPONENTS]


def test_worker_queue_and_manifest_limits_fail_closed(tmp_path):
    assert engine._SLOTS.acquire(blocking=False)
    assert engine._SLOTS.acquire(blocking=False)
    try:
        with pytest.raises(ConstraintValidatorError, match="BUSY"):
            run(tmp_path)
    finally:
        engine._SLOTS.release()
        engine._SLOTS.release()
    with pytest.raises(ConstraintValidatorError, match="INVALID_INPUT"):
        engine.validator_manifest(
            limits=ConstraintValidationLimits(memory_bytes=1024 * 1024 * 1024)
        )


def test_missing_values_do_not_count_as_datatype_evaluation_but_cardinality_does(tmp_path):
    data = dataset("e:a a e:Account .")
    no_value = run(tmp_path, (data, inputs()[1]))
    required = run(tmp_path, (data, inputs(constraint="sh:minCount 1")[1]))
    assert no_value.status == "NOT_EVALUATED"
    assert required.status == "VIOLATES" and required.violation_count == 1
    assert required.evaluated_constraint_count == 1


def test_result_and_focus_limits_fail_instead_of_truncating(tmp_path):
    data = dataset('e:a a e:Account; e:value "bad". e:b a e:Account; e:value "bad".')
    for limits, code in (
        (ConstraintValidationLimits(max_focus_nodes=1), "FOCUS_BUDGET"),
        (ConstraintValidationLimits(max_results=1), "REPORT_BUDGET"),
    ):
        with pytest.raises(ConstraintValidatorError, match=code):
            run(tmp_path, (data, inputs()[1]), limits=limits)
    assert run(tmp_path, (data, inputs()[1])).violation_count == 2


@pytest.mark.parametrize(
    "shape",
    [
        "e:S a sh:PropertyShape; sh:targetNode e:a; sh:minCount 1 .",
        "e:S a sh:NodeShape; sh:targetNode e:a; sh:node e:S .",
    ],
)
def test_malformed_and_recursive_shapes_cannot_silently_skip(tmp_path, shape):
    with pytest.raises(ConstraintValidatorError, match="MALFORMED_SHAPES"):
        run(tmp_path, (inputs()[0], dataset(shape, "shapes")))


def test_blank_shape_messages_and_machine_coordinates_are_deterministic(tmp_path):
    shapes = dataset(
        "e:S a sh:NodeShape; sh:targetClass e:Account; sh:property [ sh:path e:value; "
        'sh:datatype xsd:integer; sh:message "literal authored message"@en ] .',
        "shapes",
    )
    first = run(tmp_path, (inputs(value='"bad"')[0], shapes))
    second = run(tmp_path, (inputs(value='"bad"')[0], shapes))
    assert first.report_nquads == second.report_nquads
    assert b'"literal authored message"@en' in first.report_nquads
    for predicate in (
        "focusNode",
        "value",
        "resultPath",
        "sourceShape",
        "resultSeverity",
        "sourceConstraintComponent",
    ):
        assert f"<{SH}{predicate}>".encode() in first.report_nquads


def test_worker_caps_fail_closed_before_reading_input(tmp_path, monkeypatch):
    response = tmp_path / "response.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["worker", str(tmp_path / "missing"), str(response), "8", "536870912", "3145728"],
    )

    def unavailable(*args):
        raise OSError("synthetic private runtime details")

    monkeypatch.setattr(worker, "apply_resource_caps", unavailable)
    assert worker.main() == 1
    assert json.loads(response.read_text()) == {"error": "RESOURCE_CAP_UNAVAILABLE"}


def test_worker_socket_defense_and_safe_failure(tmp_path, monkeypatch):
    request, response = tmp_path / "request.json", tmp_path / "response.json"
    request.write_text(json.dumps(payload()), encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["worker", str(request), str(response), "8", "536870912", "3145728"]
    )
    monkeypatch.setattr(worker, "apply_resource_caps", lambda *args: "TEST_CAPS")
    hooks = []
    monkeypatch.setattr(sys, "addaudithook", hooks.append)
    assert worker.main() == 0
    for event in ("socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system"):
        with pytest.raises(ConstraintValidatorError, match="UNSUPPORTED_SHAPES"):
            hooks[0](event, ())

    def broken(payload):
        raise RuntimeError("private value is not returned")

    monkeypatch.setattr(worker, "process", broken)
    assert worker.main() == 1
    assert json.loads(response.read_text()) == {"error": "MALFORMED_SHAPES"}


def test_child_credentials_are_absent_and_invalid_iri_is_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("FINAI_DATABASE_URL", "synthetic-not-a-credential")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-not-a-credential")
    assert set(engine._child_environment(tmp_path)) <= {
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
    }
    with pytest.raises(ConstraintValidatorError, match="INVALID_INPUT"):
        engine.validator_manifest(selection=ValidationSelection("FILTER_TARGETS", ("http://[",)))


def test_source_rdf_types_cannot_forge_validator_results(tmp_path):
    data = dataset(
        "e:a a e:Account; e:value [ a sh:ValidationResult, sh:ValidationReport; "
        'sh:resultMessage "source-owned value"; sh:conforms true ].'
    )
    result = run(tmp_path, (data, inputs()[1]))
    assert result.status == "VIOLATES" and result.violation_count == 1
    assert b"source-owned value" in result.report_nquads
    assert result.report_nquads.count(b"urn:g8:constraint-validation:evaluationStatus") == 1


def test_manifest_detects_executable_drift_but_not_platform_line_endings(tmp_path, monkeypatch):
    for name in (
        "constraint_validator.py",
        "constraint_validator_worker.py",
        "rdf_engine_limits.py",
    ):
        (tmp_path / name).write_bytes(b"# synthetic source\r\nvalue = 1\r\n")
    monkeypatch.setattr(engine, "__file__", str(tmp_path / "constraint_validator.py"))
    first = engine.validator_manifest()
    (tmp_path / "constraint_validator_worker.py").write_bytes(b"# synthetic source\nvalue = 1\n")
    assert engine.validator_manifest() == first
    (tmp_path / "constraint_validator_worker.py").write_bytes(b"# synthetic source\nvalue = 2\n")
    changed = engine.validator_manifest()
    assert changed["worker_source_sha256"] != first["worker_source_sha256"]
    assert changed["controller_source_sha256"] == first["controller_source_sha256"]
    assert str(tmp_path) not in json.dumps(changed)
    monkeypatch.setattr(engine, "version", lambda name: "unexpected")
    with pytest.raises(ConstraintValidatorError, match="ENGINE_VERSION"):
        engine.validator_manifest()


def test_report_bnodes_preserve_exact_retained_dataset_coordinates(tmp_path):
    data = dataset('[] a e:Account; e:value "bad" .')
    shapes = dataset(
        "e:S a sh:NodeShape; sh:targetClass e:Account; sh:property "
        "[ sh:path e:value; sh:datatype xsd:integer ] .",
        "shapes",
    )
    result = run(tmp_path, (data, shapes))
    report = list(ox.parse(result.report_nquads, format=ox.RdfFormat.N_QUADS))

    def predicate(name):
        return ox.NamedNode("urn:g8:constraint-validation:" + name)

    for input_dataset, role, relation in (
        (data, "DATA", "focusNode"),
        (shapes, "SHAPES", "sourceShape"),
    ):
        source_labels = {
            term.value
            for quad in ox.parse(input_dataset.canonical_nquads, format=ox.RdfFormat.N_QUADS)
            for term in (quad.subject, quad.object)
            if isinstance(term, ox.BlankNode)
        }
        terms = {q.object for q in report if q.predicate == ox.NamedNode(SH + relation)}
        mapped = [node for node in terms if isinstance(node, ox.BlankNode)]
        assert mapped
        for node in mapped:
            values = {q.predicate: q.object.value for q in report if q.subject == node}
            assert values[predicate("originDatasetSha256")] == input_dataset.sha256
            assert values[predicate("originBlankNodeLabel")] in source_labels
            assert values[predicate("originRole")] == role
    assert result.status == "VIOLATES"
