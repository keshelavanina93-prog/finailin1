"""An installed wheel must load pinned catalogs and candidates without a checkout."""

import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


def test_wheel_contains_exact_catalog_and_loads_without_source_checkout(tmp_path):
    root = Path(__file__).resolve().parents[3]
    dist = tmp_path / "dist"
    subprocess.run(
        [sys.executable, "-m", "hatchling", "build", "-t", "wheel", "-d", str(dist)],
        cwd=root / "services/api", check=True, capture_output=True, text=True,
    )
    wheel = next(dist.glob("*.whl"))
    with ZipFile(wheel) as archive:
        for source, packaged in (
            ("packages/contracts/catalog/ontology-catalog.g8-finance.v1.json",
             "finai_api/catalog/ontology-catalog.g8-finance.v1.json"),
            ("constructions/candidate/coa-406.candidate.json",
             "finai_api/constructions/coa-406.candidate.json"),
            ("constructions/candidate/seg-entities.candidate.json",
             "finai_api/constructions/seg-entities.candidate.json"),
        ):
            assert archive.read(packaged) == (root / source).read_bytes()
    script = """
import json
from finai_api.domain import finance_catalog_loader as loader
catalog = loader.load_finance_catalog()
candidate = loader.load_candidate_construction('g8.candidate.coa-406')
print(json.dumps({'catalog_id': catalog['catalog_id'], 'accounts': len(candidate['mutations'])}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(wheel)},
        check=True, capture_output=True, text=True,
    )
    assert json.loads(completed.stdout) == {"catalog_id": "g8.ontology.finance.v1", "accounts": 406}
