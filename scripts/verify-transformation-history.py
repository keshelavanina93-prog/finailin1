"""Read actual build history through the mounted proxy without starting work."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main() -> None:
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    token = next(
        token for token, grant in grants.items() if "ingest" in grant["permissions"]
    )
    pages = []
    ids: set[str] = set()
    params: dict[str, str | int] = {"limit": 2}
    with httpx.Client(
        base_url="http://127.0.0.1:3062/api/ontology/transformations",
        headers={"Authorization": "Bearer " + token},
        timeout=30,
    ) as client:
        for _ in range(10):
            response = client.get("/runs", params=params)
            response.raise_for_status()
            page = response.json()
            assert page["purpose"] == "HISTORICAL_BUILD_EVIDENCE"
            assert len(page["items"]) <= 2
            for item in page["items"]:
                assert item["request_id"] not in ids
                assert "runtime_status" not in item
                assert (
                    not item["current_use_authorized"]
                    and not item["business_effect_authorized"]
                )
                ids.add(item["request_id"])
            pages.append(page)
            cursor = page["next_cursor"]
            if cursor is None:
                break
            params.update(
                before_created_at=cursor["created_at"],
                before_request_id=cursor["request_id"],
            )
        else:
            raise AssertionError("History exceeded bounded proof window")
        assert {
            "e94d4d85-47f5-4560-a62d-f710c61b8152",
            "7366e916-7b1e-430a-b99f-9872f24df261",
            "cb0be0c5-fb7f-452c-9460-7dab27ff0bda",
        }.issubset(ids)
        assert (
            client.get(
                "/runs", params={"before_request_id": next(iter(ids))}
            ).status_code
            == 422
        )
    Path("docs/development/evidence/nin12-build-history.json").write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "pages": pages,
                "unique_runs": len(ids),
                "read_only": True,
                "incomplete_cursor_rejected": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Historical build pages verified: {len(ids)} distinct retained runs; no work submitted."
    )


if __name__ == "__main__":
    main()
