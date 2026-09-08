"""Private one-shot worker. Pinned core instrumentation is scoped to one evaluation."""

import base64
import hashlib
import inspect
import json
import sys
import warnings
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from finai_api.services.constraint_validator import (
    ConstraintValidationLimits,
    ConstraintValidatorError,
    ValidationSelection,
    validator_manifest,
)
from finai_api.services.rdf_engine_limits import apply_resource_caps

SH = "http://www.w3.org/ns/shacl#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
G8 = "urn:g8:constraint-validation:"
_CORE = set(
    [
        "class",
        "datatype",
        "nodeKind",
        "minCount",
        "maxCount",
        "minExclusive",
        "minInclusive",
        "maxExclusive",
        "maxInclusive",
        "not",
        "and",
        "or",
        "xone",
        "minLength",
        "maxLength",
        "pattern",
        "flags",
        "languageIn",
        "uniqueLang",
        "equals",
        "disjoint",
        "lessThan",
        "lessThanOrEquals",
        "node",
        "property",
        "qualifiedValueShape",
        "qualifiedMinCount",
        "qualifiedMaxCount",
        "qualifiedValueShapesDisjoint",
        "closed",
        "ignoredProperties",
        "hasValue",
        "in",
        "targetClass",
        "targetNode",
        "targetSubjectsOf",
        "targetObjectsOf",
        "path",
        "inversePath",
        "alternativePath",
        "zeroOrMorePath",
        "oneOrMorePath",
        "zeroOrOnePath",
        "deactivated",
        "severity",
        "message",
        "name",
        "description",
        "order",
        "group",
        "defaultValue",
    ]
)
_STRUCTURAL = {
    "PropertyConstraintComponent",
    "NodeConstraintComponent",
    "AndConstraintComponent",
    "OrConstraintComponent",
    "XoneConstraintComponent",
    "NotConstraintComponent",
}
_VALUE_BASED = {
    "ClassConstraintComponent",
    "DatatypeConstraintComponent",
    "NodeKindConstraintComponent",
    "MinExclusiveConstraintComponent",
    "MinInclusiveConstraintComponent",
    "MaxExclusiveConstraintComponent",
    "MaxInclusiveConstraintComponent",
    "MinLengthConstraintComponent",
    "MaxLengthConstraintComponent",
    "PatternConstraintComponent",
    "LanguageInConstraintComponent",
    "InConstraintComponent",
}


def _canonical(dataset: Any) -> bytes:
    import pyoxigraph as ox

    dataset.canonicalize(ox.CanonicalizationAlgorithm.RDFC_1_0)
    content = ox.serialize(dataset, format=ox.RdfFormat.N_QUADS)
    if not isinstance(content, bytes):
        raise ConstraintValidatorError("WORKER_FAILED")
    return b"".join(line + b"\n" for line in sorted(content.split(b"\n")) if line)


def _graph(
    source: dict,
    prefix: str,
    maximum: int,
    origins: dict[Any, tuple[str, str, str]] | None = None,
    origin_role: str = "",
) -> Any:
    import pyoxigraph as ox
    from rdflib import BNode, Graph, Literal, URIRef

    content = base64.b64decode(source["canonical_nquads"], validate=True)
    if hashlib.sha256(content).hexdigest() != source["sha256"]:
        raise ConstraintValidatorError("HASH_MISMATCH")
    dataset = ox.Dataset()
    graph_names: set[str] = set()
    try:
        for count, quad in enumerate(ox.parse(content, format=ox.RdfFormat.N_QUADS), 1):
            if count > maximum:
                raise ConstraintValidatorError("QUAD_BUDGET")
            if (
                not isinstance(quad.graph_name, ox.NamedNode)
                or not isinstance(quad.subject, (ox.NamedNode, ox.BlankNode))
                or not isinstance(quad.object, (ox.NamedNode, ox.BlankNode, ox.Literal))
                or (isinstance(quad.object, ox.Literal) and quad.object.direction is not None)
            ):
                raise ConstraintValidatorError("NON_CANONICAL")
            graph_names.add(quad.graph_name.value)
            dataset.add(quad)
    except SyntaxError:
        raise ConstraintValidatorError("NON_CANONICAL") from None
    if _canonical(dataset) != content:
        raise ConstraintValidatorError("NON_CANONICAL")
    if not set(source["graph_iris"]).issubset(graph_names):
        raise ConstraintValidatorError("GRAPH_SELECTION")

    def term(value: Any) -> Any:
        if isinstance(value, ox.NamedNode):
            return URIRef(value.value)
        if isinstance(value, ox.BlankNode):
            node = BNode(prefix + value.value)
            if origins is not None:
                origins[node] = (source["sha256"], value.value, origin_role)
            return node
        return Literal(
            value.value,
            lang=value.language,
            datatype=URIRef(value.datatype.value) if not value.language else None,
            normalize=False,
        )

    graph = Graph()
    for quad in dataset:
        if quad.graph_name.value in source["graph_iris"]:
            graph.add((term(quad.subject), term(quad.predicate), term(quad.object)))
    return graph


