"""Versioned platform definitions, never enterprise/company facts."""

from typing import Any
from uuid import UUID, uuid5

CATALOG_NAMESPACE = UUID("8c24e8eb-8af8-470a-9607-96390853617f")


def canonical_id(tenant: UUID, kind: str, key: str) -> UUID:
    return uuid5(CATALOG_NAMESPACE, f"{tenant}:{kind}:{key}")


SEMANTICS = {
    "OntologyDefinition": "definition",
    "SpatialGeometry": "geometry",
    "GeoJSONDocument": "geojson",
    "Name": "text",
    "Identifier": "identifier",
    "AccountCode": "identifier",
    "TaxCode": "identifier",
    "Text": "text",
    "Money": "money",
    "Amount": "decimal",
    "Quantity": "quantity",
    "CurrencyCode": "identifier",
    "Unit": "identifier",
    "Date": "date",
    "Time": "datetime",
    "Count": "integer",
    "Flag": "boolean",
    "CanonicalReference": "reference",
}

# required field -> semantic kind or a canonical target type. Optional fields carry '?'.
TYPE_FIELDS: dict[str, dict[str, str]] = {
    "SourceLicenceNotice": {
        "document_id": "Identifier", "source_record_id": "@SourceRecord",
        "notice": "OntologyDefinition",
    },
    "LicenceNoticeBinding": {
        "notice_id": "@SourceLicenceNotice", "company_id": "@LegalEntity", "licence_id": "@Licence",
        "identity_binding_id?": "@CorporateDisclosureBinding",
        "basis": "Identifier", "rationale": "Text",
    },
    "SourceCorporateObservation": {
        "document_id": "Identifier", "source_record_id": "@SourceRecord",
        "observation": "OntologyDefinition",
    },
    "CorporateDisclosureBinding": {
        "observation_id": "@SourceCorporateObservation", "reporter_id": "@LegalEntity",
        "related_entity_id": "@LegalEntity", "reporter_code": "Identifier",
        "reporting_year": "Count", "source_url": "Text", "relationship_basis": "Identifier",
        "rationale": "Text",
    },
    "SourceAccountDefinition": {
        "account_code": "AccountCode", "source_record_id": "@SourceRecord",
        "source_name": "Text", "definition": "OntologyDefinition",
    },
    "FactContract": {"schema_id": "@SchemaDefinition", "definition": "OntologyDefinition"},
    "FactReconciliation": {
        "left_contract_id": "@FactContract", "right_contract_id": "@FactContract",
        "definition": "OntologyDefinition",
    },
    "SourceJournalMovement": {
        "legal_entity_id": "@LegalEntity", "debit_account_id": "@LocalAccount",
        "credit_account_id": "@LocalAccount", "source_record_id": "@SourceRecord",
        "posting_date": "Date", "document_reference": "Text", "amount": "Amount",
        "source_family": "Identifier", "source_row_key": "Identifier",
        "unit_status": "Identifier", "source_details": "OntologyDefinition",
    },
    "SourceTrialBalanceRow": {
        "legal_entity_id": "@LegalEntity", "account_id?": "@LocalAccount",
        "source_record_id": "@SourceRecord", "period_start": "Date", "period_end": "Date",
        "source_row_role": "Identifier", "source_row_key": "Identifier",
        "parent_source_row_key?": "Identifier", "source_family": "Identifier",
        "unit_status": "Identifier", "source_details": "OntologyDefinition",
        "opening_debit?": "Amount", "opening_credit?": "Amount",
        "turnover_debit?": "Amount", "turnover_credit?": "Amount",
        "closing_debit?": "Amount", "closing_credit?": "Amount",
    },
    "ObjectSetDefinition": {"definition": "OntologyDefinition"},
    "ObjectInterface": {"definition": "OntologyDefinition"},
    "ObjectTypeImplementation": {
        "interface_id": "@ObjectInterface", "schema_id": "@SchemaDefinition",
        "definition": "OntologyDefinition",
    },
    "ObjectTypeGroup": {"definition": "OntologyDefinition"},
    "DerivedProperty": {"schema_id": "@SchemaDefinition", "definition": "OntologyDefinition"},
    "ObjectBinding": {
        "source_schema_id": "@SchemaDefinition", "target_schema_id": "@SchemaDefinition",
        "definition": "OntologyDefinition",
    },
    "EnterpriseGroup": {"code": "Identifier"},
    "BusinessDomain": {"code": "Identifier", "domain_pack?": "@DomainPack"},
    "LegalEntity": {"registration_code?": "Identifier", "jurisdiction?": "Text"},
    "SubsidiaryRelationship": {
        "owner_id": "@LegalEntity",
        "subsidiary_id": "@LegalEntity",
        "ownership_percent?": "Amount",
    },
    "BusinessUnit": {"code": "Identifier"},
    "LicensedOperator": {"licence_reference": "Identifier"},
    "Licence": {"identifier": "Identifier", "jurisdiction": "Text", "regulator_id?": "@Party"},
    "LegalIdentifier": {"identifier": "Identifier", "scheme": "Identifier"},
    "LicensedServiceArea": {"code": "Identifier", "location_id?": "@Location"},
    "GasDistributionSystem": {"code": "Identifier"},
    "PipelineSegment": {"code": "Identifier", "system_id": "@GasDistributionSystem"},
    "TariffDecision": {"reference": "Identifier", "regulator_id": "@Party"},
    "TariffComponent": {"decision_id": "@TariffDecision", "rate": "Money", "unit": "Unit"},
    "ServiceCompany": {"code": "Identifier"},
    "ConsolidationUnit": {"code": "Identifier"},
    "ConsolidationGroup": {"code": "Identifier"},
    "OperationalNetwork": {"code": "Identifier"},
    "AssetPortfolio": {"code": "Identifier"},
    "DomainPack": {"code": "Identifier", "version": "Identifier"},
    "Ledger": {
        "legal_entity_id": "@LegalEntity",
        "calendar_id": "@FiscalCalendar",
        "chart_id": "@LocalChartOfAccounts",
        "currency_id": "@Currency",
    },
    "AccountingBook": {"ledger_id": "@Ledger", "code": "Identifier"},
    "FiscalCalendar": {"code": "Identifier"},
    "FiscalPeriod": {"calendar_id": "@FiscalCalendar", "starts_on": "Date", "ends_on": "Date"},
    "Currency": {"code": "CurrencyCode"},
    "FXRateSet": {"base_currency_id": "@Currency", "rate_date": "Date"},
    "LocalChartOfAccounts": {"legal_entity_id": "@LegalEntity", "code": "Identifier"},
    "LocalAccount": {"chart_id": "@LocalChartOfAccounts", "account_code": "AccountCode"},
    "GroupAccount": {"account_code": "AccountCode"},
    "DimensionDefinition": {"code": "Identifier"},
    "DimensionMember": {"dimension_id": "@DimensionDefinition", "code": "Identifier"},
    "CompanyDimension": {
        "legal_entity_id": "@LegalEntity", "dimension_id": "@DimensionDefinition",
        "source_record_id": "@SourceRecord", "source_column": "Identifier",
        "source_header": "Text",
    },
    "SourceDimensionAssignment": {
        "observation_id": "@SourceJournalMovement", "company_dimension_id": "@CompanyDimension",
        "member_id": "@DimensionMember", "source_record_id": "@SourceRecord",
    },
    "AccountDimensionRule": {
        "account_id": "@LocalAccount",
        "dimension_id": "@DimensionDefinition",
        "required": "Flag",
    },
    "Party": {"registration_code?": "Identifier"},
    "Customer": {"party_id": "@Party"},
    "Supplier": {"party_id": "@Party"},
    "Counterparty": {"party_id": "@Party"},
    "Product": {"code": "Identifier", "unit?": "Unit"},
    "Contract": {"reference": "Identifier", "party_id?": "@Party"},
    "Facility": {"code": "Identifier", "location_id?": "@Location"},
    "Location": {"code": "Identifier", "latitude?": "Amount", "longitude?": "Amount"},
    "SourceEvidence": {"sha256": "Identifier", "source_system": "Identifier"},
    "SourceRecord": {"evidence_id": "@SourceEvidence", "coordinate": "Identifier"},
    "MappingVersion": {
        "source_schema_id": "@SchemaDefinition",
        "target_schema_id": "@SchemaDefinition",
    },
    "AccountMappingVersion": {
        "local_account_id": "@LocalAccount",
        "group_account_id": "@GroupAccount",
    },
    "JournalEntry": {
        "legal_entity_id": "@LegalEntity",
        "ledger_id": "@Ledger",
        "period_id": "@FiscalPeriod",
        "reference": "Identifier",
    },
    "JournalLine": {
        "journal_id": "@JournalEntry",
        "account_id": "@LocalAccount",
        "amount": "Money",
        "source_record_id": "@SourceRecord",
    },
    "MetricDefinition": {"code": "Identifier", "function_reference": "Identifier"},
    "ReportSnapshot": {
        "legal_entity_id": "@LegalEntity",
        "period_id": "@FiscalPeriod",
        "metric_id": "@MetricDefinition",
    },
    "RegulatoryRule": {
        "act_id": "@RegulatoryAct",
        "legal_entity_id": "@LegalEntity",
        "licence_id": "@Licence",
        "evidence_id": "@SourceEvidence",
        "definition": "OntologyDefinition",
    },
    "RegulatoryAct": {
        "reference": "Identifier",
        "jurisdiction": "Text",
        "evidence_id": "@SourceEvidence",
    },
    "Alias": {"source_system": "Identifier", "external_id": "Identifier", "target_id": "@*"},
    "IdentityResolution": {
        "source_id": "@*",
        "target_id": "@*",
        "active": "Flag",
        "survivorship": "Text",
    },
    "Relationship": {"relation_id": "@LinkType", "source_id": "@*", "target_id": "@*"},
    "SemanticBinding": {
        "source_schema_id": "@SchemaDefinition",
        "source_field": "Identifier",
        "semantic_id": "@SemanticContract",
    },
    "ContextBinding": {
        "legal_entity_id": "@LegalEntity",
        "ledger_id": "@Ledger",
        "period_id": "@FiscalPeriod",
        "currency_id": "@Currency",
        "source_scope_key": "Identifier",
    },
    "SourceAccountingScope": {
        "document_id": "Identifier", "source_record_id": "@SourceRecord",
        "legal_entity_id": "@LegalEntity", "chart_id": "@LocalChartOfAccounts",
        "worksheet": "Text", "source_profile": "Identifier",
        "observed_from": "Date", "observed_through": "Date", "date_basis": "Identifier",
        "coverage_state": "Identifier", "evidence_id": "@SourceEvidence",
    },
    "SourceAccountingBinding": {
        "scope_id": "@SourceAccountingScope", "source_use": "Identifier",
        "ledger_id?": "@Ledger", "book_id?": "@AccountingBook",
        "period_id?": "@FiscalPeriod", "currency_id?": "@Currency",
        "currency_role?": "Identifier", "rationale": "Text",
    },
}

