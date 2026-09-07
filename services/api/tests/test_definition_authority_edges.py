"""Synthetic contract fixtures for exact journal history and executable definitions.

These tests run production validators against explicit retained-version adapter
fixtures. They establish neither authentic source acceptance nor financial posting.
"""

from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4, uuid5

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.journal_dimensions import PolicyDefinition
from finai_api.domain.resources import ResourceMutation
from finai_api.domain.review import Principal
from finai_api.services import company_journals
from finai_api.services import journal_dimensions as dimensions
from finai_api.services.ontology_definition_validation import validate_definition
from finai_api.services.temporal_definition_dependency import TemporalDependencyUnavailable
from finai_api.services.workspace import WorkspaceError

AT = datetime(2026, 9, 8, tzinfo=UTC)


def mutation(kind, definition=None, **attrs):
    return ResourceMutation(
        object_type=kind,
        identity_key="fixture:" + uuid4().hex,
        display_name="Synthetic authority fixture",
        valid_from=AT,
        attributes=attrs | ({"definition": definition} if definition is not None else {}),
        evidence_class="SOURCE_BOUND",
    )


def pin(node):
    return {key: str(node[key]) for key in ("resource_id", "version_id")}


class RetainedGraph:
    def __init__(self):
        self.principal = Principal(
            actor_id="synthetic-dimension-reader",
            display_name="Fixture reader",
            scope=ExactScope(
                tenant_id=uuid4(),
                legal_entity_id="fixture-company",
                period="2026-09",
                currency="GEL",
            ),
            permissions=("ontology_read",),
        )
        self.nodes = {}
        self.edges = {}
        self.calls = []
        self.rows = []
        self.one = None
        self.lifecycle = {}
        self.rule_set_complete = True

    def add(self, kind, **attributes):
        node = {
            "resource_id": uuid4(),
            "version_id": uuid4(),
            "object_type": kind,
            "identity_key": "synthetic:" + uuid4().hex,
            "attributes": attributes,
            "authority_state": "APPROVED",
            "evidence_class": "SOURCE_BOUND",
            "valid_from": AT - timedelta(days=1),
            "valid_to": None,
            "system_from": AT - timedelta(days=1),
            "access_entity": "fixture-company",
        }
        self.nodes[str(node["resource_id"])] = node
        for field, value in attributes.items():
            if isinstance(value, str) and value in self.nodes:
                self.link(node, "FIELD:" + field, self.nodes[value])
        return node

    def link(self, source, relation, target):
        self.edges[str(source["version_id"]), relation] = [
            (target["resource_id"], target["version_id"])
        ]

    def target(self, identity, *_args):
        return self.nodes[str(identity)]

    def execute(self, query, params):
        self.calls.append((query, params))
        assert params[0] == self.principal.scope.tenant_id
        self.one = None
        self.rows = []
        if "resource_lifecycle_events" in query:
            self.one = self.lifecycle.get(str(params[1]))
        elif "g8_account_rule_set_complete" in query:
            self.one = (self.rule_set_complete,)
        elif "g8_effective_version_id" in query:
            node = self.nodes.get(str(params[1]))
            self.one = node if node and node["version_id"] == params[2] else None
        elif "target_resource_id=%s" in query:
            self.rows = [
                (version,)
                for identity, version in self.edges.get((str(params[1]), params[3]), [])
                if str(identity) == str(params[2])
            ]
        elif "resource_dependencies" in query:
            self.rows = self.edges.get((str(params[1]), params[2]), [])
        else:
            raise AssertionError("Unexpected repository query: " + query)
        return self

    def cursor(self, **_kwargs):
        return nullcontext(self)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.one

    def exact(self, _cursor, principal, identity, version, at):
        assert principal == self.principal
        assert at == AT
        node = self.nodes.get(str(identity))
        return node if node and str(node["version_id"]) == str(version) else None

    def linked(self, _cursor, principal, source, field, at):
        refs = self.edges.get((str(source["version_id"]), "FIELD:" + field), [])
        return self.exact(None, principal, *refs[0], at) if len(refs) == 1 else None


