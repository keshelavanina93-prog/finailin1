"""Compile retained Function evidence into one non-authoritative analysis contract."""

from finai_api.domain.semantic_analysis import Projection, ProjectionRequest, Section, Selection
from finai_api.security import require_permission
from finai_api.services import function_invocations
from finai_api.services.semantic_analysis_support import Resolver, digest
from finai_api.services.workspace import WorkspaceError


def load(principal, invocation_id):
    history = function_invocations.history(principal, invocation_id)
    if history["status"] != "SUCCEEDED":
        raise WorkspaceError(409, "Analysis requires a completed retained result")
    with function_invocations._database(principal) as c:
        row = c.execute(
            "SELECT plan,plan_hash FROM function_invocations WHERE tenant_id=%s AND request_id=%s",
            (principal.scope.tenant_id, invocation_id),
        ).fetchone()
    if row is None:
        raise WorkspaceError(404, "Analysis invocation unavailable")
    from finai_api.services.function_execution import _digest

    plan, result, receipt = row["plan"], history["output"], history["receipt"]
    if (
        _digest({key: value for key, value in plan.items() if key != "plan_hash"})
        != row["plan_hash"]
        or plan["plan_hash"] != row["plan_hash"]
        or receipt["plan_hash"] != row["plan_hash"]
        or result.get("plan_hash") != row["plan_hash"]
        or result.get("invocation_plan_hash") != row["plan_hash"]
        or receipt["request_id"] != str(invocation_id)
        or result.get("invocation_request_id") != str(invocation_id)
        or receipt["function"] != plan["function"]
        or result.get("function") != plan["function"]
        or result.get("implementation") != plan["implementation"]
        or receipt["implementation"] != plan["implementation"]
        or result.get("static_dependencies") != plan["static_dependencies"]
        or result.get("contract") != "function-result/1"
        or any(
            value.get("current_use_authorized") is not False
            or value.get("business_effect_authorized") is not False
            for value in (history, receipt, result)
        )
    ):
        raise WorkspaceError(409, "Analysis result differs from its retained execution contract")
    resolver = Resolver(principal, plan)
    function = resolver.version(plan["function"])
    if function["object_type"] != "FunctionDefinition" or function["authority_state"] != "APPROVED":
        raise WorkspaceError(409, "Analysis requires its original reviewed Function")
    return history, plan, resolver


def project(principal, request: ProjectionRequest):
    require_permission(principal, "ontology_read")
    history, plan, resolver = load(principal, request.invocation_id)
    implementation = plan["implementation"]["implementation_id"]
    if implementation == "accounting.retained-posted-movements/v1":
        from finai_api.services.semantic_analysis_posted import build
    elif implementation == "ontology.object-set-derived/v1" and plan.get("group_count"):
        from finai_api.services.semantic_analysis_counts import build
    elif implementation == "ontology.object-set-derived/v1":
        from finai_api.services.semantic_analysis_objects import build
    else:
        raise WorkspaceError(
            422,
            "This retained result has no supported analytical measure contract; inspect its source",
        )
    with resolver.read_session():
        descriptor, rows, contributors = build(history, plan, resolver, request.company_id)
    if descriptor.company.resource_id != request.company_id:
        raise WorkspaceError(404, "Analysis unavailable for this company")
    revision = digest(
        {
            "descriptor": descriptor.model_dump(mode="json"),
            "rows": [row.model_dump(mode="json") for row in rows],
        }
    )
    if request.descriptor_sha256 and request.descriptor_sha256 != revision:
        raise WorkspaceError(
            409, "Analysis descriptor changed; explicitly reopen the retained result"
        )
    definitions = {field.key: field for field in descriptor.fields}
    if len(definitions) != len(descriptor.fields) or len({row.key for row in rows}) != len(rows):
        raise WorkspaceError(409, "Analysis descriptor has ambiguous fields or retained rows")
    for selection in request.filters:
        field = definitions.get(selection.field)
        if field is None or not field.filterable:
            raise WorkspaceError(422, "This field is not an available analysis filter")

        def matches(value, selection=selection):
            return (
                value.state == selection.state
                and type(value.value) is type(selection.value)
                and value.value == selection.value
            )

        if not any(matches(option) for option in field.options):
            raise WorkspaceError(422, "Analysis filter is unavailable in this retained result")
        rows = [row for row in rows if matches(row.values[selection.field])]
    sections = []
    if request.group_by:
        field = definitions.get(request.group_by)
        if field is None or not field.groupable:
            raise WorkspaceError(422, "This field cannot partition the retained analysis rows")
        for option in field.options:
            keys = [row.key for row in rows if row.values[field.key] == option]
            if keys:
                sections.append(
                    Section(
                        label=option.label or str(option.value)
                        if option.state == "VALUE"
                        else option.state.title(),
                        row_keys=keys,
                    )
                )
    else:
        sections = [Section(label=descriptor.title, row_keys=[row.key for row in rows])]
    selected = None
    if request.selected_row is not None:
        selected_rows = [row for row in rows if row.key == request.selected_row]
        if not selected_rows:
            raise WorkspaceError(422, "Selected group is outside the current retained view")
        group = contributors[request.selected_row]
        if request.contributor_index >= len(group):
            raise WorkspaceError(422, "Contributor position is outside the selected group")
        selected = Selection(
            row_key=request.selected_row,
            contributor_index=request.contributor_index,
            contributor_count=len(group),
            contributor=group[request.contributor_index],
        )
    return Projection(
        descriptor=descriptor,
        descriptor_sha256=revision,
        rows=rows,
        total_rows=len(contributors),
        sections=sections,
        selection=selected,
        request=request,
    )
