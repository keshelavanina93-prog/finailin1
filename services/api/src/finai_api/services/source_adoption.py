"""Reviewed recurring-source transitions in the shared canonical resource graph."""

from datetime import UTC, datetime
from uuid import UUID, uuid5

from psycopg.rows import dict_row

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.source_adoption import (
    AdoptionDefinition,
    FamilyDefinition,
    PinnedResource,
    SourceFamilySelection,
    require_compatible_adoption,
)
from finai_api.services import resources
from finai_api.services.accounting_promotion import validate_current_binding
from finai_api.services.resource_lifecycle import _latest, _version
from finai_api.services.source_snapshot import derive_snapshot
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError


def pin(row):
    return PinnedResource.model_validate(
        {key: str(row[key]) for key in ("resource_id", "version_id", "content_hash")}
    )


class Resolver:
    """Use the publication resolver when writing; keep every observed input fenced."""

    def __init__(self, conn, principal, target=None):
        self.conn, self.principal, self.target = conn, principal, target
        self.rows = {}

    def __call__(self, identity):
        identity = str(identity)
        if identity in self.rows:
            return self.rows[identity]
        if len(self.rows) >= 100:
            raise WorkspaceError(422, "Recurring-source review exceeds 100 exact input resources")
        row = (
            self.target(identity)
            if self.target
            else resources._get(self.conn, self.principal.scope.tenant_id, UUID(identity))
        )
        if not row.get("system_from") or row["evidence_class"] == "REFERENCE_TEMPLATE":
            raise WorkspaceError(409, "Recurring sources require existing reviewed dependencies")
        reference = pin(row)
        with self.conn.cursor(row_factory=dict_row) as cursor:
            current = _version(cursor, self.principal, reference)
            event = _latest(cursor, self.principal, reference.version_id)
        if pin(current) != reference or (
            event
            and (
                event["payload"]["target_state"] in {"REVOKED", "SUPERSEDED"}
                or event["payload"]["availability_state"] != "AVAILABLE"
            )
        ):
            raise WorkspaceError(409, "Recurring-source dependency is unavailable or changed")
        self.rows[identity] = row
        return row

    def exact(self, reference, kind):
        row = self(reference.resource_id)
        if row["object_type"] != kind or UUID(str(row["version_id"])) != reference.version_id:
            raise WorkspaceError(
                409, "Selected recurring-source reference is stale or incompatible"
            )
        with self.conn.cursor(row_factory=dict_row) as cursor:
            upstream_authority(cursor, self.principal.scope.tenant_id, reference.version_id)
        if kind == "SourceAccountingBinding":
            validate_current_binding(self.conn, self.principal, row)
        return row


def family_content(principal, selection, resolver):
    binding = resolver.exact(selection.baseline_binding, "SourceAccountingBinding")
    baseline = derive_snapshot(principal, binding, resolver)
    key = (
        f"source-family:{baseline.company.resource_id}:"
        f"{selection.source_system}:{selection.family_key}"
    )
    identity = canonical_id(principal.scope.tenant_id, "SourceFamily", key)
    definition = FamilyDefinition(selection=selection, baseline=baseline)
    attrs = {
        "company_id": str(baseline.company.resource_id),
        "baseline_binding_id": str(baseline.binding.resource_id),
        "source_system": selection.source_system,
        "family_key": selection.family_key,
        "definition": definition.model_dump(mode="json"),
    }
    return identity, key, selection.display_name, attrs