@pytest.fixture
def journal(monkeypatch):
    graph = RetainedGraph()
    company = graph.add("LegalEntity")
    chart = graph.add("LocalChartOfAccounts", legal_entity_id=str(company["resource_id"]))
    account = graph.add("LocalAccount", chart_id=str(chart["resource_id"]))
    dimension = graph.add("DimensionDefinition")
    member = graph.add("DimensionMember", dimension_id=str(dimension["resource_id"]), code="West")
    rule = graph.add(
        "AccountDimensionRule",
        account_id=str(account["resource_id"]),
        dimension_id=str(dimension["resource_id"]),
        required=True,
    )
    policy = graph.add(
        "AccountDimensionPolicy",
        account_id=str(account["resource_id"]),
        chart_id=str(chart["resource_id"]),
        legal_entity_id=str(company["resource_id"]),
        definition={
            "contract": "account-dimension-policy/1",
            "reason": "Explicit fixture completeness review",
            "rules": [pin(rule)],
        },
    )
    graph.link(policy, "DIMENSION_POLICY_RULE:" + str(rule["resource_id"]), rule)
    graph.link(policy, "DIMENSION_RULE:" + str(rule["resource_id"]), rule)
    evidence = graph.add("SourceEvidence", sha256="a" * 64)
    record = graph.add(
        "SourceRecord", evidence_id=str(evidence["resource_id"]), coordinate="Fixture!3"
    )
    cell = graph.add(
        "SourceRecord", evidence_id=str(evidence["resource_id"]), coordinate="Fixture!Y3"
    )
    header = graph.add(
        "SourceRecord", evidence_id=str(evidence["resource_id"]), coordinate="Fixture!Y2"
    )
    context = graph.add(
        "CompanyDimension",
        evidence_id=str(evidence["resource_id"]),
        legal_entity_id=str(company["resource_id"]),
        dimension_id=str(dimension["resource_id"]),
        source_record_id=str(header["resource_id"]),
        source_column="Y",
    )
    observation = graph.add(
        "SourceJournalMovement",
        evidence_id=str(evidence["resource_id"]),
        legal_entity_id=str(company["resource_id"]),
        debit_account_id=str(account["resource_id"]),
        source_record_id=str(record["resource_id"]),
        source_row_key="Fixture!3",
        source_details={"cells": {"Y": {"type": 1, "value": "West"}}},
    )
    source = graph.add(
        "SourceDimensionAssignment",
        evidence_id=str(evidence["resource_id"]),
        observation_id=str(observation["resource_id"]),
        company_dimension_id=str(context["resource_id"]),
        member_id=str(member["resource_id"]),
        source_record_id=str(cell["resource_id"]),
    )
    line = graph.add(
        "JournalLine",
        account_id=str(account["resource_id"]),
        side="DEBIT",
        source_record_id=str(record["resource_id"]),
        dimension_policy_id=str(policy["resource_id"]),
        dimensions={
            "contract": "journal-line-dimensions/1",
            "policy": pin(policy),
            "assignments": [
                {
                    "member": pin(member),
                    "provenance": {
                        "kind": "REVIEWED_SOURCE_ATTRIBUTION",
                        "side": "DEBIT",
                        "assignment": pin(source),
                        "reason": "Reviewed exact fixture source side",
                    },
                }
            ],
        },
    )
    graph.link(line, "DIMENSION_MEMBER:" + str(member["resource_id"]), member)
    relations = {
        "DIMENSION_SOURCE:" + str(member["resource_id"]): source,
        "DIMENSION_SOURCE_OBSERVATION": observation,
        "DIMENSION_SOURCE_COMPANY": context,
        "DIMENSION_JOURNAL_RECORD": record,
        "DIMENSION_ATTRIBUTION_COMPANY": company,
        "DIMENSION_ATTRIBUTION_CHART": chart,
        "DIMENSION_SOURCE_CELL": cell,
        "DIMENSION_SOURCE_HEADER": header,
        "DIMENSION_SOURCE_EVIDENCE": evidence,
    }
    for relation, node in relations.items():
        graph.link(line, relation, node)
    monkeypatch.setattr(company_journals, "exact", graph.exact)
    monkeypatch.setattr(company_journals, "linked", graph.linked)
    return SimpleNamespace(**locals())


def historical(case):
    return dimensions.historical(case.graph, case.graph.principal, case.line, case.account, AT)


