"""Dedicated Temporal worker. Run with the same server-owned access configuration as API."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from finai_api.config import get_settings
from finai_api.regulatory_workflow import RegulatorySourceCheck
from finai_api.report_workflow import ReportSourceWorkflow
from finai_api.security import require_permission
from finai_api.services import execution_publication as publication
from finai_api.services import report_workflows as records
from finai_api.services import transformation_runs
from finai_api.services.regulatory_monitors import check as regulatory_source_check
from finai_api.services.report_inputs import ReportInputRequest, retain_assessment
from finai_api.services.tb_frontier import analyze
from finai_api.services.workspace import detail
from finai_api.transformation_workflow import TransformationWorkflow


@activity.defn(name="report_source_hierarchy")
def hierarchy(context: dict[str, Any]) -> dict[str, Any]:
    principal = records.current_principal(context["actor_id"], context["scope"])
    require_permission(principal, "read")
    require_permission(principal, "ingest")
    identity = context["workflow_id"]
    record = records.read(principal, identity)
    request = record["request"]["report"]
    attempt = f"hierarchy:{context['generation']}:{activity.info().attempt}"
    records.event(
        principal, identity, attempt + ":started", {"node": "hierarchy", "state": "RUNNING"}
    )
    try:
        proofs = []
        for receipt_id in sorted(set(request["receipt_ids"])):
            receipt = detail(principal, receipt_id).receipt
            if receipt.classifier_version == "1c-biff-tb-layout/1":
                proof = analyze(
                    [{"source_row": c.source_row, "values": c.values} for c in receipt.candidates]
                )
                proofs.append(
                    {
                        "receipt_id": receipt_id,
                        "source_sha256": receipt.source_sha256,
                        "proof": proof,
                    }
                )
        # Full proof lives in scoped G8 storage. Temporal retains only small output references.
        records.event(
            principal,
            identity,
            attempt + ":completed",
            {"node": "hierarchy", "state": "COMPLETED", "proofs": proofs},
        )
        if record["definition"].get("outputs"):
            publication.stage(
                principal,
                identity,
                context["generation"],
                "hierarchy",
                "source-hierarchy/1",
                {"proofs": proofs},
            )
        return {"event_id": attempt + ":completed", "sources_checked": len(proofs)}
    except Exception:
        records.event(
            principal, identity, attempt + ":failed", {"node": "hierarchy", "state": "FAILED"}
        )
        raise


@activity.defn(name="report_source_coverage")
def coverage(context: dict[str, Any]) -> dict[str, Any]:
    principal = records.current_principal(context["actor_id"], context["scope"])
    require_permission(principal, "read")
    require_permission(principal, "ingest")
    identity = context["workflow_id"]
    record = records.read(principal, identity)
    attempt = f"coverage:{context['generation']}:{activity.info().attempt}"
    records.event(
        principal,
        identity,
        attempt + ":started",
        {"node": "coverage", "state": "RUNNING", "attempt": activity.info().attempt},
    )
    try:
        result = retain_assessment(
            principal, ReportInputRequest.model_validate(record["request"]["report"])
        )
        output = {"assessment_id": result["assessment_id"], "state": result["state"]}
        records.event(
            principal,
            identity,
            attempt + ":completed",
            {"node": "coverage", "state": "COMPLETED", "output": output},
        )
        if record["definition"].get("outputs"):
            publication.stage(
                principal,
                identity,
                context["generation"],
                "coverage",
                "source-assessment/1",
                output,
            )
        return output
    except Exception:
        records.event(
            principal,
            identity,
            attempt + ":failed",
            {
                "node": "coverage",
                "state": "FAILED",
                "reason": "Source coverage execution failed; retry after remediation",
            },
        )
        raise


@activity.defn(name="execution_publish")
def publish_outputs(context: dict[str, Any]) -> dict[str, Any]:
    principal = records.current_principal(context["actor_id"], context["scope"])
    manifest = publication.publish(principal, context["workflow_id"], context["generation"])
    # Only a small immutable reference crosses into Temporal history.
    return {"publication_id": manifest["publication_id"], "generation": manifest["generation"]}


async def main() -> None:
    settings = get_settings()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    with ThreadPoolExecutor(max_workers=4) as executor:
        worker = Worker(
            client,
            task_queue="g8-report-source-v1",
            workflows=[ReportSourceWorkflow, RegulatorySourceCheck, TransformationWorkflow],
            activities=[
                coverage,
                hierarchy,
                publish_outputs,
                regulatory_source_check,
                transformation_runs.load,
                transformation_runs.execute_node,
                transformation_runs.publish,
            ],
            activity_executor=executor,
        )
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