# Spatial fields are optional extensions; accepted versions retain their original schema.
for _kind in (
    "Location",
    "Facility",
    "PipelineSegment",
    "LicensedServiceArea",
    "OperationalNetwork",
    "GasDistributionSystem",
):
    TYPE_FIELDS[_kind].update(
        {
            "geometry?": "SpatialGeometry",
            "legal_entity_id?": "@LegalEntity",
            "spatial_import_id?": "@SpatialImport",
        }
    )
TYPE_FIELDS["SpatialImport"] = {
    "legal_entity_id": "@LegalEntity",
    "document": "GeoJSONDocument",
    "canonical_document_sha256": "Identifier",
}
for _kind in (
    "PipelineJunction",
    "Valve",
    "Regulator",
    "MeteringRegulatingStation",
    "DeliveryPoint",
    "CustomerConnection",
    "GasNetworkZone",
    "PressureZone",
):
    TYPE_FIELDS[_kind] = {
        "code": "Identifier",
        "system_id?": "@GasDistributionSystem",
        "legal_entity_id?": "@LegalEntity",
        "geometry?": "SpatialGeometry",
    }

LINKS: dict[str, tuple[list[str], list[str], str]] = {
    "CONNECTS": (["PipelineSegment"], ["PipelineJunction"], "explicit directed connectivity"),
    "FEEDS": (
        ["DeliveryPoint", "PipelineJunction", "PipelineSegment"],
        ["GasNetworkZone", "PipelineSegment", "PressureZone"],
        "explicit directed feed",
    ),
    "SUPPLIES": (
        ["PressureZone", "GasNetworkZone"],
        ["CustomerConnection", "Facility"],
        "explicit directed supply",
    ),
    "CONTROLS_OR_MEASURES": (
        ["Valve", "Regulator", "MeteringRegulatingStation"],
        ["PipelineSegment", "PressureZone"],
        "control or measurement association",
    ),
    "HAS_BUSINESS_DOMAIN": (["EnterpriseGroup"], ["BusinessDomain"], "domain membership"),
    "HAS_LEGAL_ENTITY": (["EnterpriseGroup"], ["LegalEntity"], "corporate membership"),
    "OPERATED_BY": (
        ["BusinessDomain"],
        ["LegalEntity", "LicensedOperator", "BusinessUnit"],
        "operating responsibility",
    ),
    "OWNS_OR_CONTROLS": (["LegalEntity"], ["SubsidiaryRelationship"], "legal ownership"),
    "HAS_BUSINESS_UNIT": (
        ["LegalEntity"],
        ["BusinessUnit", "ServiceCompany"],
        "operating organization",
    ),
    "PARTICIPATES_IN": (
        ["LegalEntity", "BusinessUnit"],
        ["ConsolidationUnit", "ConsolidationGroup", "BusinessDomain"],
        "membership",
    ),
    "USES_DOMAIN_PACK": (
        ["BusinessDomain", "LegalEntity", "BusinessUnit", "LicensedOperator"],
        ["DomainPack"],
        "industry semantic capability",
    ),
    "HAS_OPERATOR": (["LegalEntity"], ["LicensedOperator"], "operating organization"),
    "HAS_IDENTIFIER": (["LegalEntity"], ["LegalIdentifier"], "governed legal identifier"),
    "HAS_CHART_OF_ACCOUNTS": (["LegalEntity"], ["LocalChartOfAccounts"], "accounting structure"),
    "USES_FUNCTIONAL_CURRENCY": (["LegalEntity", "Ledger"], ["Currency"], "functional currency"),
    "HOLDS_LICENSE": (["LegalEntity", "LicensedOperator"], ["Licence"], "licence authority"),
    "AUTHORIZES": (
        ["Licence"],
        ["LicensedServiceArea", "GasDistributionSystem"],
        "licensed activity",
    ),
    "OPERATES": (
        ["LegalEntity", "LicensedOperator"],
        ["Facility", "OperationalNetwork", "AssetPortfolio"],
        "operating responsibility",
    ),
    "LICENSED_FOR": (
        ["LicensedOperator"],
        ["OperationalNetwork", "Location"],
        "licence responsibility",
    ),
    "HAS_LEDGER": (["LegalEntity"], ["Ledger", "AccountingBook"], "accounting structure"),
    "USES_CALENDAR": (["Ledger"], ["FiscalCalendar"], "accounting structure"),
    "USES_CHART_OF_ACCOUNTS": (["Ledger"], ["LocalChartOfAccounts"], "accounting structure"),
    "USES_CURRENCY_CONTEXT": (["Ledger"], ["Currency", "FXRateSet"], "accounting structure"),
    "ALLOWS_DIMENSION_MODEL": (
        ["LegalEntity", "Ledger"],
        ["DimensionDefinition"],
        "accounting structure",
    ),
    "MAPS_TO": (["LocalAccount"], ["GroupAccount"], "account mapping"),
    "BELONGS_TO": (
        ["JournalEntry", "JournalLine"],
        ["LegalEntity", "Ledger", "FiscalPeriod"],
        "accounting scope",
    ),
    "DERIVED_FROM": (["*"], ["SourceRecord", "SourceEvidence"], "lineage"),
    "GENERATED_FROM": (["ReportSnapshot"], ["*"], "versioned dependency"),
}


