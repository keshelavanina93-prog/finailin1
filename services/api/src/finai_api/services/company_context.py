"""Company working context is a projection of versioned ontology, not a name filter."""

from datetime import UTC, datetime
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.resources import CanonicalResource
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError

KINDS = [
    "CompanyWorkspace",
    "EnterpriseGroup",
    "LegalEntity",
    "DomainPack",
    "Relationship",
    "SubsidiaryRelationship",
    "BusinessUnit",
    "LicensedOperator",
    "ConsolidationGroup",
    "ConsolidationUnit",
    "Ledger",
    "AccountingBook",
    "FiscalCalendar",
    "FiscalPeriod",
    "LocalChartOfAccounts",
    "Currency",
    "DimensionDefinition",
    "CompanyDimension",
    "SourceAccountingScope",
    "SourceAccountingBinding",
    "CorporateDisclosureBinding",
    "SourceCorporateObservation",
    "Licence",
    "LicenceNoticeBinding",
    "SourceLicenceNotice",
    "LinkType",
    "Facility",
    "OperationalNetwork",
    "AssetPortfolio",
]


def project(nodes, pins, company_id=None, pinned_scopes=()):
    by_id = {n["resource_id"]: n for n in nodes}
    # Historical pins explain a reviewed selection; they never replace snapshot state.
    scope_versions = {
        n["version_id"]: n
        for n in [*nodes, *pinned_scopes]
        if n["object_type"] == "SourceAccountingScope"
    }
    bindings_by_scope = {}
    for binding in nodes:
        if binding["object_type"] != "SourceAccountingBinding":
            continue
        scope = scope_versions.get(pins.get((binding["version_id"], "scope_id")))
        if scope and scope["resource_id"] == binding["attributes"].get("scope_id"):
            bindings_by_scope.setdefault(scope["resource_id"], []).append(binding)

    def linked(node, field):
        pin = pins.get((node["version_id"], field))
        target = by_id.get(node["attributes"].get(field))
        if target and pin == target["version_id"]:
            return target
        return None

    workspaces = []
    for node in nodes:
        if node["object_type"] != "CompanyWorkspace":
            continue
        company, enterprise, pack = [
            linked(node, f) for f in ("company_id", "enterprise_id", "domain_pack_id")
        ]
        if company and enterprise and pack:
            workspaces.append(
                {
                    "configuration": node,
                    "company": company,
                    "enterprise": enterprise,
                    "domain_pack": pack,
                }
            )
    source_companies = {}
    reported_groups = {}
    for node in nodes:
        if node["object_type"] == "SourceAccountingScope":
            owner = linked(node, "legal_entity_id")
            if owner:
                source_companies[owner["resource_id"]] = owner
        if node["object_type"] == "CorporateDisclosureBinding":
            reporter, party, observation = [
                linked(node, field)
                for field in ("reporter_id", "related_entity_id", "observation_id")
            ]
            if not reporter or not party or not observation:
                continue
            observed = observation["attributes"]["observation"]
            if observed["reported_role"] != "SUBSIDIARY":
                continue
            key = (reporter["resource_id"], node["attributes"]["reporting_year"])
            group = reported_groups.setdefault(
                key,
                {
                    "reporter": reporter,
                    "reporting_year": key[1],
                    "members": [],
                    "basis": "REPORTED_GROUP_DISCLOSURE",
                },
            )
            group["members"].append(
                {
                    "company": party,
                    "binding": node,
                    "observation": observation,
                    "reported_percent": observed.get("reported_percent"),
                    "former_indicator": observed.get("former_indicator", ""),
                }
            )
    result = {
        "workspaces": workspaces,
        "context": None,
        "source_companies": list(source_companies.values()),
        "reported_groups": list(reported_groups.values()),
    }
    if company_id is None:
        return result
    company = by_id.get(str(company_id))
    if not company or company["object_type"] != "LegalEntity":
        raise WorkspaceError(404, "Company is unavailable in this ontology snapshot")

    related = {company["resource_id"]: company}
    relationships, disclosures, accounting, licences = [], [], [], []
    # Only explicit typed relationships establish structure. Disclosure bindings stay evidence.
    for node in nodes:
        if node["object_type"] == "SubsidiaryRelationship":
            owner, child = linked(node, "owner_id"), linked(node, "subsidiary_id")
            if owner and child and str(company_id) in {owner["resource_id"], child["resource_id"]}:
                relationships.append(
                    {"kind": "OWNERSHIP", "record": node, "source": owner, "target": child}
                )
                related[owner["resource_id"]] = owner
                related[child["resource_id"]] = child
        if node["object_type"] == "CorporateDisclosureBinding":
            reporter, party, observation = [
                linked(node, f) for f in ("reporter_id", "related_entity_id", "observation_id")
            ]
            if (
                reporter
                and party
                and observation
                and str(company_id) in {reporter["resource_id"], party["resource_id"]}
            ):
                disclosures.append(
                    {
                        "binding": node,
                        "reporter": reporter,
                        "party": party,
                        "observation": observation,
                    }
                )
        if node["object_type"] == "SourceAccountingScope":
            owner = linked(node, "legal_entity_id")
            if owner and owner["resource_id"] == str(company_id):
                bindings = bindings_by_scope.get(node["resource_id"], [])
                accounting.append({"scope": node, "bindings": bindings})
        if node["object_type"] == "LicenceNoticeBinding":
            owner = linked(node, "company_id")
            if owner and owner["resource_id"] == str(company_id):
                licences.append(
                    {
                        "binding": node,
                        "notice": linked(node, "notice_id"),
                        "licence": linked(node, "licence_id"),
                    }
                )

    # Walk only structural edges, never financial facts or incidental evidence references.
    allowed = {
        "HAS_LEGAL_ENTITY",
        "HAS_BUSINESS_UNIT",
        "HAS_OPERATOR",
        "PARTICIPATES_IN",
        "USES_DOMAIN_PACK",
        "OPERATES",
        "HAS_LEDGER",
        "ALLOWS_DIMENSION_MODEL",
    }
    for _ in range(8):
        before = len(related)
        for node in nodes:
            if node["object_type"] != "Relationship":
                continue
            source, target, relation = [
                linked(node, f) for f in ("source_id", "target_id", "relation_id")
            ]
            if not source or not target or not relation or relation["identity_key"] not in allowed:
                continue
            outgoing = (
                source["resource_id"] in related and source["object_type"] != "EnterpriseGroup"
            )
            incoming = target["resource_id"] == str(company_id)
            if outgoing or incoming:
                related[target["resource_id"]] = target
                related[source["resource_id"]] = source
                if not any(
                    r["record"]["resource_id"] == node["resource_id"] for r in relationships
                ):
                    relationships.append(
                        {
                            "kind": relation["identity_key"],
                            "record": node,
                            "source": source,
                            "target": target,
                        }
                    )
        if len(related) == before:
            break

    ledgers = []
    for node in nodes:
        if node["object_type"] != "Ledger" or linked(node, "legal_entity_id") != company:
            continue
        fields = {f: linked(node, f) for f in ("calendar_id", "chart_id", "currency_id")}
        books = [
            b
            for b in nodes
            if b["object_type"] == "AccountingBook" and linked(b, "ledger_id") == node
        ]
        periods = [
            p
            for p in nodes
            if p["object_type"] == "FiscalPeriod"
            and fields["calendar_id"]
            and linked(p, "calendar_id") == fields["calendar_id"]
        ]
        ledgers.append(
            {
                "ledger": node,
                **fields,
                "books": books,
                "periods": periods,
                "ready": all(fields.values()) and bool(books),
            }
        )
    result["context"] = {
        "company": company,
        "relationships": relationships,
        "ledgers": ledgers,
        "accounting_sources": accounting,
        "disclosures": disclosures,
        "licence_evidence": licences,
        "structural_resources": list(related.values()),
        "dimensions": [
            n
            for n in nodes
            if n["object_type"] == "CompanyDimension" and linked(n, "legal_entity_id") == company
        ],
        "accounting_state": "CONFIGURED"
        if any(ledger["ready"] for ledger in ledgers)
        else "ACCOUNTING_CONFIGURATION_REQUIRED",
    }
    return result


