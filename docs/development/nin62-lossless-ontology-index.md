# Lossless disposable ontology index

Oxigraph Store 0.5.11 normalizes some RDF literal datatypes and lexical forms. The
original PROV-O artifact demonstrated the defect: one `owl:maxCardinality` object
changed from `"0"^^xsd:nonNegativeInteger` to `"0"^^xsd:integer`. The previous reader
correctly refused the changed dataset hash, but could not inspect this valid source.

The derived store now uses `canonical-nquad-envelope/1`. Each canonical source quad
is an opaque `xsd:string` containing exactly its canonical N-Quads line. Its outer
subject and graph retain their original RDF nodes; a fixed private predicate marks
the envelope. These are disposable storage records, never new ontology assertions
or canonical business identities.

Every read verifies the fixed predicate, plain string datatype, absence of language
or direction, exactly one canonical quad, and matching outer subject and graph.
Decoded UTF-8 bytes and envelope count are bounded before dataset assembly. The
reconstructed dataset must match the caller's exact retained SHA256 before any
subject results are returned. Neither rewritten manifest fields nor an additional
cache digest can authorize different RDF content.

The private cache key and pointer include the encoding version. Existing raw-RDF
caches return `INDEX_MISSING` under the new key and can be rebuilt from the retained
dataset. Old generations are left intact for concurrent readers and remain subject
to the existing global storage budget. Public response shapes and canonical release
identities do not change.

No resource cap changed: 512 MiB memory, 8 CPU seconds, 10 seconds wall time,
128 descriptors, two concurrent local workers, and the existing disk/result/data
budgets remain enforced. The existing early Linux production probe invokes the new
build/read path automatically; actual Linux execution remains a CI integration gate.

## Focused evidence

- Existing index suite: 27 passed, including cross-scope isolation, physical cache
  tampering, replay, process concurrency, timeout and descriptor caps.
- New lossless suite: 15 passed, including shared blank nodes across envelopes,
  multiple named graphs, language-tagged Unicode, integer subtype and numeric/date
  lexical preservation, malformed/duplicate/noncanonical envelopes, forged metadata,
  decoded-byte budget, old-cache rebuild, and the unchanged public PROV file.
- Ruff and Windows/Linux mypy passed. No full API suite was run for this change.
- The already approved native PROV release was rebuilt and inspected through the
  authorized service after its publisher withdrawal, using explicit historical
  inspection. It retained all 1,146 quads and exact dataset SHA256
  `0a4814bb0648e8ee3465db44d1818723336c721bc51c04439ca201815a82499e`.
  Evidence is `.finai/artifacts/nin62-prov-lossless-index.json`; current publisher use
  remains refused. This proves bounded exact retained inspection, not standards
  conformance, inference, scale acceptance or business authority.
