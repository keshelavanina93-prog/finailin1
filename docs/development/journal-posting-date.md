# Explicit journal posting dates

Journal publication now requires an explicit `posting_date` in strict YYYY-MM-DD format. The date must be a real calendar date inside the inclusive bounds of the fiscal period resolved from the journal's reviewed source accounting binding. Journal lines validate the date of their resolved parent journal too; adding lines to a historical journal without a posting date does not bypass the requirement.

The publication validator uses the shared resource resolver with an `ACCOUNTING_POSTING_PERIOD` dependency. Proposal evaluation and promotion therefore consume the exact period version through existing canonical dependency and authority checks. There is no new finance-local calendar, identity namespace or publication mechanism.

The canonical JournalEntry schema adds an optional Date field so older retained journal versions remain readable. New publication is stricter than historical deserialization. The ontology installer adds only missing journal fields through normal independent review and preserves existing schema fields and prior versions. No historical posting dates are filled from record effective time, source filenames or authorization scope.

Journal proposal review displays the supplied accounting date separately from record effective times and says when it is absent. This is a prerequisite for accounting publication, not proof of authentic journal posting: source-row date correspondence, accepted source interpretation, balanced complete journal bundles, mapping policy and other accounting rules remain separate checks. The change does not implement close/reopen or authorize financial effects.

Focused validator checks cover missing/invalid dates, inclusive period boundaries, leap-day validity, the journal and line-parent paths, and revalidation against changed period bounds. The live registry upgrade publishes one additive JournalEntry schema through proposal `0f719315-3b0f-46d8-b863-9e058a69b51d`. The previous schema remains retained. NIN-17 and production accounting acceptance remain open.