def test_historical_dimension_assignment_retains_original_source_and_ignores_current_completeness(
    journal,
):
    journal.graph.rule_set_complete = False
    result = historical(journal)
    assert result["state"] == "COMPLETE"
    assert result["issues"] == []
    assert result["policy"]["version_id"] == journal.policy["version_id"]
    assert result["assignments"][0]["member"]["version_id"] == journal.member["version_id"]
    assert result["assignments"][0]["provenance"]["assignment"] == pin(journal.source)
    assert not any("g8_account_rule_set_complete" in query for query, _ in journal.graph.calls)


@pytest.mark.parametrize(
    "fault,issue",
    [
        ("policy_pin", "dependency is unavailable"),
        ("policy_identity", "identity disagrees"),
        ("chart", "company/chart context"),
        ("dimension_type", "rule is incomplete"),
        ("duplicate_rule", "rule is incomplete"),
        ("disallowed_member", "outside the policy"),
        ("duplicate_member", "outside the policy"),
        ("side", "side attribution disagrees"),
        ("source_edge", "attribution dependency"),
        ("source_version", "attribution version"),
        ("missing_assignment", "required analytical assignment"),
        ("invalid_declaration", "declaration is invalid"),
    ],
)
def test_history_with_unresolved_or_mismatched_retained_pins_never_claims_completeness(
    journal, fault, issue
):
    graph = journal.graph
    payload = journal.line["attributes"]["dimensions"]
    if fault == "policy_pin":
        payload["policy"]["version_id"] = str(uuid4())
    elif fault == "policy_identity":
        journal.line["attributes"]["dimension_policy_id"] = str(uuid4())
    elif fault == "chart":
        del graph.edges[str(journal.account["version_id"]), "FIELD:chart_id"]
    elif fault == "dimension_type":
        journal.dimension["object_type"] = "LocalAccount"
    elif fault == "duplicate_rule":
        rule = graph.add("AccountDimensionRule", **journal.rule["attributes"])
        journal.policy["attributes"]["definition"]["rules"].append(pin(rule))
        graph.link(journal.policy, "DIMENSION_POLICY_RULE:" + str(rule["resource_id"]), rule)
    elif fault == "disallowed_member":
        journal.member["attributes"]["dimension_id"] = str(uuid4())
    elif fault == "duplicate_member":
        payload["assignments"] *= 2
    elif fault == "side":
        journal.line["attributes"]["side"] = "CREDIT"
    elif fault == "source_edge":
        del graph.edges[str(journal.line["version_id"]), "DIMENSION_SOURCE_EVIDENCE"]
    elif fault == "source_version":
        journal.evidence["version_id"] = uuid4()
    elif fault == "missing_assignment":
        payload["assignments"] = []
    else:
        payload["contract"] = "unsupported/2"
    result = historical(journal)
    assert result["state"] == "INCOMPLETE_OR_UNAVAILABLE"
    assert issue in result["issues"][0]
    assert not any("g8_account_rule_set_complete" in query for query, _ in graph.calls)


@pytest.mark.parametrize(
    "changes",
    [
        {"object_type": "Industry"},
        {"authority_state": "REVOKED"},
        {"evidence_class": "REFERENCE_TEMPLATE"},
    ],
)
def test_dimension_context_requires_reviewed_correct_type(journal, changes):
    with pytest.raises(WorkspaceError, match="Reviewed LocalAccount") as error:
        dimensions.require_node(
            journal.graph, journal.graph.principal, journal.account | changes, "LocalAccount", AT
        )
    assert error.value.status == 409


def test_dimension_context_parses_exact_effective_window_and_lifecycle(journal):
    node = journal.account | {
        "valid_from": AT.isoformat(),
        "valid_to": (AT + timedelta(days=1)).isoformat(),
    }
    assert (
        dimensions.require_node(journal.graph, journal.graph.principal, node, "LocalAccount", AT)
        == node
    )
    with pytest.raises(WorkspaceError, match="effective at publication"):
        dimensions.require_node(
            journal.graph, journal.graph.principal, node, "LocalAccount", AT + timedelta(days=1)
        )
    journal.graph.lifecycle[str(node["version_id"])] = ({"target_state": "REVOKED"},)
    with pytest.raises(WorkspaceError, match="withdrawal or unavailability"):
        dimensions.require_node(journal.graph, journal.graph.principal, node, "LocalAccount", AT)


