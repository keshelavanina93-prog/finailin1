"""Offline, synthetic RDF fixtures challenge normalization and refusal boundaries."""

import base64
import ctypes
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from finai_api.services import rdf_engine, rdf_engine_limits, rdf_engine_worker
from finai_api.services.rdf_engine import RdfArtifact, RdfEngineError, RdfLimits, canonicalize_rdf

A = "https://example.test/a"
B = "https://example.test/b"
C = "https://example.test/c"
P = "https://example.test/p"
IMPORT = "http://www.w3.org/2002/07/owl#imports"


def artifact(iri=A, text=None, imports=(), namespaces=None, format="TURTLE"):
    content = text if isinstance(text, bytes) else (text or f'<{iri}#term> <{P}> "text" .').encode()
    return RdfArtifact(iri, format, content, namespaces or (iri + "#",), imports)


def run(tmp_path, artifacts, **kwargs):
    return canonicalize_rdf(
        artifacts,
        root_iris=kwargs.pop("root_iris", [artifacts[0].artifact_iri]),
        work_dir=tmp_path,
        **kwargs,
    )


def test_turtle_and_rdfxml_isomorphic_datasets_have_identical_canonical_bytes(tmp_path):
    turtle = artifact(text=f'<{A}#term> <{P}> _:first . _:first <{P}> "café"@fr .')
    xml = artifact(
        format="RDF_XML",
        text=f'''<?xml version="1.0" encoding="UTF-8"?>
    <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
             xmlns:e="https://example.test/">
      <rdf:Description rdf:nodeID="another"><e:p xml:lang="fr">café</e:p></rdf:Description>
      <rdf:Description rdf:about="{A}#term"><e:p rdf:nodeID="another"/></rdf:Description>
    </rdf:RDF>''',
    )
    first, second = run(tmp_path, [turtle]), run(tmp_path, [xml])
    expected = (f'<{A}#term> <{P}> _:c14n0 <{A}> .\n_:c14n0 <{P}> "café"@fr <{A}> .\n').encode()
    assert first.canonical_nquads == second.canonical_nquads == expected
    assert first.canonical_sha256 == second.canonical_sha256 == hashlib.sha256(expected).hexdigest()
    assert first.artifacts[0].sha256 != second.artifacts[0].sha256
    assert first.quad_count == 2 and first.blank_node_count == 1
    assert first.literal_bytes == len("café".encode())
    assert first.manifest["canonicalization"] == "RDFC-1.0"
    assert first.manifest["shacl_validation"] is False
    assert first.manifest["network_retrieval"] is False
    assert not list(tmp_path.iterdir())


def test_document_order_and_local_blank_labels_do_not_change_named_graph_result(tmp_path):
    a = artifact(
        text=f'<{A}> <{IMPORT}> <{B}> . <{A}#s> <{P}> _:same . _:same <{P}> "a" .', imports=(B,)
    )
    b = artifact(B, f'<{B}#s> <{P}> _:same . _:same <{P}> "b" .')
    first = run(tmp_path, [a, b])
    second = run(
        tmp_path, [replace(b, content=b.content.replace(b"_:same", b"_:renamed")), a], root_iris=[A]
    )
    assert first.canonical_nquads == second.canonical_nquads
    assert first.blank_node_count == 2 and first.quad_count == 5
    assert first.import_closure == (A, B)
    assert first.artifacts[0].imports == (B,)
    assert first.artifacts[0].quad_count == 3 and first.artifacts[1].quad_count == 2
    assert run(tmp_path, [b, a], root_iris=[A]).manifest == first.manifest


