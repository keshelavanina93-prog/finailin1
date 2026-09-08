"""Explicit reviewed authority for a retained source family to produce journal pairs."""

from finai_api.domain.source_journal_compatibility import CompatibilityDefinition
from finai_api.services.source_accounting_context import validate_active_selection
from finai_api.services.workspace import WorkspaceError


def validate(item, target, owner=None):
    attrs, owner = item.attributes, owner or str(item.resource_id)
    spec = CompatibilityDefinition.model_validate(attrs["definition"])
    binding = target(attrs["accounting_binding_id"], owner, "COMPATIBILITY_BINDING")
    scope = target(attrs["scope_id"], owner, "COMPATIBILITY_SCOPE")
    config, observed = binding["attributes"], scope["attributes"]
    if str(binding["version_id"]) != str(spec.binding_version_id) or str(
        scope["version_id"]
    ) != str(spec.scope_version_id):
        raise WorkspaceError(409, "Compatibility binding or scope version changed")
    if (
        binding["object_type"] != "SourceAccountingBinding"
        or scope["object_type"] != "SourceAccountingScope"
    ):
        raise WorkspaceError(422, "Compatibility needs exact accounting binding and source scope")
    if (
        config["scope_id"] != str(scope["resource_id"])
        or observed["legal_entity_id"] != attrs["legal_entity_id"]
        or spec.source_profile != observed["source_profile"]
        or spec.sheet != observed["worksheet"]
    ):
        raise WorkspaceError(422, "Compatibility differs from retained source identity")
    for key in ("ledger_id", "book_id", "period_id", "currency_id"):
        if attrs[key] != config[key]:
            raise WorkspaceError(422, "Compatibility accounting context differs from its binding")
    for key in ("amount_field", "amount_semantics", "vat_treatment"):
        if getattr(spec, key) != config.get(key):
            raise WorkspaceError(422, "Compatibility amount or VAT policy differs from its binding")
    if config.get("granularity") != spec.grain:
        raise WorkspaceError(422, "Compatibility needs a reviewed row-grain binding")
    evidence = target(observed["evidence_id"], owner, "COMPATIBILITY_EVIDENCE")
    if evidence["attributes"]["sha256"] != spec.source_sha256:
        raise WorkspaceError(422, "Compatibility source hash differs from retained evidence")
    validate_active_selection(
        config, observed, lambda ref: target(ref, owner, "COMPATIBILITY_CONTEXT:" + ref)
    )
    return spec


def require(item, binding, scope, target):
    identity = item.attributes.get("source_compatibility_id")
    if not identity:
        raise WorkspaceError(
            422, "Source family needs reviewed source-to-journal compatibility authority"
        )
    authority = target(identity, str(item.resource_id), "SOURCE_JOURNAL_COMPATIBILITY")
    if (
        authority["object_type"] != "SourceJournalCompatibility"
        or authority["authority_state"] != "APPROVED"
        or authority["evidence_class"] == "REFERENCE_TEMPLATE"
        or authority["attributes"]["accounting_binding_id"] != str(binding["resource_id"])
        or authority["attributes"]["scope_id"] != str(scope["resource_id"])
    ):
        raise WorkspaceError(422, "Reviewed source-to-journal compatibility is unavailable")
    from types import SimpleNamespace

    return validate(
        SimpleNamespace(resource_id=authority["resource_id"], attributes=authority["attributes"]),
        target,
        str(item.resource_id),
    )