def adoption_content(principal, selection, resolver):
    family = resolver.exact(selection.family, "SourceFamily")
    retained = FamilyDefinition.model_validate(family["attributes"]["definition"])
    _, _, _, expected_family = family_content(principal, retained.selection, resolver)
    if expected_family != family["attributes"]:
        raise WorkspaceError(409, "Reviewed source family no longer matches its exact baseline")
    predecessor = derive_snapshot(
        principal,
        resolver.exact(selection.predecessor_binding, "SourceAccountingBinding"),
        resolver,
    )
    successor = derive_snapshot(
        principal, resolver.exact(selection.successor_binding, "SourceAccountingBinding"), resolver
    )
    if selection.predecessor_adoption is None:
        if predecessor != retained.baseline:
            raise WorkspaceError(
                409, "A non-baseline predecessor needs its exact reviewed adoption"
            )
    else:
        prior = resolver.exact(selection.predecessor_adoption, "SourceSnapshotAdoption")
        link = AdoptionDefinition.model_validate(prior["attributes"]["definition"])
        if link.family != pin(family) or link.successor != predecessor:
            raise WorkspaceError(409, "Predecessor is not an exact member of this reviewed family")
    require_compatible_adoption(retained.baseline, predecessor, successor, selection.policy)
    identity = uuid5(
        selection.family.resource_id, f"source-adoption:{successor.binding.resource_id}"
    )
    definition = AdoptionDefinition(
        selection=selection, family=pin(family), predecessor=predecessor, successor=successor
    )
    attrs = {
        "company_id": str(successor.company.resource_id),
        "family_id": str(selection.family.resource_id),
        "predecessor_binding_id": str(predecessor.binding.resource_id),
        "successor_binding_id": str(successor.binding.resource_id),
        "definition": definition.model_dump(mode="json"),
    }
    if selection.predecessor_adoption:
        attrs["predecessor_adoption_id"] = str(selection.predecessor_adoption.resource_id)
    name = f"{retained.selection.display_name[:187]} · {successor.observed_from}"
    return identity, "source-adoption:" + str(identity), name, attrs


def require_single_successor(conn, principal, identity, attrs):
    """Called again under the canonical promotion lock, including scheduled heads."""
    with conn.cursor(row_factory=dict_row) as cursor:
        hidden = cursor.execute(
            "SELECT public.g8_has_hidden_current_dependents(%s) AS hidden",
            (UUID(attrs["family_id"]),),
        ).fetchone()
        if not hidden or hidden["hidden"]:
            raise WorkspaceError(
                409, "Recurring-source membership is incomplete in the authorized context"
            )
        found = cursor.execute(
            resources.HEAD_SELECT
            + "WHERE h.tenant_id=%s AND v.object_type='SourceSnapshotAdoption' "
            "AND v.authority_state='APPROVED' AND v.resource_id<>%s "
            "AND v.attributes->>'family_id'=%s "
            "AND (v.attributes->>'predecessor_binding_id'=%s "
            "OR v.attributes->>'successor_binding_id'=%s) LIMIT 1",
            (
                principal.scope.tenant_id,
                identity,
                attrs["family_id"],
                attrs["predecessor_binding_id"],
                attrs["successor_binding_id"],
            ),
        ).fetchone()
    if found:
        raise WorkspaceError(
            409, "This family already has a reviewed successor or snapshot membership"
        )


def validate(conn, principal, item, target, previous, access_entity=None):
    """Generic proposals cannot forge the server-derived compatibility observations."""
    if item.evidence_class != "USER_ASSERTED":
        raise WorkspaceError(422, "Recurring-source adoption requires explicit human review")
    if previous and item.authority_state == "REVOKED":
        if (
            item.attributes != previous["attributes"]
            or item.display_name != previous["display_name"]
        ):
            raise WorkspaceError(
                422, "Withdrawal must preserve the original reviewed source contract"
            )
        return
    if item.authority_state != "APPROVED":
        raise WorkspaceError(422, "A new recurring-source contract cannot start withdrawn")
    resolver = Resolver(
        conn,
        principal,
        lambda identity: target(identity, str(item.resource_id), "SOURCE_REVIEW:" + identity),
    )
    try:
        if item.object_type == "SourceFamily":
            saved = FamilyDefinition.model_validate(item.attributes["definition"])
            expected = family_content(principal, saved.selection, resolver)
        else:
            if previous:
                raise WorkspaceError(
                    409, "A retained adoption is immutable; review a new successor"
                )
            saved = AdoptionDefinition.model_validate(item.attributes["definition"])
            expected = adoption_content(principal, saved.selection, resolver)
            require_single_successor(conn, principal, expected[0], expected[3])
    except (ValueError, KeyError, TypeError) as exc:
        raise WorkspaceError(
            422, "Invalid recurring-source compatibility contract: " + str(exc)
        ) from exc
    identity, key, name, attrs = expected
    policy_source = resolver(
        attrs["company_id"] if item.object_type == "SourceFamily" else attrs["family_id"]
    )
    if access_entity is not None and access_entity != policy_source["access_entity"]:
        raise WorkspaceError(
            403, "Recurring source contracts must preserve the exact company/family access boundary"
        )
    if (item.resource_id, item.identity_key, item.display_name, item.attributes) != (
        identity,
        key,
        name,
        attrs,
    ):
        raise WorkspaceError(
            422, "Recurring-source contract differs from retained bytes and reviewed meaning"
        )


