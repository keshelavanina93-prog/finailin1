# Query-time canonical property filters

NIN-26 direct object queries and saved Object Set definitions now share canonical property
validation. Unknown fields, incorrect scalar kinds, malformed references/dates, non-finite
decimals and null filters for required fields produce explicit 422 errors. Valid queries with
no matches remain successful empty sets. These rules reuse canonical resource scalar validation;
there is no module-specific property type system.

For direct execution, schema selection, object versions, counts and traversal share one SQL
snapshot. Schema selection honors the query's effective time and knowledge time, and selects
the latest applicable version before rejecting withdrawn definitions. A future-effective schema
does not hide the earlier currently effective schema. Filtered results expose exact
`filter_schema_versions` for explanation and retained derived-query evidence. Unfiltered queries
do not pay for this additional schema lookup. This change does not alter material authority or
grant financial certification.

The replacement G8 ontology workbench displays query-time schema references, retains explicit
API errors instead of showing misleading empty results, and offers scalar filter inputs only.
Date controls supply canonical dates; timestamp input indicates the timezone requirement.

Focused native PostgreSQL verification covers unknown/mistyped filters, saved-definition
refusal, exact schema version references, historical knowledge boundaries and future-effective
schema evolution. Existing object-set pagination/traversal and definition-history checks pass.
Scalar cases cover boolean/integer distinction, UUID/date/time/decimal validation and required
null refusal. Synthetic schema fixtures establish local contracts, not authentic source or
complete product acceptance.
