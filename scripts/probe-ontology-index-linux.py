"""Early synthetic-only Linux cap diagnosis; never load service secrets or company artifacts."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

CHILD = r"""
import json, os, resource, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from finai_api.services.rdf_engine_limits import apply_resource_caps
fd_limit, memory_mib = int(sys.argv[3]), int(sys.argv[4])
original_setrlimit = resource.setrlimit
def diagnostic_limits(which, pair):
    original_setrlimit(which, (fd_limit, fd_limit) if which == resource.RLIMIT_NOFILE else pair)
resource.setrlimit = diagnostic_limits
stage = "caps"
def stats():
    try:
        lines = Path("/proc/self/status").read_text().splitlines()
        return {**{line.split(":")[0]:line.split(":",1)[1].strip() for line in lines
                   if line.startswith(("VmSize:","VmRSS:","VmPeak:","Threads:"))},
                "fds":len(os.listdir("/proc/self/fd"))}
    except Exception as error:
        return {"stats_error":type(error).__name__}
before = {}
try:
    apply_resource_caps(3, memory_mib * 1024**2, 256 * 1024**2)
    resource.setrlimit = original_setrlimit
    stage = "import"
    import pyoxigraph as ox
    before = stats()
    stage = "create"
    store = ox.Store(sys.argv[2])
    stage = "extend"
    store.add(ox.Quad(ox.NamedNode("https://example.test/s"), ox.NamedNode("https://example.test/p"),
                      ox.Literal("synthetic probe"), ox.NamedNode("https://example.test/g")))
    stage = "flush"
    store.flush()
    del store
    stage = "read-only"
    store = ox.Store.read_only(sys.argv[2])
    stage = "inspect"
    assert len(list(store)) == 1
    print(json.dumps({"ok":True,"stage":stage,"before":before,"after":stats()}))
except BaseException as error:
    # Only this fixed synthetic fixture runs here, never retained documents or DB credentials.
    message = str(error).replace(sys.argv[2], "<synthetic-store>")[:1200]
    print(json.dumps({"ok":False,"stage":stage,"exception":type(error).__name__,
                      "message":message,"before":before,"after":stats()}))
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify", action="store_true", help="Fail early unless production index works"
    )
    args = parser.parse_args()
    if sys.platform != "linux":
        print(json.dumps({"skipped": "Linux-specific synthetic resource probe"}))
        return 0
    repository = Path(__file__).resolve().parents[1]
    src = repository / "services" / "api" / "src"
    scratch_root = repository / ".finai" / "tmp"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="index-cap-probe-", dir=scratch_root
    ) as temporary:
        scratch = Path(temporary)
        for name, descriptors, memory, arena in (
            ("current-32fd-512MiB", 32, 512, None),
            ("128fd-512MiB", 128, 512, None),
            ("32fd-2048MiB", 32, 2048, None),
            ("128fd-2048MiB", 128, 2048, None),
            ("32fd-512MiB-2arenas", 32, 512, "2"),
        ):
            environment = {
                "TEMP": str(scratch),
                "TMP": str(scratch),
                "TMPDIR": str(scratch),
            }
            if arena:
                environment["MALLOC_ARENA_MAX"] = arena
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        "-B",
                        "-c",
                        CHILD,
                        str(src),
                        str(scratch / name),
                        str(descriptors),
                        str(memory),
                    ],
                    env=environment,
                    cwd=scratch,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                print(
                    json.dumps(
                        {
                            "variant": name,
                            "returncode": result.returncode,
                            "stdout": result.stdout[:4000],
                            "stderr": result.stderr[:1200],
                        }
                    ),
                    flush=True,
                )
            except subprocess.TimeoutExpired:
                print(json.dumps({"variant": name, "timeout_seconds": 8}), flush=True)
        if args.verify:
            sys.path.insert(0, str(src))
            from hashlib import sha256
            from uuid import uuid4

            from finai_api.services.ontology_index import (
                OntologyIndexScope,
                build_index,
                inspect_subject,
            )

            data = b'<https://example.test/s> <https://example.test/p> "probe" <https://example.test/g> .\n'
            scope = OntologyIndexScope(
                "probe-tenant",
                "probe-entity",
                str(uuid4()),
                str(uuid4()),
                "a" * 64,
                sha256(data).hexdigest(),
            )
            try:
                manifest = build_index(
                    scope, data, index_root=scratch / "production-api"
                )
                result = inspect_subject(
                    scope,
                    "https://example.test/s",
                    index_root=scratch / "production-api",
                )
                assert manifest.quad_count == 1 and len(result.quads) == 1
                print(json.dumps({"production_index_verified": True}), flush=True)
            except Exception as error:
                print(
                    json.dumps(
                        {
                            "production_index_verified": False,
                            "code": getattr(error, "code", type(error).__name__),
                        }
                    ),
                    flush=True,
                )
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
