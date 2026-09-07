"""Shared rule completeness and explicit journal-side dimension validation."""

from datetime import datetime
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.journal_dimensions import LineDimensions, PolicyDefinition, SourceAttribution
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.services.period_control import available, pin
from finai_api.services.workspace import WorkspaceError


def policy_identity(tenant, account_id):
    key = "account:" + str(account_id)
    return canonical_id(tenant, "AccountDimensionPolicy", key), key


def require_node(conn, principal, node, kind, at):
    if (
        not node
        or node["object_type"] != kind
        or node["authority_state"] != "APPROVED"
        or node["evidence_class"] == "REFERENCE_TEMPLATE"
    ):
        raise WorkspaceError(409, f"Reviewed {kind} is unavailable")
    if at is None:
        return node
    start = node["valid_from"]
    end = node["valid_to"]
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    if isinstance(end, str):
        end = datetime.fromisoformat(end)
    if start > at or (end is not None and end <= at):
        raise WorkspaceError(409, f"{kind} is not effective at publication time")
    available(conn, principal, str(node["version_id"]))
    return node


def edge(conn, principal, source, field, target):
    rows = conn.execute(
        "SELECT target_resource_id,target_version_id FROM resource_dependencies "
        "WHERE tenant_id=%s AND version_id=%s AND relation=%s",
        (principal.scope.tenant_id, UUID(str(source["version_id"])), "FIELD:" + field),
    ).fetchall()
    if (
        len(rows) != 1
        or str(rows[0][0]) != str(target["resource_id"])
        or str(rows[0][1]) != str(target["version_id"])
        or source["attributes"].get(field) != str(target["resource_id"])
    ):
        raise WorkspaceError(409, f"Exact {field} relationship is stale or unavailable")


def exact_requested(conn, principal, ref, kind, at):
    with conn.cursor(row_factory=dict_row) as cursor:
        node = cursor.execute(
            "SELECT v.*,i.identity_key FROM resource_versions v "
            "JOIN canonical_identities i USING(tenant_id,resource_id) WHERE v.tenant_id=%s "
            "AND v.resource_id=%s AND v.version_id=%s AND v.system_from<=%s "
            "AND v.version_id=g8_effective_version_id(v.tenant_id,v.resource_id,%s)",
            (principal.scope.tenant_id, ref.resource_id, ref.version_id, at, at),
        ).fetchone()
    return require_node(conn, principal, node, kind, at)


def requested_target(conn, principal, item, identifier, relation, at):
    """Only policy/rule relations may select an exact current-effective older editing version."""
    refs = {}
    kind = None
    if item.object_type == "AccountDimensionPolicy" and (
        relation.startswith("DIMENSION_POLICY_RULE:") or relation.startswith("BOUND_SOURCE:")
    ):
        definition = PolicyDefinition.model_validate(item.attributes.get("definition"))
        refs = {str(ref.resource_id): ref for ref in definition.rules}
        kind = "AccountDimensionRule"
    elif item.object_type == "JournalLine" and (
        relation in {"FIELD:dimension_policy_id", "DIMENSION_POLICY"}
        or relation.startswith(("DIMENSION_RULE:", "BOUND_SOURCE:"))
    ):
        definition = LineDimensions.model_validate(item.attributes.get("dimensions"))
        if identifier == str(definition.policy.resource_id):
            refs = {identifier: definition.policy}
            kind = "AccountDimensionPolicy"
        elif relation.startswith(("DIMENSION_RULE:", "BOUND_SOURCE:")):
            policy = exact_requested(
                conn, principal, definition.policy, "AccountDimensionPolicy", at
            )
            declared = PolicyDefinition.model_validate(policy["attributes"]["definition"])
            refs = {str(ref.resource_id): ref for ref in declared.rules}
            kind = "AccountDimensionRule"
    ref = refs.get(identifier)
    return exact_requested(conn, principal, ref, kind, at) if ref else None