@pytest.mark.parametrize(
    "relation,identifier,expected",
    [
        ("FIELD:dimension_policy_id", "policy", "AccountDimensionPolicy"),
        ("DIMENSION_RULE:fixture", "rule", "AccountDimensionRule"),
        ("BOUND_SOURCE:fixture", "rule", "AccountDimensionRule"),
        ("UNRELATED", "rule", None),
    ],
)
def test_journal_target_override_only_resolves_declared_exact_policy_or_rule(
    journal, relation, identifier, expected
):
    candidate = mutation("JournalLine", **journal.line["attributes"])
    node = getattr(journal, identifier)
    result = dimensions.requested_target(
        journal.graph, journal.graph.principal, candidate, str(node["resource_id"]), relation, AT
    )
    if expected:
        assert result["object_type"] == expected
        assert pin(result) == pin(node)
        exact_calls = [
            params for query, params in journal.graph.calls if "g8_effective_version_id" in query
        ]
        assert exact_calls[-1] == (
            journal.graph.principal.scope.tenant_id,
            node["resource_id"],
            node["version_id"],
            AT,
            AT,
        )
    else:
        assert result is None


@pytest.mark.parametrize(
    "fault,message,status",
    [
        ("identity", "canonical account identity", 422),
        ("mixed", "separate proposals", 422),
        ("scope", "access scope", 403),
        ("definition", "typed exact rule set", 422),
        ("company", "company and chart disagree", 422),
        ("rule_pin", "rule version changed", 409),
        ("duplicate", "duplicate dimension", 422),
    ],
)
def test_dimension_policy_refuses_cross_scope_unreviewed_or_inexact_rule_population(
    journal, fault, message, status
):
    graph = journal.graph
    identity, key = dimensions.policy_identity(
        graph.principal.scope.tenant_id, journal.account["resource_id"]
    )
    item = mutation("AccountDimensionPolicy", **journal.policy["attributes"]).model_copy(
        update={"resource_id": identity, "identity_key": key}
    )
    proposal = SimpleNamespace(mutations=[item])
    if fault == "identity":
        item = item.model_copy(update={"resource_id": uuid4()})
    elif fault == "mixed":
        proposal.mutations.append(mutation("JournalLine"))
    elif fault == "scope":
        journal.account["access_entity"] = "another-company"
    elif fault == "definition":
        item.attributes["definition"] = {}
    elif fault == "company":
        item.attributes["legal_entity_id"] = str(uuid4())
    elif fault == "rule_pin":
        item.attributes["definition"]["rules"][0]["version_id"] = str(uuid4())
    elif fault == "duplicate":
        rule = graph.add("AccountDimensionRule", **journal.rule["attributes"])
        item.attributes["definition"]["rules"].append(pin(rule))
    with pytest.raises(WorkspaceError, match=message) as error:
        dimensions.validate_policy(graph, graph.principal, item, graph.target, proposal, AT)
    assert error.value.status == status


@pytest.mark.parametrize(
    "fault,message",
    [
        ("policy_id", "reference and exact pin disagree"),
        ("mixed_proposal", "before journal publication"),
        ("source_class", "source-bound assignment evidence"),
        ("record_class", "source-bound row and company evidence"),
    ],
)
def test_journal_refuses_shortcut_policy_and_source_authority(journal, fault, message):
    graph = journal.graph
    item = mutation("JournalLine", **journal.line["attributes"])
    proposal = SimpleNamespace(mutations=[item])
    if fault == "policy_id":
        item.attributes["dimension_policy_id"] = str(uuid4())
    elif fault == "mixed_proposal":
        proposal.mutations.append(mutation("AccountDimensionRule"))
    elif fault == "source_class":
        journal.source["evidence_class"] = "USER_ASSERTED"
    else:
        journal.record["evidence_class"] = "USER_ASSERTED"
    with pytest.raises(WorkspaceError, match=message) as error:
        dimensions.validate_line(graph, graph.principal, item, graph.target, proposal, AT)
    assert error.value.status == 422


