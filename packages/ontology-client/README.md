# Ontology query client

`@g8/ontology-client` executes the existing authenticated ontology APIs. It creates no resources, invokes no business effects and performs no automatic retries.

```ts
const client = createOntologyClient({baseUrl: '/api/ontology', getToken: () => token});
const first = await client.query(query, {signal});
const next = await client.nextPage(first, {signal});
```

`runSavedSet(exactPin, options)` and `runGroup(exactPin, options)` require resource and version IDs. Options accept offset, limit, valid_at, known_at and signal. `page(previousResult, offset, options)` posts the previous response's exact query; `nextPage` returns null without a request at the end. Pages preserve definition references, temporal precision and semantic bindings. A changed population or incompatible response is an error, not an inferred empty result.

Generated server JSON schemas validate requests and responses without coercion or default insertion. Canonical attributes remain untouched. Additional checks bind definitions, interface implementations, type-group schemas, compatibility evidence and pagination to the captured request. This validates transport contracts; it does not independently attest server execution or grant current resource authority.

`OntologyClientError.status` preserves HTTP refusal status; zero denotes transport failure and 502 an invalid successful response. `detail` is bounded server detail or a safe generic message. AbortSignal cancellation propagates as cancellation. Authentication is requested afresh for each HTTP call; the client stores no token or persistent cache.
