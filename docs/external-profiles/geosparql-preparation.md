# Prepare the retained GeoSPARQL vocabulary

`scripts/prepare-geosparql-profile.py` prepares OGC vocabulary meaning through the existing publisher, release and ontology profile proposal contracts. Each proposal requires an independent reviewer in the shared review workflow. The script has no review command and never approves resources, starts services, retrieves remote URLs or creates company facts.

The committed [manifest](geosparql-1.1-vocabulary.json) selects exactly two original public files from official repository commit `ac303373bd0cf149d31f110cf8c1ed281ff66c60`: `geo.ttl` and `sf_geometries.ttl`. SHA-256, byte length, pinned original URL, publisher and license declarations, and upstream version markers are verified before every stage. Original bytes and upstream metadata, including spelling, remain unchanged. Additional files in the supplied directory are not selected. A `geo-validator.ttl` file does not become a constraint profile through this procedure. Receipt `manifest_sha256` uses sorted-key compact UTF-8 JSON so checkout line endings do not change the manifest identity.

The standard reference is GeoSPARQL **1.1**. Both selected files declare **1.1.1 metadata updates** in `owl:versionInfo`; the original GeoSPARQL `owl:versionIRI` remains `http://www.opengis.net/ont/geosparql#1.1`, while Simple Features declares `http://www.opengis.net/ont/sf/1.1.1`. This distinction is intentional. The original declared license URI is `http://purl.org/NET/rdflicense/:APACHE2.0`; preparation verifies that declaration, rather than determining additional licensing rights or silently replacing it.

The resulting development profile contains these two named vocabulary graphs with exact approved release pins. It enables reviewed external meaning only. It does **not** establish spatial function execution, geometry correctness, inference, SHACL validation, GeoSPARQL standard conformance, business fact authority or release acceptance.

## Local inputs and review checkpoints

Use the existing local API environment and the intended maker's `G8_ONTOLOGY_TOKEN`. The tool accepts only loopback HTTP `/v1/ontology` endpoints, disables redirects and environment proxies, and keeps Windows inputs/outputs on D:. Never substitute the independent reviewer's token to bypass a pending review. A preview requires neither credentials nor a running API.

The supplied artifact directory must contain both original files and `retrieval-manifest.json`. The latter is a JSON list with exactly one record per selected file (unselected records are allowed). Each selected record needs `file`, `requested_url`, `retrieved_url`, `sha256`, `byte_length`, aware `retrieved_at` and substantive `retrieval_time_basis`. URLs, hashes and lengths must match the committed manifest. Retrieval times describe retrieval evidence, not the upstream issued date or the date of preparing a proposal. They remain operator-supplied provenance; the script does not independently attest when the retrieval occurred.

Examples below assume `$python`, `$artifacts`, `$receipts` and `$api` point to the existing D: interpreter, retained artifact directory, existing D: output directory, and local `/v1/ontology/` API. Every output path must be new; existing receipts are preserved. Tokens are read from the environment and never written into receipts.

1. Verify original files and preview the publisher declaration:

   ```powershell
   & $python scripts/prepare-geosparql-profile.py verify --artifact-dir $artifacts
   & $python scripts/prepare-geosparql-profile.py publisher --artifact-dir $artifacts
   ```

2. Prepare the publisher proposal, then use the existing G8 proposal review workflow with an independent authorized reviewer:

   ```powershell
   & $python scripts/prepare-geosparql-profile.py publisher --artifact-dir $artifacts --base-url $api --apply --output "$receipts\publisher-proposal.json"
   ```

   After approval, save the actual approved publisher's exact `resource_id`, `version_id` and `content_hash` into `source-pin.json`. A pending proposal ID is not a version pin. The script verifies the pinned source definition against this manifest before release preparation; the canonical service enforces current-effective and lifecycle authority. A future editing head does not replace a currently effective reviewed pin.

3. Retain original files without interpreting or approving them:

   ```powershell
   & $python scripts/prepare-geosparql-profile.py retain --artifact-dir $artifacts --base-url $api --apply --output "$receipts\retained.json"
   ```

   Retention verifies returned hashes/lengths and records source-document references plus retrieval evidence. The two document writes are independently durable. If a later write fails, earlier retained bytes remain uninterpreted; retry is safe under the existing document retention contract. No release is published by retention.

4. Prepare the release after publisher review. Supply both actual retrieval times explicitly; their instants must match `retrieval-manifest.json` and the retention receipt:

   ```powershell
   & $python scripts/prepare-geosparql-profile.py release --artifact-dir $artifacts --source-pin "$receipts\source-pin.json" --retained "$receipts\retained.json" --retrieved-at "geo.ttl=$geoRetrievalTime" --retrieved-at "sf_geometries.ttl=$sfRetrievalTime"
   & $python scripts/prepare-geosparql-profile.py release --artifact-dir $artifacts --source-pin "$receipts\source-pin.json" --retained "$receipts\retained.json" --retrieved-at "geo.ttl=$geoRetrievalTime" --retrieved-at "sf_geometries.ttl=$sfRetrievalTime" --base-url $api --apply --output "$receipts\release-proposal.json"
   ```

   The normal bounded, offline RDF engine parses both original documents into artifact-named graphs and retains its dataset/report. Engine refusal is a retained refusal, not a vocabulary release. Successful preparation returns `REVIEW_REQUIRED`; the script preserves the runtime's actual status. An independent reviewer must approve before a release pin can be used. Replaying the same approved import uses the same canonical release; changed content cannot silently overwrite it.

5. Save the actual approved release pin in `release-pin.json`, then prepare the vocabulary profile:

   ```powershell
   & $python scripts/prepare-geosparql-profile.py profile --artifact-dir $artifacts --release-pin "$receipts\release-pin.json"
   & $python scripts/prepare-geosparql-profile.py profile --artifact-dir $artifacts --release-pin "$receipts\release-pin.json" --base-url $api --apply --output "$receipts\profile-proposal.json"
   ```

   The script inspects that exact currently authorized release and verifies both graph identities, original hashes/lengths, publisher pins, licenses, namespaces, source URLs and retrieval times before proposing the profile. The canonical service rechecks current authority at publication. Independently review this third proposal in G8. Profiles use the existing immutable content-addressed resource identity; revisions require a new identity and review, rather than mutable profile overwrite.

An HTTP failure produces a status-only diagnostic without returning credentials or other scope metadata. Inspect existing local proposal/history tools for authorized details. A lost response does not imply a failed write; inspect before retrying publisher preparation to avoid duplicate pending proposals. Shared `SourceEvidence` identity remains tenant-plus-content-hash with its immutable access boundary: a second company in the same tenant may prepare an import but encounter a non-disclosing conflict at approval. This procedure does not create a new private evidence identity or implement cross-company sharing.

## Focused verification

`scripts/tests/test_prepare_geosparql_profile.py` checks preview behavior, provenance tampering, exact reviewed-version selection and retrieval receipt binding. Its optional native journey uses the original retained public files, actual API routes, PostgreSQL, object storage and the bounded RDF engine. It bootstraps platform definitions only in a fresh synthetic tenant and requires the exact disposable CI database path; its three independent synthetic reviews do not authorize adoption in a real company.

Native execution requires explicit `G8_BINDING_DB_TEST=1`, `G8_NATIVE_STORAGE_TEST=1` and `G8_GEOSPARQL_ARTIFACT_DIR` pointing to the retained D: directory. An optional new D: `G8_GEOSPARQL_CAPTURE_PATH` records proof references without credentials. This test uses an in-process API client and does not launch a listener. Run this file alone with `--no-cov` and a D: temporary directory; the master operator owns the integrated coverage gate.