def fact(**changes):
    return {
        "grain": ["account", "period", "unit"],
        "dimensions": ["account", "period", "unit"],
        "measure": "amount",
        "aggregation": "flow_sum",
        "time_field": "period",
        "unit_field": "unit",
        "source_family": "SYNTHETIC_APPROVED_FACT",
        "source_family_field": "family",
        "authority_basis": "Reviewed synthetic representation",
        "partition_fields": ["account"],
        **changes,
    }


def fact_fields():
    return {
        name: {"kind": kind, "required": True}
        for name, kind in {
            "account": "identifier",
            "period": "date",
            "unit": "reference",
            "family": "identifier",
            "amount": "decimal",
            "start": "date",
            "denominator": "decimal",
            "role": "text",
            "parent": "identifier",
        }.items()
    }


@pytest.mark.parametrize(
    "fault,message",
    [
        ("family", "source family"),
        ("missing_grain", "declared and required"),
        ("grain_kind", "scalar identities"),
        ("time", "date or timestamp"),
        ("period", "calendar dates"),
        ("unit", "explicit identity"),
        ("measure", "required numeric"),
        ("denominator", "denominator"),
        ("role", "Row role"),
        ("hierarchy", "compatible identities"),
    ],
)
def test_fact_contract_refuses_implicit_financial_semantics(fault, message):
    definition = fact()
    fields = fact_fields()
    if fault == "family":
        fields["family"]["required"] = False
    elif fault == "missing_grain":
        del fields["account"]
    elif fault == "grain_kind":
        fields["account"]["kind"] = "decimal"
    elif fault == "time":
        fields["period"]["kind"] = "text"
    elif fault == "period":
        definition.update(grain=["account", "period", "unit", "start"], period_start_field="start")
        fields["start"]["kind"] = "datetime"
    elif fault == "unit":
        fields["unit"]["kind"] = "text"
    elif fault == "measure":
        fields["amount"]["required"] = False
    elif fault == "denominator":
        definition.update(aggregation="ratio_of_sums", denominator_measure="denominator")
        fields["denominator"]["kind"] = "text"
    elif fault == "role":
        definition.update(row_role_field="role", included_row_role="DETAIL")
        fields["role"]["required"] = False
    elif fault == "hierarchy":
        definition.update(hierarchy_key_field="account", parent_key_field="parent")
        fields["parent"]["kind"] = "reference"
    with pytest.raises(WorkspaceError, match=message) as error:
        validate_definition(
            mutation("FactContract", definition, schema_id=str(uuid4())),
            {},
            {},
            lambda *_: {"identity_key": "ApprovedFact", "attributes": {"fields": fields}},
        )
    assert error.value.status == 422


def test_fact_contract_accepts_explicit_period_ratio_role_and_hierarchy_contract():
    definition = fact(
        grain=["account", "period", "unit", "start"],
        period_start_field="start",
        aggregation="ratio_of_sums",
        denominator_measure="denominator",
        row_role_field="role",
        included_row_role="DETAIL",
        hierarchy_key_field="account",
        parent_key_field="parent",
    )
    validate_definition(
        mutation("FactContract", definition, schema_id=str(uuid4())),
        {},
        {},
        lambda *_: {"identity_key": "ApprovedFact", "attributes": {"fields": fact_fields()}},
    )


@pytest.mark.parametrize(
    "fault,message",
    [
        (None, None),
        ("same", "distinct fact contracts"),
        ("grain", "shared declared dimensions"),
        ("time", "reporting period"),
        ("interval", "complete period interval"),
        ("ratio", "underlying components"),
        ("partition", "matching accounting partitions"),
    ],
)
def test_reconciliation_preserves_time_partition_and_representation_authority(fault, message):
    left, right = str(uuid4()), str(uuid4())
    contracts = {left: fact(), right: fact()}
    group = ["account", "period", "unit"]
    if fault == "same":
        right = left
    elif fault == "grain":
        group.append("unshared")
    elif fault == "time":
        group.remove("period")
    elif fault == "interval":
        contracts[left] = fact(
            grain=["account", "period", "unit", "start"], period_start_field="start"
        )
    elif fault == "ratio":
        contracts[left] = fact(aggregation="ratio_of_sums", denominator_measure="denominator")
    elif fault == "partition":
        contracts[right] = fact(partition_fields=[])
    item = mutation(
        "FactReconciliation",
        {
            "group_by": group,
            "absolute_tolerance": "0.01",
            "authority_side": "left",
            "relationship": "SOURCE_CONTROL",
            "rationale": "Preserve reviewed accounting grain",
        },
        left_contract_id=left,
        right_contract_id=right,
    )

    def target(identity, *_):
        return {"attributes": {"definition": contracts[identity]}}

    if message:
        with pytest.raises(WorkspaceError, match=message) as error:
            validate_definition(item, {}, {}, target)
        assert error.value.status == 422
    else:
        validate_definition(item, {}, {}, target)


