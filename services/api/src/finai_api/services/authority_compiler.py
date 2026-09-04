from finai_api.domain.authority import (
    CompileHydrationRequest,
    ConstructionReceipt,
    DerivationRule,
    EpistemicState,
    FieldAuthority,
    SourceField,
    canonical_sha256,
)


class AuthorityCompiler:
    """Classifies what an evidence package can prove without promoting it."""

    def compile(self, request: CompileHydrationRequest) -> ConstructionReceipt:
        observed = {field.name: field for field in request.authority_contract.observed_fields}
        rules = {rule.output_field: rule for rule in request.derivation_rules}
        evidence_ids = tuple(item.evidence_id for item in request.authority_contract.evidence)

        fields = tuple(
            self._classify(
                name=item.name,
                inference_candidate=item.inference_candidate,
                observed=observed,
                rules=rules,
                evidence_ids=evidence_ids,
            )
            for item in request.requested_fields
        )
        request_hash = canonical_sha256(request)
        return ConstructionReceipt(
            receipt_id=f"cr_{request_hash[:24]}",
            compiler_version=request.compiler_version,
            authority_contract_id=request.authority_contract.contract_id,
            authority_contract_version=request.authority_contract.contract_version,
            exact_scope=request.authority_contract.scope,
            request_sha256=request_hash,
            fields=fields,
        )

    def _classify(
        self,
        *,
        name: str,
        inference_candidate: bool,
        observed: dict[str, SourceField],
        rules: dict[str, DerivationRule],
        evidence_ids: tuple[str, ...],
    ) -> FieldAuthority:
        if name in observed:
            source_field = observed[name]
            source_path = source_field.source_path
            return FieldAuthority(
                field=name,
                state=EpistemicState.OBSERVED,
                authoritative=True,
                evidence_ids=evidence_ids,
                source_path=source_path,
                rationale="Directly declared by the source authority contract.",
            )

        rule = rules.get(name)
        if rule is not None:
            missing = tuple(
                dependency for dependency in rule.depends_on if dependency not in observed
            )
            if not missing:
                return FieldAuthority(
                    field=name,
                    state=EpistemicState.DERIVED,
                    authoritative=True,
                    evidence_ids=evidence_ids,
                    rule_id=rule.rule_id,
                    rule_version=rule.rule_version,
                    dependencies=rule.depends_on,
                    rationale="Deterministically derived from observed dependencies.",
                )
            return FieldAuthority(
                field=name,
                state=EpistemicState.UNAVAILABLE,
                authoritative=False,
                rule_id=rule.rule_id,
                rule_version=rule.rule_version,
                dependencies=rule.depends_on,
                rationale=(
                    "Derivation is blocked; missing observed dependencies: "
                    f"{', '.join(missing)}."
                ),
            )

        if inference_candidate:
            return FieldAuthority(
                field=name,
                state=EpistemicState.INFERRED,
                authoritative=False,
                rationale="Candidate interpretation requires human review and supporting evidence.",
            )

        return FieldAuthority(
            field=name,
            state=EpistemicState.UNAVAILABLE,
            authoritative=False,
            rationale="The source authority contract does not support this field.",
        )
