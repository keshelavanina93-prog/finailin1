import argparse
import json
import os
from copy import deepcopy
from uuid import UUID

import psycopg
from finai_api.domain.review import Principal
from finai_api.services import function_invocations as f
from finai_api.services.workspace import WorkspaceError
from psycopg.types.json import Jsonb

p = next(
    Principal.model_validate(v)
    for v in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
    if "ingest" in v["permissions"]
)
parser = argparse.ArgumentParser(
    description="Verify a retained posted-movement result and optional rollback-only SQL tampering probes."
)
parser.add_argument("invocation_id", type=UUID)
parser.add_argument("--probe-sql-guards", action="store_true")
args = parser.parse_args()
identity = args.invocation_id
original = f.history(p, identity)
assert original["status"] == "SUCCEEDED"
assert f.history(p, identity)["receipt_hash"] == original["receipt_hash"]
foreign = p.model_copy(
    update={
        "scope": p.scope.model_copy(
            update={"legal_entity_id": "unrelated-report-company"}
        )
    }
)
try:
    f.history(foreign, identity)
except WorkspaceError as exc:
    assert getattr(exc, "status", None) == 404
else:
    raise AssertionError("Cross-company report visible")
checks = ["reopen_same_receipt", "foreign_company_404"]
if args.probe_sql_guards:
    with f._database(p) as cur:
        saved = cur.execute(
            "SELECT * FROM function_invocation_results WHERE tenant_id=%s AND request_id=%s",
            (p.scope.tenant_id, identity),
        ).fetchone()
        for kind in [
            "wrong_total",
            "wrong_currency",
            "missing_exclusion",
            "missing_authority",
        ]:
            output = deepcopy(original["output"])
            if kind == "wrong_total":
                output["posted_movements"]["groups"][0]["value"] = "0"
            elif kind == "wrong_currency":
                output["posted_movements"]["groups"][0]["currency_id"] = "wrong"
            elif kind == "missing_exclusion":
                output["posted_movements"]["excluded_rows"] = []
            else:
                output["authority_check"] = {}
            output.pop("run_id")
            run = "fcr_" + f._digest(output)
            output["run_id"] = run
            receipt = deepcopy(saved["payload"])
            receipt["run_id"] = run
            cur.execute("SAVEPOINT forgery_check")
            try:
                cur.execute(
                    "INSERT INTO fact_calculation_runs(tenant_id,run_id,exact_scope,payload,actor_id) VALUES(%s,%s,%s,%s,%s)",
                    (
                        p.scope.tenant_id,
                        run,
                        Jsonb(p.scope.model_dump(mode="json")),
                        Jsonb(output),
                        p.actor_id,
                    ),
                )
                cur.execute(
                    "INSERT INTO function_invocation_results(tenant_id,request_id,exact_scope,actor_id,status,run_id,payload,proof_hash) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        p.scope.tenant_id,
                        identity,
                        Jsonb(saved["exact_scope"]),
                        saved["actor_id"],
                        "SUCCEEDED",
                        run,
                        Jsonb(receipt),
                        f._digest(receipt),
                    ),
                )
            except psycopg.errors.RaiseException as exc:
                assert "Posted" in str(exc), str(exc)
                checks.append(kind + "_SQL_refused")
            else:
                raise AssertionError("Forged report accepted")
            finally:
                cur.execute("ROLLBACK TO SAVEPOINT forgery_check")
print(json.dumps(checks))