def complete(conn, principal, account, refs, at):
    result = conn.execute(
        "SELECT g8_account_rule_set_complete(%s,%s,%s,%s::uuid[],%s)",
        (
            principal.scope.tenant_id,
            UUID(str(account["resource_id"])),
            UUID(str(account["version_id"])),
            [ref.version_id for ref in refs],
            at,
        ),
    ).fetchone()
    if not result or result[0] is not True:
        raise WorkspaceError(409, "The exact complete account rule set is unavailable or changed")


def inspect_policy(conn, principal, policy, account, target, at, owner=None):
    """Current completeness; historical consumers deliberately do not call this method."""
    attrs = policy["attributes"]
    owner = owner or str(policy["resource_id"])
    try:
        definition = PolicyDefinition.model_validate(attrs.get("definition"))
    except ValueError as exc:
        raise WorkspaceError(
            422, "A typed exact rule set and explicit review reason are required"
        ) from exc
    if attrs.get("account_id") != str(account["resource_id"]):
        raise WorkspaceError(422, "Dimension policy belongs to another account")
    chart = target(account["attributes"]["chart_id"], owner, "DIMENSION_ACCOUNT_CHART")
    company = target(chart["attributes"]["legal_entity_id"], owner, "DIMENSION_ACCOUNT_COMPANY")
    for node, kind in [
        (account, "LocalAccount"),
        (chart, "LocalChartOfAccounts"),
        (company, "LegalEntity"),
    ]:
        require_node(conn, principal, node, kind, at)
    edge(conn, principal, account, "chart_id", chart)
    edge(conn, principal, chart, "legal_entity_id", company)
    if attrs.get("chart_id") != str(chart["resource_id"]) or attrs.get("legal_entity_id") != str(
        company["resource_id"]
    ):
        raise WorkspaceError(422, "Dimension policy company and chart disagree with its account")
    # Retained policies require exact context edges; newly proposed policies are checked by target.
    if policy.get("system_from") is not None:
        for field, node in [
            ("account_id", account),
            ("chart_id", chart),
            ("legal_entity_id", company),
        ]:
            edge(conn, principal, policy, field, node)
    complete(conn, principal, account, definition.rules, at)
    rules = {}
    prefix = "DIMENSION_POLICY_RULE:" if policy.get("system_from") is None else "DIMENSION_RULE:"
    for ref in definition.rules:
        rule = target(str(ref.resource_id), owner, prefix + str(ref.resource_id))
        require_node(conn, principal, rule, "AccountDimensionRule", at)
        if pin(rule) != ref.model_dump(mode="json"):
            raise WorkspaceError(409, "Requested dimension rule version changed")
        edge(conn, principal, rule, "account_id", account)
        dimension = target(
            rule["attributes"]["dimension_id"],
            owner,
            "DIMENSION_DEFINITION:" + str(ref.resource_id),
        )
        require_node(conn, principal, dimension, "DimensionDefinition", at)
        edge(conn, principal, rule, "dimension_id", dimension)
        key = str(dimension["resource_id"])
        if key in rules:
            raise WorkspaceError(422, "Account policy contains duplicate dimension requirements")
        rules[key] = (rule, dimension)
    return rules


def validate_policy(conn, principal, item, target, proposal, at):
    attrs = item.attributes
    owner = str(item.resource_id)
    expected, key = policy_identity(principal.scope.tenant_id, attrs["account_id"])
    if (
        item.resource_id != expected
        or item.identity_key != key
        or item.evidence_class == "REFERENCE_TEMPLATE"
    ):
        raise WorkspaceError(
            422, "Account dimension policy requires its canonical account identity"
        )
    if any(
        m.object_type in {"AccountDimensionRule", "JournalLine", "JournalEntry"}
        for m in proposal.mutations
    ):
        raise WorkspaceError(
            422, "Review rules, completeness policy and journals in separate proposals"
        )
    account = target(attrs["account_id"], owner, "DIMENSION_POLICY_ACCOUNT")
    if account["access_entity"] not in (principal.scope.legal_entity_id, "__PLATFORM__"):
        raise WorkspaceError(403, "Account dimension policy must preserve the account access scope")
    pseudo = {**item.model_dump(mode="json"), "version_id": None}
    inspect_policy(conn, principal, pseudo, account, target, at, owner)


