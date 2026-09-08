# Exact retained foreign vocabulary assertions

The offline importer previously rejected every named subject outside a module's owned
namespaces (apart from its artifact descriptor). Real publisher files can annotate or
declare foreign vocabulary terms. Retaining those exact assertions does not establish
ownership of those terms.

`ModuleInput.foreign_assertions` is optional and omitted from every serialized model
when absent. A nonempty declaration contains exact `subject_iri`, `predicate_iri`,
`object_ntriples`, `classification`, and a substantive review `reason`. Its existing
approved publisher pin and retained document hash bind who asserted the statement and
the exact source bytes. The existing independent release review and replay cover the
exceptions; publisher namespaces are never widened.

The first policy permits only:

- `rdfs:label`, `rdfs:comment`, `rdfs:isDefinedBy`, `rdfs:seeAlso`, and `owl:versionInfo`
  with an exact IRI or literal object, classified `FOREIGN_ANNOTATION`.
- `rdf:type` declarations whose exact object is `owl:Class`, `rdfs:Class`,
  `rdf:Property`, `owl:AnnotationProperty`, `owl:ObjectProperty`,
  `owl:DatatypeProperty`, or `owl:Ontology`, classified
  `FOREIGN_VOCABULARY_DECLARATION`.

Objects must use the parser's exact N-Triples term spelling. Blank-node and RDF-star
objects, additional injected triples, equivalence, imports, subclass/subproperty,
domain/range, rules, and executable declarations are not exceptions. Unknown foreign
triples still refuse. Duplicate, unused, owned-subject, and artifact-descriptor
exceptions refuse. Limits are 128 declarations per artifact, 512 per closure, and
1 MiB total declaration text, inside the existing capped offline process.

The original retained bytes and every RDF triple are preserved. RDFC-1.0 still runs
over the original graph, with separate document blank-node scopes. Exception
classification and rationale appear only in the import report and reviewed metadata;
they are not injected into RDF. The report records artifact graph, original byte hash,
actual consumed declarations, and explicit false ownership/equivalence authority.

There is no new canonical term resource or alignment. Term inspection remains an
exact-release, scope-checked assertion projection with named graph provenance. A
foreign assertion in one publisher's graph can coexist with the vocabulary owner's
own graph. `rdf:type` and `rdfs:isDefinedBy` never grant namespace ownership.

## Compatibility and acceptance

No historical resource rewrite or database migration is required. Absent fields stay
absent in old module/request JSON. `RdfArtifactResult` is unchanged. The worker emits
new policy/count/report fields only for imports using exceptions. The pre-extension
worker response golden SHA256
`740103a8ed9e6bc4bab367fce49af66213cf678d81f2153db555204a7ba12e67`
remains identical. The SDK accepts the new optional declaration while refusing
ownership expansion and unsupported declarations.

Local offline acceptance uses the unchanged public PROV-O 2013-04-30 bytes, SHA256
`3d03c8e15753178541fb8cd59fbefecaf1861f9c37ef75190c6e938b85fb0c3d`,
with artifact graph `http://www.w3.org/ns/prov-o#` and the sole owned namespace
`http://www.w3.org/ns/prov#`. Eleven exact exceptions cover six foreign subjects.
All 1,146 original triples survive; canonical bytes equal an independently parsed
RDFC-1.0 dataset. The same source still refuses without exceptions.

Supply that already-retained public file through `G8_PROV_ARTIFACT_PATH` to run the
authentic-file check. Tests never download source files, and explicitly skip that
one check when the artifact is not supplied. Synthetic correctness/refusal and
historical serialization checks remain portable. FIBO compatibility has not been
established by this PROV acceptance check.

## Disposable native publication proof

`test_rdf_foreign_assertions_native.py` passed locally in 14.37 seconds using
PostgreSQL 55441 (physical data directory verified as
`D:/FinAI/g8-ci-repair/.finai/data/postgres-ci`) and private MinIO 9064. Synthetic
maker and independent checker approved the publisher and exact release through
ordinary canonical resource proposals. Self-review refused. The pre-extension
importer separately published a no-exception release; the new importer replayed its
same release, dataset and report references without creating resource versions.

PROV canonical dataset SHA256 is
`0a4814bb0648e8ee3465db44d1818723336c721bc51c04439ca201815a82499e`
(195,930 bytes, 1,146 quads). Approved release resource
`78bb7a36-0476-5846-b74a-2522b2928772`, version
`9472e623-8631-5683-90ed-048397c3b388`, retains the 11 declarations and unchanged
owned namespace. Publisher withdrawal then refused current metadata access and
import replay with HTTP-equivalent 409; exact historical inspection remained
available. Scope, exact publisher/release pins and retained document hashes are in
`.finai/artifacts/nin62-prov-native.json`. This is public artifact retention with
synthetic governance actors, not standards conformance or business authorization.

This opt-in proof requires `G8_FOREIGN_ASSERTIONS_NATIVE=1`, an explicitly configured
synthetic `G8_FOREIGN_ASSERTIONS_ENTITY`, `G8_PROV_ARTIFACT_PATH`,
`G8_PRE_EXTENSION_SRC`, and a D-only `G8_FOREIGN_ASSERTIONS_EVIDENCE` output. Reuse the
same synthetic entity for these fixed public bytes: the existing canonical
SourceEvidence identity is tenant plus content hash, and the authority guard
correctly refuses reuse that would discard another entity's access boundary.

### Separate index blocker discovered

The current Oxigraph index build succeeds, but its exact read correctly refuses
`INDEX_CORRUPT` for this source. Oxigraph Store changes one original quad's object:
`"0"^^xsd:nonNegativeInteger` becomes `"0"^^xsd:integer` on
`_:c14n18 owl:maxCardinality` in the PROV graph. Store serialization has SHA256
`a4caeca67d9be3e9f5bab46fbcd4d2c4a5f908647153c9341220d8849cd82ec1`,
which differs from the retained canonical dataset. RDFC recanonicalization cannot
restore an altered datatype. No hash guard was weakened and no index production
code was changed in this patch. Exact retained publication/replay is proven;
successful PROV index inspection was blocked pending a lossless projection fix.
The companion [lossless index change](nin62-lossless-ontology-index.md) now records
the bounded fix and successful exact historical native inspection separately.