def inspect_binding_eligibility(principal, result):
    """Current advisory checks are independent of the requested historical snapshot."""
    from finai_api.services.accounting_binding_status import inspect

    if result["context"] is None:
        return
    checked = 0
    for source in result["context"]["accounting_sources"]:
        statuses = source["binding_eligibility"] = {}
        for binding in source["bindings"]:
            if checked < 100:
                statuses[binding["version_id"]] = inspect(principal, binding)
                checked += 1
            else:
                statuses[binding["version_id"]] = {
                    "state": "ELIGIBILITY_NOT_CHECKED",
                    "reason": "Company preview reached its 100 selection check bound; "
                    "open the source selection for its current eligibility",
                    "checked_at": None,
                    "advisory": True,
                    "current_use_authorized": False,
                    "eligible_for_accounting": False,
                    "binding_version_id": binding["version_id"],
                    "reviewed_source_use": binding["attributes"].get("source_use"),
                }


def select_accounting(result, ledger_id=None, book_id=None, period_id=None):
    if not any((ledger_id, book_id, period_id)):
        return None
    if not all((ledger_id, book_id, period_id)) or result["context"] is None:
        raise WorkspaceError(422, "Select company, ledger, book and period together")
    context = result["context"]
    ledger = next(
        (row for row in context["ledgers"] if row["ledger"]["resource_id"] == str(ledger_id)), None
    )
    if not ledger or not ledger["ready"]:
        raise WorkspaceError(422, "Ledger is not configured for this company")
    book = next((row for row in ledger["books"] if row["resource_id"] == str(book_id)), None)
    period = next((row for row in ledger["periods"] if row["resource_id"] == str(period_id)), None)
    if not book or not period:
        raise WorkspaceError(422, "Book or period does not belong to the selected ledger context")
    return {
        key: {"resource_id": node["resource_id"], "version_id": node["version_id"]}
        for key, node in {
            "legal_entity_id": context["company"],
            "ledger_id": ledger["ledger"],
            "book_id": book,
            "period_id": period,
            "chart_id": ledger["chart_id"],
            "currency_id": ledger["currency_id"],
            "calendar_id": ledger["calendar_id"],
        }.items()
    }