@pytest.mark.parametrize(
    "source_bound,complete,current",
    [(False, False, False), (True, True, False), (True, False, False), (True, True, True)],
)
def test_matsne_interpretation_cannot_promote_capture_to_complete_law(
    source_bound, complete, current
):
    evidence, act = uuid4(), uuid4()
    definition = {
        "legal_status": "ENACTED",
        "source_version": "fixture-publication",
        "source_version_complete": complete,
        "provision": "Fixture provision",
        "activity": "DISTRIBUTION",
        "effective_from": "2026-01-01",
        "obligation": "Fixture obligation",
    }
    item = mutation("RegulatoryRule", definition, act_id=str(act), evidence_id=str(evidence))
    if not source_bound:
        item = item.model_copy(update={"evidence_class": "USER_ASSERTED"})
    seen = []

    def target(identity, _owner, relation):
        seen.append((identity, relation))
        return (
            {"attributes": {"reference": "MATSNE:123", "evidence_id": str(evidence)}}
            if identity == str(act)
            else {"attributes": {"observation": {"current_law_verified": current}}}
        )

    if not source_bound or (complete and not current):
        with pytest.raises(WorkspaceError) as error:
            validate_definition(item, {}, {}, target)
        assert error.value.status == 422
        assert (
            "retained source evidence" if not source_bound else "complete applicable law"
        ) in error.value.detail
    else:
        validate_definition(item, {}, {}, target)
    if source_bound:
        assert seen[-1] == (str(uuid5(evidence, "matsne-publication")), "REGULATORY_PUBLICATION")
    else:
        assert seen == []


@pytest.mark.parametrize("definition", [None, {"unknown": "shape"}])
def test_missing_or_invalid_definition_is_a_governed_validation_error(definition):
    with pytest.raises(WorkspaceError, match="Invalid ObjectTypeGroup") as error:
        validate_definition(mutation("ObjectTypeGroup", definition), {}, {}, lambda *_: {})
    assert error.value.status == 422


@pytest.mark.parametrize(
    "fault,message",
    [
        ("semantic_kind", "semantic contract"),
        ("semantic_type", "semantic contract"),
        ("unknown_type", "Unknown ontology type"),
    ],
)
def test_interface_definition_requires_shared_semantic_kind_and_canonical_target(fault, message):
    semantic = uuid4()
    field = {"kind": "text", "semantic_id": str(semantic)}
    if fault == "unknown_type":
        field = {"kind": "reference", "target_type": "UnknownType"}
    target = {
        "object_type": "SemanticContract" if fault != "semantic_type" else "LocalAccount",
        "attributes": {"kind": "integer" if fault == "semantic_kind" else "text"},
    }
    with pytest.raises(WorkspaceError, match=message):
        validate_definition(
            mutation("ObjectInterface", {"fields": {"label": field}}), {}, {}, lambda *_: target
        )


@pytest.mark.parametrize(
    "fault,message",
    [
        ("required", "required source field"),
        ("semantic", "semantic_id mapping"),
        ("target", "target_type mapping"),
    ],
)
def test_interface_implementation_cannot_erase_required_or_identity_semantics(fault, message):
    semantic, interface, schema = str(uuid4()), str(uuid4()), str(uuid4())
    spec = {
        "kind": "reference",
        "required": True,
        "semantic_id": semantic,
        "target_type": "LegalEntity",
    }
    actual = deepcopy(spec)
    actual[{"required": "required", "semantic": "semantic_id", "target": "target_type"}[fault]] = {
        "required": False,
        "semantic": str(uuid4()),
        "target": "LocalAccount",
    }[fault]
    nodes = {
        interface: {"attributes": {"definition": {"fields": {"company": spec}}}},
        schema: {"attributes": {"fields": {"company_id": actual}}},
    }
    with pytest.raises(WorkspaceError, match=message):
        validate_definition(
            mutation(
                "ObjectTypeImplementation",
                {"fields": {"company": "company_id"}},
                interface_id=interface,
                schema_id=schema,
            ),
            {},
            {},
            lambda identity, *_: nodes[identity],
        )