def validate_line(conn, principal, item, target, proposal, at):
    attrs = item.attributes
    owner = str(item.resource_id)
    try:
        definition = LineDimensions.model_validate(attrs.get("dimensions"))
    except ValueError as exc:
        raise WorkspaceError(
            422,
            "Journal line requires an exact dimension policy and explicit assignments",
        ) from exc
    if attrs.get("dimension_policy_id") != str(definition.policy.resource_id):
        raise WorkspaceError(422, "Journal line dimension policy reference and exact pin disagree")
    if any(
        m.object_type in {"AccountDimensionPolicy", "AccountDimensionRule"}
        for m in proposal.mutations
    ):
        raise WorkspaceError(422, "Review dimension policy before journal publication")
    account = target(attrs["account_id"], owner, "DIMENSION_LINE_ACCOUNT")
    policy = target(attrs["dimension_policy_id"], owner, "DIMENSION_POLICY")
    require_node(conn, principal, policy, "AccountDimensionPolicy", at)
    if pin(policy) != definition.policy.model_dump(mode="json"):
        raise WorkspaceError(409, "Journal dimension policy version changed")
    rules = inspect_policy(conn, principal, policy, account, target, at, owner)
    assigned = set()
    for assignment in definition.assignments:
        member = target(
            str(assignment.member.resource_id),
            owner,
            "DIMENSION_MEMBER:" + str(assignment.member.resource_id),
        )
        require_node(conn, principal, member, "DimensionMember", at)
        if pin(member) != assignment.member.model_dump(mode="json"):
            raise WorkspaceError(409, "Dimension member version changed")
        dimension_id = member["attributes"]["dimension_id"]
        if dimension_id not in rules or dimension_id in assigned:
            raise WorkspaceError(
                422, "Journal dimensions contain a duplicate or disallowed dimension"
            )
        assigned.add(dimension_id)
        dimension = rules[dimension_id][1]
        edge(conn, principal, member, "dimension_id", dimension)
        if isinstance(assignment.provenance, SourceAttribution):
            validate_attribution(
                conn, principal, item, assignment, member, dimension, account, target, at
            )
    if any(
        rule["attributes"]["required"] and identity not in assigned
        for identity, (rule, _) in rules.items()
    ):
        raise WorkspaceError(422, "Journal line is missing a required account dimension")