def resolve(
    principal,
    company_id: UUID | None = None,
    valid_at=None,
    known_at=None,
    ledger_id=None,
    book_id=None,
    period_id=None,
):
    known_at = known_at or datetime.now(UTC)
    valid_at = valid_at or known_at
    if valid_at.tzinfo is None or known_at.tzinfo is None:
        raise WorkspaceError(422, "Company context times require timezone information")
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        conn.execute(
            "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))",
            (f"canonical:{principal.scope.tenant_id}",),
        )
        rows = cursor.execute(
            "SELECT * FROM (SELECT DISTINCT ON(v.resource_id) v.*,i.identity_key "
            "FROM resource_versions v JOIN canonical_identities i USING(tenant_id,resource_id) "
            "WHERE v.tenant_id=%s AND v.object_type=ANY(%s) AND v.system_from<=%s "
            "AND v.valid_from<=%s AND (v.valid_to IS NULL OR v.valid_to>%s) "
            "ORDER BY v.resource_id,v.system_from DESC,v.version_id) snapshot "
            "WHERE authority_state='APPROVED' AND evidence_class<>'REFERENCE_TEMPLATE' "
            "ORDER BY display_name,resource_id LIMIT 5001",
            (principal.scope.tenant_id, KINDS, known_at, valid_at, valid_at),
        ).fetchall()
        if len(rows) > 5000:
            raise WorkspaceError(409, "Company snapshot exceeds the supported resource bound")
        nodes = [CanonicalResource.model_validate(r).model_dump(mode="json") for r in rows]
        deps = cursor.execute(
            "SELECT version_id,relation,target_version_id FROM resource_dependencies "
            "WHERE tenant_id=%s AND version_id=ANY(%s::uuid[]) AND relation LIKE 'FIELD:%%' "
            "LIMIT 50001",
            (principal.scope.tenant_id, [r["version_id"] for r in rows]),
        ).fetchall()
        if len(deps) > 50000:
            raise WorkspaceError(409, "Company snapshot exceeds the supported dependency bound")
        pins = {
            (str(d["version_id"]), d["relation"].removeprefix("FIELD:")): str(
                d["target_version_id"]
            )
            for d in deps
        }
        scope_pins = [
            pins[(n["version_id"], "scope_id")]
            for n in nodes
            if n["object_type"] == "SourceAccountingBinding"
            and (n["version_id"], "scope_id") in pins
        ]
        retained_scopes = cursor.execute(
            "SELECT v.*,i.identity_key FROM resource_versions v "
            "JOIN canonical_identities i USING(tenant_id,resource_id) "
            "WHERE v.tenant_id=%s AND v.version_id=ANY(%s::uuid[]) "
            "AND v.object_type='SourceAccountingScope' AND v.system_from<=%s LIMIT 5001",
            (principal.scope.tenant_id, scope_pins, known_at),
        ).fetchall()
        pinned_scopes = [
            CanonicalResource.model_validate(r).model_dump(mode="json") for r in retained_scopes
        ]
        result = project(nodes, pins, company_id, pinned_scopes)
        result["accounting_selection"] = select_accounting(result, ledger_id, book_id, period_id)
    # Do not hold the snapshot connection while the shared guard inspects current state.
    inspect_binding_eligibility(principal, result)
    return {**result, "valid_at": valid_at.isoformat(), "known_at": known_at.isoformat()}
