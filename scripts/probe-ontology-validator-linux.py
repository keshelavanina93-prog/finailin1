"""Early offline synthetic probe of the production capped SHACL worker on CI Linux."""

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

DATA = (
    b"<https://example.test/a> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
    b"<https://example.test/Account> <https://example.test/data> .\n"
    b"<https://example.test/a> <https://example.test/value> "
    b'"01"^^<http://www.w3.org/2001/XMLSchema#integer> <https://example.test/data> .\n'
)
VIOLATING_DATA = DATA.replace(
    b'"01"^^<http://www.w3.org/2001/XMLSchema#integer>', b'"bad"'
)
UNTARGETED_DATA = DATA.replace(
    b"<https://example.test/Account>", b"<https://example.test/Other>"
)
SHAPES = (
    b"<https://example.test/P> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
    b"<http://www.w3.org/ns/shacl#PropertyShape> <https://example.test/shapes> .\n"
    b"<https://example.test/P> <http://www.w3.org/ns/shacl#datatype> "
    b"<http://www.w3.org/2001/XMLSchema#integer> <https://example.test/shapes> .\n"
    b"<https://example.test/P> <http://www.w3.org/ns/shacl#path> "
    b"<https://example.test/value> <https://example.test/shapes> .\n"
    b"<https://example.test/S> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
    b"<http://www.w3.org/ns/shacl#NodeShape> <https://example.test/shapes> .\n"
    b"<https://example.test/S> <http://www.w3.org/ns/shacl#property> "
    b"<https://example.test/P> <https://example.test/shapes> .\n"
    b"<https://example.test/S> <http://www.w3.org/ns/shacl#targetClass> "
    b"<https://example.test/Account> <https://example.test/shapes> .\n"
)
DATA_SHA = "6c0ae054411b6606a5372851463fa3121b1645683a45a18d344e5ebb00f17171"
VIOLATING_SHA = "8fe6268b44ba6793dc5fa954254f429bb8df82d9a6fb0634303b500189ed9ddc"
UNTARGETED_SHA = "d14bd06bb88ef5e3d6ce0739d184a4f85cfc7ba215acbdc3f5980cfb0cb928c5"
SHAPES_SHA = "e3cce30a13a2622d83e3e9b26233a8c9690d3de2404da45a9e8d854f4d76b22c"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify",
        action="store_true",
        required=True,
        help="Require all three outcomes from the actual production worker",
    )
    parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / "services" / "api" / "src"))
    from finai_api.services.constraint_validator import (
        ValidationDataset,
        validate_constraints,
    )

    scratch_root = repository / ".finai" / "tmp"
    scratch_root.mkdir(parents=True, exist_ok=True)
    # This intentionally runs on Windows too, using its real mandatory Job Object caps.
    # Linux CI uses the same public function and fixed default limits without overrides.
    with tempfile.TemporaryDirectory(
        prefix="validator-cap-probe-", dir=scratch_root
    ) as temporary:
        for content, source_sha, expected_status, expected_conforms, expected_count in (
            (DATA, DATA_SHA, "CONFORMS", True, 0),
            (VIOLATING_DATA, VIOLATING_SHA, "VIOLATES", False, 1),
            (UNTARGETED_DATA, UNTARGETED_SHA, "NOT_EVALUATED", None, 0),
        ):
            try:
                result = validate_constraints(
                    ValidationDataset(
                        content, source_sha, ("https://example.test/data",)
                    ),
                    ValidationDataset(
                        SHAPES, SHAPES_SHA, ("https://example.test/shapes",)
                    ),
                    work_dir=Path(temporary),
                )
                evaluated = expected_status != "NOT_EVALUATED"
                if (
                    result.status != expected_status
                    or result.conforms is not expected_conforms
                    or result.violation_count != expected_count
                    or bool(result.evaluated_constraint_count) != evaluated
                    or bool(result.evaluated_shape_count) != evaluated
                    or bool(result.evaluated_focus_count) != evaluated
                    or result.data_sha256 != source_sha
                    or result.shapes_sha256 != SHAPES_SHA
                    or hashlib.sha256(result.report_nquads).hexdigest()
                    != result.report_sha256
                    or result.data_graph_iris != ("https://example.test/data",)
                    or result.shape_graph_iris != ("https://example.test/shapes",)
                    or (
                        not evaluated
                        and b"<http://www.w3.org/ns/shacl#conforms>"
                        in result.report_nquads
                    )
                ):
                    raise RuntimeError("SYNTHETIC_OUTCOME_MISMATCH")
                print(
                    json.dumps(
                        {
                            "production_validator_verified": True,
                            "status": result.status,
                            "data_sha256": result.data_sha256,
                            "report_sha256": result.report_sha256,
                            "evaluated_constraints": result.evaluated_constraint_count,
                            "violation_count": result.violation_count,
                        }
                    ),
                    flush=True,
                )
            except Exception as error:
                # Emit only a bounded code, never source data, environment, or parser prose.
                print(
                    json.dumps(
                        {
                            "production_validator_verified": False,
                            "expected_status": expected_status,
                            "code": str(getattr(error, "code", type(error).__name__))[
                                :80
                            ],
                        }
                    ),
                    flush=True,
                )
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
