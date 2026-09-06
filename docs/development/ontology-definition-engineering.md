# Ontology definition engineering

NIN-6 continuation: Object Sets now exposes engineering controls for new and revised Object Sets, interfaces, implementations, type groups, derived properties, bindings, fact contracts and reconciliations. Existing definitions load their published attributes, immutable business identity and expected version. The editor exposes the server's typed structure contracts and submits through the existing canonical proposal/review authority.

`POST /v1/ontology/model/definitions/preview` prepares the same mutation as publication and executes the same canonical validator under the registry transaction lock. It returns advisory validation and downstream dependency impact without retaining a proposal or publishing a resource. Restricted downstream impact follows the existing proposal redaction boundary. Submission and review still perform their own current-state checks; preview is not approval.

`GET /v1/ontology/model/definitions/contracts` supplies definition models from the server. Regulatory rules remain on their source-evidence-specific path and cannot be authored through the generic definition writer.

Local browser evidence: edited the real original-account-label definition, rejected an undeclared source field in preview, validated the correct definition, and proposed a clearer display name. Separate review published proposal `f3098d82-4aef-460e-bc8c-cabab98af758`. Reusing the original expected version then returned 409. The earlier retained derived calculation continued to resolve its original definition version. Evidence is retained in `.finai/artifacts/definition-engineering-browser.json`.

The production frontend build, focused lint and existing derived/action regression checks passed. This is a structured JSON authoring interface backed by canonical validation, not a complete visual ontology IDE. Generated SDKs, richer authoring, shared general Function execution, general workflows and regulatory calculations remain open; NIN-6 is not complete.
