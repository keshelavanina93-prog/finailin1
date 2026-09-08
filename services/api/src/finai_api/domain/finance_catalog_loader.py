"""Load the G8 finance ontology catalog JSON. Does not seed company facts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOG_RELATIVE = Path("packages/contracts/catalog/ontology-catalog.g8-finance.v1.json")


def catalog_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[5]
    return root / CATALOG_RELATIVE


def load_finance_catalog(repo_root: Path | None = None) -> dict[str, Any]:
    path = catalog_path(repo_root)
    with path.open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    if catalog.get("catalog_id") != "g8.ontology.finance.v1":
        raise ValueError("unexpected finance catalog_id")
    return catalog


def object_type_names(catalog: dict[str, Any] | None = None) -> list[str]:
    catalog = catalog or load_finance_catalog()
    return [item["api_name"] for item in catalog["object_types"]]


def link_type_names(catalog: dict[str, Any] | None = None) -> list[str]:
    catalog = catalog or load_finance_catalog()
    return [item["api_name"] for item in catalog["link_types"]]