@pytest.mark.parametrize(
    "artifacts,roots,limits,code",
    [
        ([artifact(text=f"<{A}> <{IMPORT}> <{B}> .")], [A], RdfLimits(), "IMPORT_NOT_PERMITTED"),
        (
            [artifact(text=f"<{A}> <{IMPORT}> <{B}> .", imports=(B,))],
            [A],
            RdfLimits(),
            "IMPORT_MISSING",
        ),
        (
            [artifact(text=f"<{A}> <{IMPORT}> <{A}> .", imports=(A,))],
            [A],
            RdfLimits(),
            "IMPORT_CYCLE",
        ),
        (
            [
                artifact(text=f"<{A}> <{IMPORT}> <{B}> .", imports=(B,)),
                artifact(B, f"<{B}> <{IMPORT}> <{A}> .", imports=(A,)),
            ],
            [A, B],
            RdfLimits(),
            "IMPORT_CYCLE",
        ),
        ([artifact(), artifact(B)], [A], RdfLimits(), "UNREACHABLE_ARTIFACT"),
        (
            [artifact(), artifact(B, namespaces=(A + "#nested/",))],
            [A, B],
            RdfLimits(),
            "NAMESPACE_COLLISION",
        ),
        (
            [artifact(text=f'<{B}#term> <{P}> "foreign assertion" .')],
            [A],
            RdfLimits(),
            "NAMESPACE_VIOLATION",
        ),
        (
            [
                artifact(text=f"<{A}> <{IMPORT}> <{B}> .", imports=(B,)),
                artifact(B, f"<{B}> <{IMPORT}> <{C}> .", imports=(C,)),
                artifact(C),
            ],
            [C, B, A],
            RdfLimits(max_import_depth=2),
            "IMPORT_DEPTH",
        ),
    ],
)
def test_import_and_namespace_refusals(tmp_path, artifacts, roots, limits, code):
    with pytest.raises(RdfEngineError) as caught:
        run(tmp_path, artifacts, root_iris=roots, limits=limits)
    assert caught.value.code == code
    assert "foreign assertion" not in str(caught.value)


@pytest.mark.parametrize(
    "text,code",
    [
        (b'<!DOCTYPE rdf:RDF [<!ENTITY secret SYSTEM "file:///private">]><rdf:RDF/>', "UNSAFE_XML"),
        (b'<!DOCTYPE rdf:RDF SYSTEM "https://127.0.0.1:9/never-fetch"><rdf:RDF/>', "UNSAFE_XML"),
        ('<?xml version="1.0" encoding="UTF-16"?><rdf:RDF/>'.encode("utf-16"), "UNSAFE_XML"),
        (b'<?xml version="1.0" encoding="ISO-8859-1"?><rdf:RDF/>', "UNSAFE_XML"),
        (b"<rdf:RDF>confidential malformed source</rdf:RDF>", "MALFORMED_RDF"),
    ],
)
def test_xml_entity_encoding_and_parser_failures_are_bounded(tmp_path, text, code):
    with pytest.raises(RdfEngineError) as caught:
        run(tmp_path, [artifact(text=text, format="RDF_XML")])
    assert caught.value.code == code
    assert "confidential" not in str(caught.value) and len(str(caught.value)) < 160


def test_rdf_star_and_invalid_rdf_refused_without_literal_leaks(tmp_path):
    for text in (
        f'<< <{A}#s> <{P}> <{A}#o> >> <{P}> "private" .',
        f"<{A}#s> <{P}> << <{A}#s> <{P}> <{A}#o> >> .",
    ):
        with pytest.raises(RdfEngineError) as caught:
            run(tmp_path, [artifact(text=text)])
        assert caught.value.code in ("UNSUPPORTED_RDF", "MALFORMED_RDF")
        assert "private" not in str(caught.value)
    with pytest.raises(RdfEngineError) as caught:
        run(tmp_path, [artifact(text='"private malformed source')])
    assert caught.value.code == "MALFORMED_RDF"


@pytest.mark.parametrize(
    "limits,code",
    [
        (RdfLimits(max_input_bytes=1), "INPUT_BUDGET"),
        (RdfLimits(max_quads=1), "QUAD_BUDGET"),
        (RdfLimits(max_blank_nodes=1), "BLANK_NODE_BUDGET"),
        (RdfLimits(max_literal_bytes=1), "LITERAL_BUDGET"),
        (RdfLimits(max_output_bytes=1), "OUTPUT_BUDGET"),
    ],
)
def test_independent_input_parse_and_output_budgets(tmp_path, limits, code):
    source = artifact(text=f'_:a <{P}> _:b . _:b <{P}> "long literal" .')
    with pytest.raises(RdfEngineError) as caught:
        run(tmp_path, [source], limits=limits)
    assert caught.value.code == code
    assert not list(tmp_path.iterdir())


def test_duplicate_quads_still_consume_parser_work_budget(tmp_path):
    source = artifact(text=(f'<{A}#s> <{P}> "value" .\n' * 3))
    with pytest.raises(RdfEngineError) as caught:
        run(tmp_path, [source], limits=RdfLimits(max_quads=2))
    assert caught.value.code == "QUAD_BUDGET"
    result = run(tmp_path, [source])
    assert result.quad_count == 1 and result.manifest["parsed_quad_count"] == 3