def prepare(principal, selection):
    with resources.resource_connection(principal, repeatable_read=True) as conn:
        resolver = Resolver(conn, principal)
        try:
            if isinstance(selection, SourceFamilySelection):
                kind, content = "SourceFamily", family_content(principal, selection, resolver)
            else:
                kind, content = (
                    "SourceSnapshotAdoption",
                    adoption_content(principal, selection, resolver),
                )
                require_single_successor(conn, principal, content[0], content[3])
        except ValueError as exc:
            raise WorkspaceError(422, str(exc)) from exc
        identity, key, name, attrs = content
        previous = resources.current_resources(principal, [identity]).get(str(identity))
        return {
            "resource_id": str(identity),
            "object_type": kind,
            "identity_key": key,
            "display_name": name,
            "attributes": attrs,
            "previous": previous,
            "source_versions": {key: str(row["version_id"]) for key, row in resolver.rows.items()},
            "accounting_aggregation_authorized": False,
        }


def propose(principal, selection):
    from finai_api.security import require_permission

    require_permission(principal, "ontology_propose")
    prepared = prepare(principal, selection)
    prior = prepared["previous"]
    if prior and (
        prior["attributes"] == prepared["attributes"]
        or prepared["object_type"] == "SourceSnapshotAdoption"
    ):
        raise WorkspaceError(
            409, "This recurring-source contract is already published or scheduled"
        )
    identity = UUID(prepared["resource_id"])
    return resources.propose(
        principal,
        ResourceProposal(
            title="Review recurring source compatibility",
            rationale=selection.rationale,
            access_entity=principal.scope.legal_entity_id,
            mutations=[
                ResourceMutation(
                    resource_id=identity,
                    expected_version_id=UUID(prior["version_id"]) if prior else None,
                    object_type=prepared["object_type"],
                    identity_key=prepared["identity_key"],
                    display_name=prepared["display_name"],
                    attributes=prepared["attributes"],
                    valid_from=datetime.now(UTC),
                    evidence_class="USER_ASSERTED",
                )
            ],
            source_versions={
                identity: {UUID(k): UUID(v) for k, v in prepared["source_versions"].items()}
            },
        ),
    )


def read_successor(principal, reference: VersionReference):
    """Consume an accepted transition by reopening its exact successor source scope.

    This does not combine snapshots, create postings, or inherit an old period.
    The ordinary source and Function paths retain their own accounting gates.
    """
    with resources.resource_connection(principal, repeatable_read=True) as conn:
        resolver = Resolver(conn, principal)
        row = resolver.exact(reference, "SourceSnapshotAdoption")
        definition = AdoptionDefinition.model_validate(row["attributes"]["definition"])
        expected = adoption_content(principal, definition.selection, resolver)
        if expected[3] != row["attributes"]:
            raise WorkspaceError(409, "Reviewed adoption no longer matches its exact source inputs")
        return {
            "adoption": pin(row).model_dump(mode="json"),
            "family": definition.family.model_dump(mode="json"),
            "policy": definition.selection.policy,
            "source": definition.successor.model_dump(mode="json"),
            "accounting_aggregation_authorized": False,
        }
