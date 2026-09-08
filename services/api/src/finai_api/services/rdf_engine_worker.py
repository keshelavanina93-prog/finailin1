"""Private executable worker; no service configuration, credentials, or network retrieval."""

import base64
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

# -I excludes the script directory. Add only the trusted installed package root.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from finai_api.services.rdf_engine import RdfEngineError, RdfLimits
    from finai_api.services.rdf_engine_limits import apply_resource_caps
else:
    from finai_api.services.rdf_engine import RdfEngineError, RdfLimits
    from finai_api.services.rdf_engine_limits import apply_resource_caps

_OWL_IMPORTS = "http://www.w3.org/2002/07/owl#imports"


def _xml_guard(content: bytes) -> None:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise RdfEngineError("UNSAFE_XML") from None
    # Refuse DTDs even if internal-only, custom entities, and encoding tricks before Rust.
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE) or "\x00" in text:
        raise RdfEngineError("UNSAFE_XML")
    declaration = re.match(r"\s*<\?xml\b.*?\?>", text, re.DOTALL)
    if declaration:
        encoding = re.search(r"encoding\s*=\s*['\"]([^'\"]+)", declaration[0], re.IGNORECASE)
        if encoding and encoding[1].lower() not in ("utf-8", "utf8"):
            raise RdfEngineError("UNSAFE_XML")


def _closure(imports: dict[str, set[str]], roots: list[str], max_depth: int) -> tuple[str, ...]:
    reached: set[str] = set()
    depths: dict[str, int] = {}

    def visit(iri: str, path: set[str]) -> int:
        if iri in path:
            raise RdfEngineError("IMPORT_CYCLE")
        if iri in depths:
            return depths[iri]
        reached.add(iri)
        depth = 1
        for dependency in sorted(imports[iri]):
            depth = max(depth, 1 + visit(dependency, path | {iri}))
        if depth > max_depth:
            raise RdfEngineError("IMPORT_DEPTH")
        depths[iri] = depth
        return depth

    for root in sorted(roots):
        visit(root, set())
    if reached != set(imports):
        raise RdfEngineError("UNREACHABLE_ARTIFACT")
    return tuple(sorted(reached))