def test_incoming_traversal_skips_unavailable_unrelated_history_but_retains_declared_schema():
    schemas = {"LegalEntity": "company", "LocalAccount": "account", "LaterType": "later"}
    nodes = {
        "company": {"attributes": {"fields": {}}},
        "account": {
            "attributes": {
                "fields": {"company_id": {"kind": "reference", "target_type": "LegalEntity"}}
            }
        },
    }
    calls = []

    def target(identity, _owner, relation):
        calls.append((identity, relation))
        if identity == "later":
            raise TemporalDependencyUnavailable()
        return nodes[identity]

    item = mutation(
        "ObjectSetDefinition",
        {
            "object_type": "LegalEntity",
            "traversal": [{"name": "company_id", "direction": "incoming"}],
        },
    )
    validate_definition(item, schemas, {}, target)
    assert ("account", "DEFINITION_TYPE:LocalAccount") in calls
    assert ("later", "TRAVERSAL_CANDIDATE:LaterType") in calls
    del nodes["account"]["attributes"]["fields"]["company_id"]
    with pytest.raises(WorkspaceError, match="No declared incoming reference"):
        validate_definition(item, schemas, {}, target)


@pytest.mark.parametrize(
    "expression,result_kind,message",
    [
        ({"op": "field", "field": "unknown"}, "decimal", "declared scalar"),
        (
            {
                "op": "coalesce",
                "args": [{"op": "literal", "value": "1"}, {"op": "literal", "value": "text"}],
            },
            "text",
            "same kind",
        ),
        (
            {
                "op": "add",
                "args": [{"op": "literal", "value": "1"}, {"op": "literal", "value": "text"}],
            },
            "decimal",
            "numeric inputs",
        ),
        ({"op": "literal", "value": "text"}, "decimal", "declared result kind"),
    ],
)
def test_derived_definition_refuses_implicit_scalar_or_arithmetic_coercion(
    expression, result_kind, message
):
    with pytest.raises(WorkspaceError, match=message):
        validate_definition(
            mutation(
                "DerivedProperty",
                {"name": "result", "result_kind": result_kind, "expression": expression},
                schema_id=str(uuid4()),
            ),
            {},
            {},
            lambda *_: {"attributes": {"fields": {}}},
        )


def test_derived_expression_complexity_is_bounded_before_execution():
    expression = {"op": "literal", "value": "1"}
    for _ in range(11):
        expression = {"op": "add", "args": [expression, {"op": "literal", "value": "1"}]}
    with pytest.raises(WorkspaceError, match="complexity limit"):
        validate_definition(
            mutation(
                "DerivedProperty",
                {"name": "result", "result_kind": "decimal", "expression": expression},
                schema_id=str(uuid4()),
            ),
            {},
            {},
            lambda *_: {"attributes": {"fields": {}}},
        )


def test_policy_review_reason_cannot_be_whitespace_padded():
    with pytest.raises(ValueError, match="unpadded review reason"):
        PolicyDefinition(
            contract="account-dimension-policy/1", rules=[], reason=" Review fixture rules "
        )