def validate_attribution(conn, principal, item, assignment, member, dimension, account, target, at):
    provenance = assignment.provenance
    owner = str(item.resource_id)
    source = target(
        str(provenance.assignment.resource_id),
        owner,
        "DIMENSION_SOURCE:" + str(member["resource_id"]),
    )
    require_node(conn, principal, source, "SourceDimensionAssignment", at)
    if source["evidence_class"] != "SOURCE_BOUND":
        raise WorkspaceError(
            422, "Reviewed source attribution requires source-bound assignment evidence"
        )
    if pin(source) != provenance.assignment.model_dump(
        mode="json"
    ) or provenance.side != item.attributes.get("side"):
        raise WorkspaceError(
            422, "Reviewed source attribution must match its exact assignment and journal side"
        )
    observation = target(
        source["attributes"]["observation_id"], owner, "DIMENSION_SOURCE_OBSERVATION"
    )
    context = target(
        source["attributes"]["company_dimension_id"], owner, "DIMENSION_SOURCE_COMPANY"
    )
    record = target(item.attributes["source_record_id"], owner, "DIMENSION_JOURNAL_RECORD")
    company = target(
        context["attributes"]["legal_entity_id"], owner, "DIMENSION_ATTRIBUTION_COMPANY"
    )
    chart = target(account["attributes"]["chart_id"], owner, "DIMENSION_ATTRIBUTION_CHART")
    for node, kind in [
        (observation, "SourceJournalMovement"),
        (context, "CompanyDimension"),
        (record, "SourceRecord"),
    ]:
        require_node(conn, principal, node, kind, at)
        if node["evidence_class"] != "SOURCE_BOUND":
            raise WorkspaceError(
                422, "Reviewed source attribution requires source-bound row and company evidence"
            )
    edge(conn, principal, source, "observation_id", observation)
    edge(conn, principal, source, "company_dimension_id", context)
    edge(conn, principal, source, "member_id", member)
    edge(conn, principal, context, "dimension_id", dimension)
    edge(conn, principal, chart, "legal_entity_id", company)
    edge(conn, principal, observation, "legal_entity_id", company)
    edge(conn, principal, context, "legal_entity_id", company)
    edge(conn, principal, observation, provenance.side.lower() + "_account_id", account)
    edge(conn, principal, observation, "source_record_id", record)
    cell = target(source["attributes"]["source_record_id"], owner, "DIMENSION_SOURCE_CELL")
    header = target(context["attributes"]["source_record_id"], owner, "DIMENSION_SOURCE_HEADER")
    evidence = target(record["attributes"]["evidence_id"], owner, "DIMENSION_SOURCE_EVIDENCE")
    for node, kind in [
        (cell, "SourceRecord"),
        (header, "SourceRecord"),
        (evidence, "SourceEvidence"),
    ]:
        require_node(conn, principal, node, kind, at)
    edge(conn, principal, source, "source_record_id", cell)
    edge(conn, principal, context, "source_record_id", header)
    for node in [record, cell, header, source, observation, context]:
        edge(conn, principal, node, "evidence_id", evidence)
    from types import SimpleNamespace

    from finai_api.services.source_dimensions import validate_assignment

    nodes = {str(node["resource_id"]): node for node in [observation, context, member, cell]}
    validate_assignment(
        SimpleNamespace(
            resource_id=source["resource_id"],
            attributes=source["attributes"],
            evidence_class=source["evidence_class"],
        ),
        lambda identity, *_: nodes[identity],
    )


