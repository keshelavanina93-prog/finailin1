# Retained FIBO candidate boundaries

The exact official FIBO 2026Q2 production Turtle archive was retained from `https://spec.edmcouncil.org/fibo/ontology/master/2026Q2/prod.ttl.zip`: 1,451,853 bytes, SHA-256 `7a4ccebc9ff5c1e202bf1ae44928d9149a5f6f8ff1289dde42edff13e601f579`, retrieved at `2026-09-08T02:01:00.545349Z`. It was inspected without extracting an unbounded archive or fetching imports during G8 execution.

FIBO's original Commons import IRIs are unversioned. They do not establish which Commons release the publisher intended. Exact dated official Commons 1.3 artifacts were retained as an explicit preparation candidate; this choice is not an approved G8 profile or a claim of FIBO publisher intent.

The complete Relations candidate closure contains 19 modules (2 FIBO, 17 Commons), 305,052 input bytes, 3,544 quads, 214 blank nodes, 175,365 literal bytes and depth 9. There are no missing imports or cycles. The current 16-module limit refuses this candidate; limits were not increased to accommodate it. Canonicalization execution was not claimed after that refusal.

Using only the already retained bytes, the smaller metadata-only AnnotationVocabulary candidate has a complete six-module closure: FIBO AnnotationVocabulary and Commons AnnotationVocabulary, Classifiers, Collections, Designators and TextDatatype. It contains 65,490 input bytes, 610 quads, 11 blank nodes, 42,379 literal bytes and depth 4. These measured numerical limits fit. This does not establish business semantics or engine acceptance.

The original metadata candidate contains 128 assertions about foreign named subjects. The optional exact annotation/declaration policy permits 64 and refuses 64. Refused content includes 13 `rdfs:subPropertyOf` hierarchy assertions, SKOS and Commons annotation predicates, an `rdfs:Datatype` declaration and source literals. None were deleted, relabeled as owned vocabulary, or silently admitted. Equivalence was not found on foreign subjects in this candidate.

Preparation manifests are retained beneath `D:\FinAI\g8-ontology-import\.finai\external-profile-preparation\fibo-2026Q2\commons-1.3-relations-candidate`: `candidate-manifest.json`, `annotation-metadata-candidate.json` and `foreign-assertion-policy-inspection.json`. They record exact source hashes, URLs, version IRIs, retrieval instants, licenses, closure edges and every refused assertion. The Relations manifest remains SHA-256 `4d4e4e454393b95353e0510d43274b694d2c2794384d93efd5bea34888e4243e`.

FIBO import/profile acceptance remains open. Any later expansion requires an explicit reviewed dependency choice and a separately defined policy for retained foreign relationships; the existing narrow exception contract does not authorize that expansion. There were no G8 source registrations, release/profile proposals, company facts, alignments or accounting effects from this preparation.
