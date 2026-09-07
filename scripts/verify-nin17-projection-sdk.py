"""Validate real backend projections against the unchanged frontend SDK (Node 22+)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/tests"))

from finai_api.domain.semantic_analysis import Filter
from finai_api.services import semantic_analysis
from test_semantic_entity_movements import case


def main():
    with pytest.MonkeyPatch.context() as patch:
        _, request = case.__wrapped__(patch)
        initial = semantic_analysis.project(None, request)
        selected = semantic_analysis.project(
            None,
            request.model_copy(
                update={
                    "descriptor_sha256": initial.descriptor_sha256,
                    "selected_row": initial.rows[0].key,
                }
            ),
        )
        filtered = semantic_analysis.project(
            None,
            request.model_copy(
                update={
                    "descriptor_sha256": initial.descriptor_sha256,
                    "filters": [
                        Filter(
                            field="account",
                            value=initial.rows[0].values["account"].value,
                        )
                    ],
                    "group_by": "account",
                }
            ),
        )
        payload = [
            value.model_dump(mode="json") for value in (initial, selected, filtered)
        ]
    subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            str(ROOT / "scripts/verify-nin17-projection-sdk.mjs"),
        ],
        input=json.dumps(payload),
        text=True,
        check=True,
        cwd=ROOT,
    )


if __name__ == "__main__":
    main()
