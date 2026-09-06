# Retained licence issuance and company identity

The Data workspace now reads original Matsne gas-distribution issuance tables,
shows the original cells, and submits a reviewed source-to-company binding.
The accepted ontology resources are `SourceLicenceNotice`, `Licence`, and
`LicenceNoticeBinding`, linked through the retained document, `SourceEvidence`
and `SourceRecord`. Generic ontology review pins their exact dependencies and
revalidates the retained notice before acceptance.

Company registration must match. Where an existing accounting company lacks a
registration field, its accepted `CorporateDisclosureBinding` provides the
registration identity and is itself pinned as a dependency. This keeps SGG and
Sakorggazi separate and reuses their accounting identities.

An issuance notice establishes historical issuance only. Publication does not
create `HOLDS_LICENSE`, an operating territory, tariff, or effective obligation.
`valid_from` records resource availability, while the original issuance date
remains a separate source field. Current legal status is explicitly unknown;
renewal, repeal, transfer and reauthorization evidence still require delivery.
The parser rejects unsupported tables and notices containing other event fields.

## Local authentic publication, 2026-09-06

| Company | Original notice | Issued | Accepted proposal |
| --- | --- | --- | --- |
| Sakorggazi, 208147637 | [Matsne 2184003, licence 125](https://matsne.gov.ge/ka/document/view/2184003) | 2013-12-18 | `5e09f593-1eb9-4915-a687-b79474f11e3e` |
| SOCAR Georgia Gas, 202403121 | [Matsne 2575115, licence 127](https://matsne.gov.ge/ka/document/view/2575115) | 2014-10-31 | `e68d5727-049e-4139-8d72-1a6cdf5bbdd6` |

Original SHA-256 values:

- 2184003: `c0b92b6fd01774a3da905f6a4ad0c793f33cea04d9dcd2c3361cec7b2ed7b406`
- 2575115: `6aff40fe642c1ae7319268eff410ecc30fa32c0272a45b756ae4da8d5a292e6f`

Both proposals were created through the authenticated rebuilt browser UI.
Acceptance used the separately configured reviewer identity through the API;
the browser then reopened each source and confirmed its published binding.
This demonstrates local application publication, not an external legal opinion
or independent human legal review. Evidence metadata lives in
`.finai/artifacts/licence-publication.json`.

Production web compilation and TypeScript passed. Focused lint and two identity /
applicability guard tests passed. NIN-40 remains open: current licence chains,
service areas, affected calculations/reports, monitoring and future activation
are not established by this delivery.