def process(payload: dict[str, Any], caps: str) -> dict[str, Any]:
    import pyoxigraph as ox

    if ox.__version__ != "0.5.11":
        raise RdfEngineError("ENGINE_VERSION")
    limits = RdfLimits(**payload["limits"])
    artifacts = payload["artifacts"]
    namespaces: list[tuple[str, str]] = []
    for artifact in artifacts:
        try:
            for iri in (
                artifact["artifact_iri"],
                *artifact["owned_namespaces"],
                *artifact["permitted_import_iris"],
            ):
                ox.NamedNode(iri)
        except ValueError:
            raise RdfEngineError("INVALID_INPUT") from None
        for namespace in artifact["owned_namespaces"]:
            if any(
                owner != artifact["artifact_iri"]
                and (namespace.startswith(other) or other.startswith(namespace))
                for other, owner in namespaces
            ):
                raise RdfEngineError("NAMESPACE_COLLISION")
            namespaces.append((namespace, artifact["artifact_iri"]))
    identities = {a["artifact_iri"] for a in artifacts}
    imports: dict[str, set[str]] = {iri: set() for iri in identities}
    dataset = ox.Dataset()
    records: list[dict[str, Any]] = []
    parsed_count = blank_count = literal_bytes = 0
    for artifact in artifacts:
        iri = artifact["artifact_iri"]
        content = base64.b64decode(artifact["content"], validate=True)
        if artifact["format"] == "RDF_XML":
            _xml_guard(content)
        # Each document has an independent blank-node map; canonicalization later removes labels.
        blanks: dict[str, ox.BlankNode] = {}
        graph = ox.NamedNode(iri)
        before = len(dataset)
        try:
            parsed = ox.parse(
                input=content,
                format=getattr(ox.RdfFormat, artifact["format"]),
                base_iri=iri,
                without_named_graphs=True,
                lenient=False,
            )
            for quad in parsed:
                parsed_count += 1
                if parsed_count > limits.max_quads:
                    raise RdfEngineError("QUAD_BUDGET")
                if isinstance(quad.subject, ox.Triple) or isinstance(quad.object, ox.Triple):
                    raise RdfEngineError("UNSUPPORTED_RDF")
                subject = quad.subject
                if (
                    isinstance(subject, ox.NamedNode)
                    and subject.value != iri
                    and not any(
                        subject.value.startswith(namespace)
                        for namespace in artifact["owned_namespaces"]
                    )
                ):
                    raise RdfEngineError("NAMESPACE_VIOLATION")
                if quad.predicate.value == _OWL_IMPORTS:
                    if not isinstance(quad.object, ox.NamedNode):
                        raise RdfEngineError("IMPORT_NOT_PERMITTED")
                    dependency = quad.object.value
                    if dependency not in artifact["permitted_import_iris"]:
                        raise RdfEngineError("IMPORT_NOT_PERMITTED")
                    if dependency not in identities:
                        raise RdfEngineError("IMPORT_MISSING")
                    imports[iri].add(dependency)
                terms = []
                for term in (quad.subject, quad.object):
                    if isinstance(term, ox.BlankNode):
                        if term.value not in blanks:
                            blank_count += 1
                            if blank_count > limits.max_blank_nodes:
                                raise RdfEngineError("BLANK_NODE_BUDGET")
                            blanks[term.value] = ox.BlankNode(f"d{blank_count}")
                        term = blanks[term.value]
                    elif isinstance(term, ox.Literal):
                        if term.direction is not None:
                            raise RdfEngineError("UNSUPPORTED_RDF")
                        literal_bytes += len(term.value.encode("utf-8"))
                        if literal_bytes > limits.max_literal_bytes:
                            raise RdfEngineError("LITERAL_BUDGET")
                    terms.append(term)
                dataset.add(ox.Quad(terms[0], quad.predicate, terms[1], graph))
        except SyntaxError:
            raise RdfEngineError("MALFORMED_RDF") from None
        records.append(
            {
                "artifact_iri": iri,
                "sha256": hashlib.sha256(content).hexdigest(),
                "imports": sorted(imports[iri]),
                "quad_count": len(dataset) - before,
            }
        )
    closure = _closure(imports, payload["root_iris"], limits.max_import_depth)
    dataset.canonicalize(ox.CanonicalizationAlgorithm.RDFC_1_0)
    serialized = ox.serialize(dataset, format=ox.RdfFormat.N_QUADS)
    if not isinstance(serialized, bytes):
        raise RdfEngineError("WORKER_FAILED")
    if len(serialized) > limits.max_output_bytes:
        raise RdfEngineError("OUTPUT_BUDGET")
    canonical = b"".join(line + b"\n" for line in sorted(serialized.split(b"\n")) if line)
    return {
        "canonical_nquads": base64.b64encode(canonical).decode("ascii"),
        "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
        "artifacts": sorted(records, key=lambda record: record["artifact_iri"]),
        "import_closure": closure,
        "quad_count": len(dataset),
        "blank_node_count": blank_count,
        "literal_bytes": literal_bytes,
        "manifest": {
            "engine": "pyoxigraph",
            "engine_version": ox.__version__,
            "canonicalization": "RDFC-1.0",
            "canonicalization_hash": "SHA-256",
            "serialization": "CANONICAL_N_QUADS_UTF8_SORTED",
            "named_graph_policy": "ARTIFACT_IRI",
            "network_retrieval": False,
            "reasoning": "NONE",
            "shacl_validation": False,
            "resource_caps": "REQUIRED_OS_CPU_AND_MEMORY",
            "parsed_quad_count": parsed_count,
            "cpu_seconds": limits.cpu_seconds,
            "memory_bytes": limits.memory_bytes,
            "wall_timeout_seconds": str(limits.wall_timeout_seconds),
        },
    }


def main() -> int:
    response = Path(sys.argv[2])
    try:
        try:
            caps = apply_resource_caps(*(int(value) for value in sys.argv[3:6]))
        except (OSError, ValueError):
            raise RdfEngineError("RESOURCE_CAP_UNAVAILABLE") from None
        payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        result = process(payload, caps)
    except RdfEngineError as exc:
        response.write_text(json.dumps({"error": exc.code}), encoding="utf-8")
        return 1
    except Exception:
        response.write_text('{"error":"WORKER_FAILED"}', encoding="utf-8")
        return 1
    response.write_text(json.dumps(result, sort_keys=True, ensure_ascii=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