def _supported(graph: Any) -> None:
    from rdflib import URIRef

    for _, predicate, value in graph:
        if str(predicate).startswith(SH) and str(predicate)[len(SH) :] not in _CORE:
            raise ConstraintValidatorError("UNSUPPORTED_SHAPES")
        if predicate == URIRef("http://www.w3.org/2002/07/owl#imports"):
            raise ConstraintValidatorError("UNSUPPORTED_SHAPES")
        if (
            str(value).startswith(SH)
            and predicate == URIRef(RDF + "type")
            and str(value)[len(SH) :] not in {"NodeShape", "PropertyShape"}
        ):
            raise ConstraintValidatorError("UNSUPPORTED_SHAPES")
        if value == URIRef(SH + "ConstraintComponent"):
            raise ConstraintValidatorError("UNSUPPORTED_SHAPES")


def _evaluate(
    data: Any, shapes: Any, selection: ValidationSelection, limits: ConstraintValidationLimits
) -> tuple[bool, Any, set, set]:
    import pyshacl
    from pyshacl.constraints import ALL_CONSTRAINT_COMPONENTS
    from pyshacl.entrypoints import meta_validate
    from pyshacl.shape import Shape
    from pyshacl.shapes_graph import ShapesGraph
    from rdflib import URIRef

    # Meta-validation is deliberately outside the coverage observation window.
    meta_ok, _, _ = meta_validate(
        shapes, inference="none", do_owl_imports=False, advanced=False, js=False, sparql_mode=False
    )
    if not meta_ok:
        raise ConstraintValidatorError("MALFORMED_SHAPES")
    discovered = list(ShapesGraph(shapes).shapes)
    if len(discovered) > limits.max_shapes:
        raise ConstraintValidatorError("SHAPE_BUDGET")
    known = {s.node for s in discovered}
    if any(URIRef(iri) not in known for iri in selection.shape_iris):
        raise ConstraintValidatorError("UNKNOWN_SHAPE")
    present = set(data.subjects()) | set(data.objects())
    if any(URIRef(iri) not in present for iri in selection.focus_iris):
        raise ConstraintValidatorError("UNKNOWN_FOCUS")
    components = [c for c in ALL_CONSTRAINT_COMPONENTS if ".core." in c.__module__]
    if len(components) != 28 or any(
        list(inspect.signature(c.evaluate).parameters)
        != [
            "self",
            "executor",
            "datagraph" if c.__name__ == "NotConstraintComponent" else "target_graph",
            "focus_value_nodes",
            "_evaluation_path",
        ]
        for c in components
    ):
        raise ConstraintValidatorError("ENGINE_VERSION")
    completed: set[tuple[Any, Any, str]] = set()
    seen_focus: set[Any] = set()
    originals = {c: c.evaluate for c in components}
    original_targets = Shape.focus_nodes
    original_validate = Shape.validate
    if list(inspect.signature(original_validate).parameters) != [
        "self",
        "executor",
        "target_graph",
        "focus",
        "_evaluation_path",
    ] or list(inspect.signature(original_targets).parameters) != ["self", "data_graph", "debug"]:
        raise ConstraintValidatorError("ENGINE_VERSION")
    reported: set[Any] = set()

    def wrap(component: Any, original: Any) -> Any:
        def evaluate(
            self: Any,
            executor: Any,
            target_graph: Any,
            focus_value_nodes: Any,
            _evaluation_path: Any,
        ) -> Any:
            seen_focus.update(focus_value_nodes)
            if len(seen_focus) > limits.max_focus_nodes:
                raise ConstraintValidatorError("FOCUS_BUDGET")
            result = original(self, executor, target_graph, focus_value_nodes, _evaluation_path)
            # Count completed substantive component/focus applications, not declarations.
            # Structural wrappers cannot make an otherwise empty shape pass acceptance.
            if component.__name__ not in _STRUCTURAL:
                completed.update(
                    (self.shape.node, focus, component.__name__)
                    for focus, values in focus_value_nodes.items()
                    if values or component.__name__ not in _VALUE_BASED
                )
            reported.update(r[1] for r in result[1])
            if len(reported) > limits.max_results:
                raise ConstraintValidatorError("REPORT_BUDGET")
            return result

        return evaluate

    def bounded_targets(self: Any, graph: Any, debug: bool = False) -> Any:
        targets = original_targets(self, graph, debug=debug)
        if selection.mode == "FILTER_TARGETS":
            targets &= {URIRef(i) for i in selection.focus_iris}
        seen_focus.update(targets)
        if len(seen_focus) > limits.max_focus_nodes:
            raise ConstraintValidatorError("FOCUS_BUDGET")
        return targets

    def selected_validate(
        self: Any, executor: Any, target_graph: Any, focus: Any = None, _evaluation_path: Any = None
    ) -> Any:
        if _evaluation_path is None:
            if selection.shape_iris and self.node not in {URIRef(i) for i in selection.shape_iris}:
                return True, []
            if selection.mode == "EXPLICIT_SHAPE_FOCUS":
                focus = [URIRef(i) for i in selection.focus_iris]
        return original_validate(
            self, executor, target_graph, focus=focus, _evaluation_path=_evaluation_path
        )

    try:
        for component, original in originals.items():
            _replace_method(component, "evaluate", wrap(component, original))
        _replace_method(Shape, "focus_nodes", bounded_targets)
        _replace_method(Shape, "validate", selected_validate)
        # Recursive shapes may cause pySHACL to warn and skip evaluation. Refuse instead.
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            conforms, report, _ = pyshacl.validate(
                data,
                shacl_graph=shapes,
                inference="none",
                advanced=False,
                js=False,
                do_owl_imports=False,
                sparql_mode=False,
                meta_shacl=False,
                abort_on_first=False,
                allow_infos=False,
                allow_warnings=False,
                max_validation_depth=15,
                use_shapes=None,
                focus_nodes=None,
            )
        return conforms, report, completed, reported
    finally:
        for component, original in originals.items():
            _replace_method(component, "evaluate", original)
        _replace_method(Shape, "focus_nodes", original_targets)
        _replace_method(Shape, "validate", original_validate)