@pytest.mark.parametrize(
    "fault,message,status",
    [
        (None, None, None),
        ("missing_identity", "identity and display fields", 422),
        ("canonical_reference", "required reference", 422),
        ("calculated_type", "exact source schema", 409),
        ("calculated_schema", "exact source schema", 409),
        ("display_kind", "display property must return text", 422),
        ("target_kind", "compatible canonical types", 422),
        ("required_unmapped", "every required target property", 422),
    ],
)
def test_calculated_object_binding_requires_exact_schema_and_preserves_target_types(
    fault, message, status
):
    source_id, destination_id, property_id = [str(uuid4()) for _ in range(3)]
    source_version, property_version = str(uuid4()), str(uuid4())
    property_pin = {"resource_id": property_id, "version_id": property_version}
    definition = {
        "identity_mode": "CANONICAL_REFERENCE",
        "identity_field": "company_id",
        "display_property": property_pin,
        "fields": [{"derived_property": property_pin, "target_field": "label"}],
    }
    nodes = {
        source_id: {
            "version_id": source_version,
            "attributes": {
                "fields": {
                    "company_id": {
                        "kind": "reference",
                        "target_type": "LegalEntity",
                        "required": True,
                    }
                }
            },
        },
        destination_id: {
            "identity_key": "LegalEntity",
            "attributes": {
                "fields": {
                    "label": {"kind": "text", "required": True},
                }
            },
        },
        property_id: {
            "object_type": "DerivedProperty",
            "version_id": property_version,
            "dependencies": [{"relation": "FIELD:schema_id", "version_id": source_version}],
            "attributes": {
                "definition": {
                    "name": "reviewed_label",
                    "result_kind": "text",
                    "expression": {"op": "literal", "value": "Synthetic label"},
                }
            },
        },
    }
    if fault == "missing_identity":
        definition["identity_field"] = "missing"
    elif fault == "canonical_reference":
        nodes[source_id]["attributes"]["fields"]["company_id"]["target_type"] = "LocalAccount"
    elif fault == "calculated_type":
        nodes[property_id]["object_type"] = "Metric"
    elif fault == "calculated_schema":
        nodes[property_id]["dependencies"][0]["version_id"] = str(uuid4())
    elif fault == "display_kind":
        nodes[property_id]["attributes"]["definition"]["result_kind"] = "decimal"
    elif fault == "target_kind":
        nodes[destination_id]["attributes"]["fields"]["label"]["kind"] = "identifier"
    elif fault == "required_unmapped":
        nodes[destination_id]["attributes"]["fields"]["required_code"] = {
            "kind": "identifier",
            "required": True,
        }
    calls = []

    def target(identity, owner, relation, version=None):
        calls.append((identity, owner, relation, version))
        return nodes[identity]

    item = mutation(
        "ObjectBinding", definition, source_schema_id=source_id, target_schema_id=destination_id
    )
    if message:
        with pytest.raises(WorkspaceError, match=message) as error:
            validate_definition(item, {}, {}, target)
        assert error.value.status == status
    else:
        validate_definition(item, {}, {}, target)
        assert (
            property_id,
            str(item.resource_id),
            "BINDING_DERIVED_PROPERTY:" + property_id,
            property_version,
        ) in calls
        assert len([call for call in calls if call[0] == property_id]) == 1


def test_traversal_rejects_mixed_destination_semantics_even_when_null_is_valid_for_both():
    nodes = {
        "root": {"attributes": {"fields": {}}},
        "text": {"attributes": {"fields": {"value": {"kind": "text", "required": False}}}},
        "decimal": {"attributes": {"fields": {"value": {"kind": "decimal", "required": False}}}},
        "link": {
            "attributes": {"sources": ["LegalEntity"], "targets": ["TextRecord", "NumericRecord"]}
        },
    }
    schemas = {"LegalEntity": "root", "TextRecord": "text", "NumericRecord": "decimal"}
    item = mutation(
        "ObjectSetDefinition",
        {
            "object_type": "LegalEntity",
            "traversal": [
                {"kind": "link", "name": "OBSERVES", "filters": [{"field": "value", "value": None}]}
            ],
        },
    )
    with pytest.raises(WorkspaceError, match="compatible destination field kinds"):
        validate_definition(
            item, schemas, {"OBSERVES": "link"}, lambda identity, *_: nodes[identity]
        )


def test_object_set_explicit_root_cannot_reinterpret_another_canonical_type():
    identity = str(uuid4())
    item = mutation(
        "ObjectSetDefinition", {"object_type": "LegalEntity", "resource_ids": [identity]}
    )
    with pytest.raises(WorkspaceError, match="root identity has a different object type"):
        validate_definition(
            item,
            {"LegalEntity": "schema"},
            {},
            lambda identifier, *_: (
                {"attributes": {"fields": {}}}
                if identifier == "schema"
                else {"object_type": "LocalAccount"}
            ),
        )


def test_type_group_does_not_repeat_canonical_object_types():
    with pytest.raises(WorkspaceError, match="unique object types"):
        validate_definition(
            mutation("ObjectTypeGroup", {"types": ["LegalEntity", "LegalEntity"]}),
            {},
            {},
            lambda *_: {},
        )