def platform_definitions(tenant: UUID) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    for name, kind in SEMANTICS.items():
        definitions.append(
            {
                "object_type": "SemanticContract",
                "identity_key": name,
                "display_name": name,
                "attributes": {"kind": kind, "version": 1},
            }
        )
    for name, specs in TYPE_FIELDS.items():
        specs = dict(specs)
        if name not in ("SourceEvidence", "SourceRecord"):
            specs.setdefault("evidence_id?", "@SourceEvidence")
        fields: dict[str, Any] = {}
        for raw, specification in specs.items():
            field = raw.removesuffix("?")
            target = specification[1:] if specification.startswith("@") else None
            semantic = "CanonicalReference" if target else specification
            fields[field] = {
                "field_id": str(uuid5(CATALOG_NAMESPACE, f"field:{name}:{field}")),
                "semantic_id": str(canonical_id(tenant, "SemanticContract", semantic)),
                "kind": SEMANTICS[semantic],
                "required": not raw.endswith("?"),
                "target_type": target,
                "deprecated": False,
            }
        definitions.append(
            {
                "object_type": "SchemaDefinition",
                "identity_key": name,
                "display_name": name,
                "attributes": {
                    "fields": fields,
                    "additional_fields": False,
                    "compatibility": "BACKWARD",
                    "version": 1,
                },
            }
        )
    for name, (sources, targets, meaning) in LINKS.items():
        definitions.append(
            {
                "object_type": "LinkType",
                "identity_key": name,
                "display_name": name.replace("_", " ").title(),
                "attributes": {"sources": sources, "targets": targets, "meaning": meaning},
            }
        )
    return definitions