@pytest.mark.parametrize(
    "limits",
    [
        RdfLimits(max_quads=True),
        RdfLimits(cpu_seconds=0),
        RdfLimits(wall_timeout_seconds=float("nan")),
        RdfLimits(memory_bytes=2**50),
    ],
)
def test_processing_limits_cannot_disable_caps(tmp_path, limits):
    with pytest.raises(RdfEngineError) as caught:
        run(tmp_path, [artifact()], limits=limits)
    assert caught.value.code == "INVALID_INPUT"


def test_duplicate_artifact_identity_and_unsupported_format_refused(tmp_path):
    for sources in ([artifact(), artifact()], [replace(artifact(), format="JSON_LD")]):
        with pytest.raises(RdfEngineError) as caught:
            run(tmp_path, sources)
        assert caught.value.code == "INVALID_INPUT"


def test_worker_has_no_credentials_and_timeout_kills_then_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setenv("FINAI_DATABASE_URL", "never-copy-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "never-copy-secret")
    monkeypatch.setenv("PYTHONPATH", "untrusted-python-path")
    real_popen = subprocess.Popen
    children = []

    def capture(*args, **kwargs):
        assert set(kwargs["env"]) <= {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR"}
        assert "never-copy-secret" not in str(kwargs["env"])
        assert args[0][1:3] == ["-I", "-B"]
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(rdf_engine.subprocess, "Popen", capture)
    assert run(tmp_path, [artifact()]).manifest["resource_caps"] == "REQUIRED_OS_CPU_AND_MEMORY"
    with pytest.raises(RdfEngineError) as caught:
        run(tmp_path, [artifact()], limits=RdfLimits(wall_timeout_seconds=0.000001))
    assert caught.value.code == "WALL_TIMEOUT"
    assert all(child.poll() is not None for child in children)
    assert not list(tmp_path.iterdir())


def test_unsupported_platform_fails_closed(monkeypatch):
    monkeypatch.setattr(rdf_engine_limits.sys, "platform", "unsupported-platform")
    with pytest.raises(OSError, match="unsupported"):
        rdf_engine_limits.apply_resource_caps(1, 128 * 1024**2, 1024**2)


@pytest.mark.parametrize(
    "work,expected",
    [
        ("try:\n bytearray(256 * 1024**2)\nexcept MemoryError:\n sys.exit(23)\nsys.exit(0)", 23),
        ("while True: pass", None),
    ],
)
def test_operating_system_memory_and_cpu_caps_actually_enforce(tmp_path, work, expected):
    directory = str(Path(rdf_engine_limits.__file__).parent)
    script = (
        f"import sys;sys.path.insert(0,{directory!r});"
        "from rdf_engine_limits import apply_resource_caps;"
        "apply_resource_caps(1,128*1024**2,1024**2)\n" + work
    )
    child = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script],
        cwd=tmp_path,
        env=rdf_engine._child_environment(tmp_path),
        capture_output=True,
        timeout=8,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert child.returncode == expected if expected is not None else child.returncode != 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows D-only runtime contract")
def test_windows_temp_refuses_other_drive_before_writing():
    with pytest.raises(RdfEngineError) as caught:
        canonicalize_rdf([artifact()], root_iris=[A], work_dir=Path("C:/forbidden-rdf-temp"))
    assert caught.value.code == "INVALID_INPUT"


def worker_payload(artifacts, limits=None):
    return {
        "artifacts": [
            {**asdict(a), "content": base64.b64encode(a.content).decode("ascii")} for a in artifacts
        ],
        "root_iris": [artifacts[0].artifact_iri],
        "limits": asdict(limits or RdfLimits()),
    }


def test_direct_parser_contract_matches_isolated_result_and_platform_independent_manifest(tmp_path):
    sources = [
        artifact(
            text=f'<{A}> <{IMPORT}> <{B}> . <{A}#s> <{P}> _:x . _:x <{P}> "é" .', imports=(B,)
        ),
        artifact(B, f'<{B}#s> <{P}> _:x . _:x <{P}> "other" .'),
    ]
    payload = worker_payload(sources)
    first = rdf_engine_worker.process(payload, "WINDOWS_CAPS_TEST")
    second = rdf_engine_worker.process(payload, "LINUX_CAPS_TEST")
    assert first == second
    native = run(tmp_path, sources)
    assert base64.b64decode(first["canonical_nquads"]) == native.canonical_nquads
    assert first["manifest"] == native.manifest


@pytest.mark.parametrize(
    "content,format,limits,code",
    [
        (f"<{A}> <{IMPORT}> <{B}> .", "TURTLE", RdfLimits(), "IMPORT_NOT_PERMITTED"),
        (f'<{A}> <{IMPORT}> "bad" .', "TURTLE", RdfLimits(), "IMPORT_NOT_PERMITTED"),
        (f'<{B}> <{P}> "foreign" .', "TURTLE", RdfLimits(), "NAMESPACE_VIOLATION"),
        (f'_:a <{P}> _:b . _:b <{P}> "long" .', "TURTLE", RdfLimits(max_quads=1), "QUAD_BUDGET"),
        (f"_:a <{P}> _:b .", "TURTLE", RdfLimits(max_blank_nodes=1), "BLANK_NODE_BUDGET"),
        (f'<{A}> <{P}> "long" .', "TURTLE", RdfLimits(max_literal_bytes=1), "LITERAL_BUDGET"),
        (f'<{A}> <{P}> "long" .', "TURTLE", RdfLimits(max_output_bytes=1), "OUTPUT_BUDGET"),
        (
            '<!DOCTYPE rdf:RDF SYSTEM "https://example.test/never">',
            "RDF_XML",
            RdfLimits(),
            "UNSAFE_XML",
        ),
        ('<?xml version="1.0" encoding="UTF-16"?>', "RDF_XML", RdfLimits(), "UNSAFE_XML"),
        ("malformed private source", "TURTLE", RdfLimits(), "MALFORMED_RDF"),
    ],
)
def test_direct_worker_refusal_contract(content, format, limits, code):
    with pytest.raises(RdfEngineError) as caught:
        rdf_engine_worker.process(
            worker_payload([artifact(text=content, format=format)], limits), "TEST_ONLY_UNCAPPED"
        )
    assert caught.value.code == code


@pytest.mark.parametrize("failure", ["create", "configure", "assign", None])
def test_windows_cap_api_configures_exact_limits_or_refuses(failure, monkeypatch):
    class Function:
        def __init__(self, call):
            self.call = call

        def __call__(self, *args):
            return self.call(*args)

    seen = {}

    def configure(job, information_class, pointer, size):
        limits = pointer._obj
        seen.update(
            job=job,
            information_class=information_class,
            cpu=limits.basic.process_time,
            memory=limits.process_memory,
            flags=limits.basic.flags,
            processes=limits.basic.active_processes,
        )
        assert size == ctypes.sizeof(limits)
        return failure != "configure"

    class Kernel:
        CreateJobObjectW = Function(lambda *_: 0 if failure == "create" else 100)
        SetInformationJobObject = Function(configure)
        GetCurrentProcess = Function(lambda: 200)
        AssignProcessToJobObject = Function(lambda *_: failure != "assign")
        CloseHandle = Function(lambda job: seen.update(closed=job))

    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: Kernel(), raising=False)
    monkeypatch.setattr(rdf_engine_limits, "_job_handle", None)
    if failure:
        with pytest.raises(OSError):
            rdf_engine_limits._windows_caps(3, 123456)
        if failure != "create":
            assert seen["closed"] == 100
    else:
        rdf_engine_limits._windows_caps(3, 123456)
        assert seen == {
            "job": 100,
            "information_class": 9,
            "cpu": 30_000_000,
            "memory": 123456,
            "flags": 0x210A,
            "processes": 1,
        }
        assert rdf_engine_limits._job_handle == 100


def test_worker_entrypoint_writes_only_bounded_result_and_refusal(tmp_path, monkeypatch):
    request, response = tmp_path / "request.json", tmp_path / "response.json"
    request.write_text(json.dumps(worker_payload([artifact()])), encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["worker", str(request), str(response), "1", "100000000", "10000"]
    )
    monkeypatch.setattr(rdf_engine_worker, "apply_resource_caps", lambda *_: "TEST_ONLY_UNCAPPED")
    assert rdf_engine_worker.main() == 0
    assert json.loads(response.read_text())["canonical_sha256"]
    request.write_text(
        json.dumps(worker_payload([artifact(text="private malformed")])), encoding="utf-8"
    )
    assert rdf_engine_worker.main() == 1
    assert json.loads(response.read_text()) == {"error": "MALFORMED_RDF"}

    def refused(*_):
        raise OSError("private OS details")

    monkeypatch.setattr(rdf_engine_worker, "apply_resource_caps", refused)
    assert rdf_engine_worker.main() == 1
    assert json.loads(response.read_text()) == {"error": "RESOURCE_CAP_UNAVAILABLE"}