def historical(conn, principal, line, account, at):
    """Inspect exact retained relationships without applying today's rule completeness."""
    from finai_api.services.company_journals import exact

    result = {"state": "UNESTABLISHED", "policy": None, "assignments": [], "issues": []}
    if not line["attributes"].get("dimensions") or not line["attributes"].get(
        "dimension_policy_id"
    ):
        result["issues"] = ["No retained explicit analytical completeness policy"]
        return result
    try:
        definition = LineDimensions.model_validate(line["attributes"]["dimensions"])

        def linked(source, ref, relation, kind):
            with conn.cursor(row_factory=dict_row) as cursor:
                node = exact(cursor, principal, ref.resource_id, ref.version_id, at)
            rows = conn.execute(
                "SELECT target_resource_id,target_version_id FROM resource_dependencies "
                "WHERE tenant_id=%s AND version_id=%s AND relation=%s",
                (principal.scope.tenant_id, source["version_id"], relation),
            ).fetchall()
            if (
                node is None
                or node["object_type"] != kind
                or len(rows) != 1
                or str(rows[0][0]) != str(ref.resource_id)
                or str(rows[0][1]) != str(ref.version_id)
            ):
                raise WorkspaceError(
                    409, "Retained analytical dependency is unavailable or inconsistent"
                )
            return node

        policy = linked(
            line, definition.policy, "FIELD:dimension_policy_id", "AccountDimensionPolicy"
        )
        result["policy"] = policy
        if str(definition.policy.resource_id) != line["attributes"]["dimension_policy_id"]:
            raise WorkspaceError(409, "Retained policy identity disagrees with the line")
        edge(conn, principal, policy, "account_id", account)
        declared = PolicyDefinition.model_validate(policy["attributes"]["definition"])
        rules = {}
        from finai_api.services.company_journals import linked as field

        with conn.cursor(row_factory=dict_row) as cursor:
            chart = field(cursor, principal, account, "chart_id", at)
            company = field(cursor, principal, chart, "legal_entity_id", at) if chart else None
        if not chart or not company:
            raise WorkspaceError(409, "Retained policy company/chart context is unavailable")
        edge(conn, principal, policy, "chart_id", chart)
        edge(conn, principal, policy, "legal_entity_id", company)

        for ref in declared.rules:
            rule = linked(
                policy, ref, "DIMENSION_POLICY_RULE:" + str(ref.resource_id), "AccountDimensionRule"
            )
            edge(conn, principal, rule, "account_id", account)
            with conn.cursor(row_factory=dict_row) as cursor:
                dimension = field(cursor, principal, rule, "dimension_id", at)
            if (
                not dimension
                or dimension["object_type"] != "DimensionDefinition"
                or str(dimension["resource_id"]) in rules
            ):
                raise WorkspaceError(409, "Retained dimension rule is incomplete or duplicated")
            rules[str(dimension["resource_id"])] = (rule, dimension)
        assigned = set()
        for assignment in definition.assignments:
            member = linked(
                line,
                assignment.member,
                "DIMENSION_MEMBER:" + str(assignment.member.resource_id),
                "DimensionMember",
            )
            key = member["attributes"]["dimension_id"]
            if key not in rules or key in assigned:
                raise WorkspaceError(409, "Retained assignment is duplicated or outside the policy")
            assigned.add(key)
            edge(conn, principal, member, "dimension_id", rules[key][1])
            if isinstance(assignment.provenance, SourceAttribution):
                source = linked(
                    line,
                    assignment.provenance.assignment,
                    "DIMENSION_SOURCE:" + str(member["resource_id"]),
                    "SourceDimensionAssignment",
                )
                edge(conn, principal, source, "member_id", member)
                if assignment.provenance.side != line["attributes"].get("side"):
                    raise WorkspaceError(
                        409, "Retained side attribution disagrees with its journal line"
                    )
                from types import SimpleNamespace

                def retained_target(identity, owner, relation):
                    rows = conn.execute(
                        "SELECT target_version_id FROM resource_dependencies WHERE tenant_id=%s "
                        "AND version_id=%s AND target_resource_id=%s AND relation=%s",
                        (principal.scope.tenant_id, line["version_id"], UUID(identity), relation),
                    ).fetchall()
                    if len(rows) != 1:
                        raise WorkspaceError(409, "Retained attribution dependency is unavailable")
                    with conn.cursor(row_factory=dict_row) as cursor:
                        node = exact(cursor, principal, UUID(identity), rows[0][0], at)
                    if node is None:
                        raise WorkspaceError(409, "Retained attribution version is unavailable")
                    return node

                validate_attribution(
                    conn,
                    principal,
                    SimpleNamespace(resource_id=line["resource_id"], attributes=line["attributes"]),
                    assignment,
                    member,
                    rules[key][1],
                    account,
                    retained_target,
                    None,
                )
            result["assignments"].append(
                {
                    "member": member,
                    "dimension": rules[key][1],
                    "provenance": assignment.provenance.model_dump(mode="json"),
                }
            )
        if any(
            rule["attributes"]["required"] and key not in assigned
            for key, (rule, _) in rules.items()
        ):
            raise WorkspaceError(409, "Retained required analytical assignment is missing")
        result["state"] = "COMPLETE"
    except (WorkspaceError, ValueError, KeyError) as exc:
        result["state"] = "INCOMPLETE_OR_UNAVAILABLE"
        result["issues"] = [
            exc.detail
            if isinstance(exc, WorkspaceError)
            else "Retained analytical declaration is invalid or incomplete"
        ]
    return result