def _replace_method(owner: Any, name: str, method: Any) -> None:
    """Adapt only version/signature-verified evaluator methods in the private process."""
    setattr(owner, name, method)


def process(payload: dict) -> dict:
    import pyoxigraph as ox
    import pyshacl
    import rdflib
    from rdflib import BNode, Literal, URIRef

    if (pyshacl.__version__, rdflib.__version__, ox.__version__) != ("0.40.1", "7.6.0", "0.5.11"):
        raise ConstraintValidatorError("ENGINE_VERSION")
    limits = ConstraintValidationLimits(**payload["limits"])
    selection = ValidationSelection(
        **{
            **payload["selection"],
            "focus_iris": tuple(payload["selection"]["focus_iris"]),
            "shape_iris": tuple(payload["selection"]["shape_iris"]),
        }
    )
    manifest = validator_manifest(selection=selection, limits=limits)
    origins: dict[Any, tuple[str, str, str]] = {}
    data = _graph(payload["data"], "data_", limits.max_quads, origins, "DATA")
    shapes = _graph(payload["shapes"], "shapes_", limits.max_shape_quads, origins, "SHAPES")
    _supported(shapes)
    conforms, report, completed, reported = _evaluate(data, shapes, selection, limits)
    if not isinstance(report, rdflib.Graph):
        raise ConstraintValidatorError("MALFORMED_SHAPES")
    # A cloned data blank node may itself assert SHACL result/report types. Only
    # nodes actually returned by completed evaluators are engine result records.
    results = reported & set(report.subjects(URIRef(RDF + "type"), URIRef(SH + "ValidationResult")))
    if len(results) > limits.max_results:
        raise ConstraintValidatorError("REPORT_BUDGET")
    status = ("CONFORMS" if conforms else "VIOLATES") if completed else "NOT_EVALUATED"
    # Generated prose can contain unordered graph rendering. Retain machine triples and
    # exact authored messages; the manifest explicitly names this normalization policy.
    for result in results:
        report.remove((result, URIRef(SH + "resultMessage"), None))
        for shape in report.objects(result, URIRef(SH + "sourceShape")):
            for message in shapes.objects(shape, URIRef(SH + "message")):
                report.add((result, URIRef(SH + "resultMessage"), message))
    roots = set(report.subjects(URIRef(RDF + "type"), URIRef(SH + "ValidationReport")))
    if results:
        roots &= {
            root for result in results for root in report.subjects(URIRef(SH + "result"), result)
        }
    if len(roots) != 1:
        raise ConstraintValidatorError("MALFORMED_SHAPES")
    report_node = roots.pop()
    report.add((report_node, URIRef(G8 + "evaluationStatus"), Literal(status)))
    report.add((report_node, URIRef(G8 + "selectionMode"), Literal(selection.mode)))
    for field in ("data", "shapes"):
        report.add((report_node, URIRef(G8 + field + "Sha256"), Literal(payload[field]["sha256"])))
        for iri in sorted(payload[field]["graph_iris"]):
            report.add((report_node, URIRef(G8 + field + "Graph"), URIRef(iri)))
    for field, iris in (("focus", selection.focus_iris), ("shape", selection.shape_iris)):
        for iri in sorted(iris):
            report.add((report_node, URIRef(G8 + field + "Selector"), URIRef(iri)))
    if not completed:
        # A vacuous pySHACL true is not a conformance assertion in this retained report.
        report.remove((report_node, URIRef(SH + "conforms"), None))

    # RDFC renames report blank nodes. Preserve their exact retained-input coordinates
    # using selected input maps, never by trusting a caller-supplied identifier prefix.
    origin_fields = ("originDatasetSha256", "originBlankNodeLabel", "originRole")
    for field in origin_fields:
        report.remove((None, URIRef(G8 + field), None))
    report_terms = set(report.subjects()) | set(report.objects())
    for node, coordinate in origins.items():
        if node in report_terms:
            for field, value in zip(origin_fields, coordinate, strict=True):
                report.add((node, URIRef(G8 + field), Literal(value)))

    def term(value: Any) -> Any:
        if isinstance(value, URIRef):
            return ox.NamedNode(str(value))
        if isinstance(value, BNode):
            return ox.BlankNode(str(value))
        return ox.Literal(
            str(value),
            language=value.language,
            datatype=ox.NamedNode(str(value.datatype)) if value.datatype else None,
        )

    canonical = _canonical(
        ox.Dataset(
            ox.Quad(term(s), term(p), term(o), ox.NamedNode(G8 + "report")) for s, p, o in report
        )
    )
    if len(canonical) > limits.max_report_bytes:
        raise ConstraintValidatorError("REPORT_BUDGET")
    return {
        "status": status,
        "conforms": conforms if completed else None,
        "data_sha256": payload["data"]["sha256"],
        "shapes_sha256": payload["shapes"]["sha256"],
        "data_graph_iris": sorted(payload["data"]["graph_iris"]),
        "shape_graph_iris": sorted(payload["shapes"]["graph_iris"]),
        "report_nquads": base64.b64encode(canonical).decode(),
        "report_sha256": hashlib.sha256(canonical).hexdigest(),
        "evaluated_shape_count": len({s for s, _, _ in completed}),
        "evaluated_focus_count": len({f for _, f, _ in completed}),
        "evaluated_constraint_count": len(completed),
        "violation_count": len(results),
        "manifest": manifest,
    }


def main() -> int:
    response = Path(sys.argv[2])
    try:
        try:
            apply_resource_caps(*(int(value) for value in sys.argv[3:6]))
        except (OSError, ValueError):
            raise ConstraintValidatorError("RESOURCE_CAP_UNAVAILABLE") from None

        # Defense in depth: selected in-memory graphs cannot open sockets or spawn code.
        def audit(event: str, args: tuple) -> None:
            if (
                event in {"socket.connect", "socket.bind", "socket.getaddrinfo", "socket.sendto"}
                or event.startswith("subprocess.")
                or event == "os.system"
            ):
                raise ConstraintValidatorError("UNSUPPORTED_SHAPES")

        sys.addaudithook(audit)
        result = process(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    except ConstraintValidatorError as exc:
        response.write_text(json.dumps({"error": exc.code}), encoding="utf-8")
        return 1
    except (MemoryError, OSError):
        response.write_text('{"error":"WORKER_FAILED"}', encoding="utf-8")
        return 1
    except Exception:
        response.write_text('{"error":"MALFORMED_SHAPES"}', encoding="utf-8")
        return 1
    response.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
