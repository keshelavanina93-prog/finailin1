# Ontology query client

`@g8/ontology-client` executes the existing authenticated ontology APIs. It creates no resources, invokes no business effects and performs no automatic retries.

```ts
const client = createOntologyClient({baseUrl: '/api/ontology', getToken: () => token});
const first = await client.query(query, {signal});
const next = await client.nextPage(first, {signal});
```

`runSavedSet(exactPin, options)` and `runGroup(exactPin, options)` require resource and version IDs. Options accept offset, limit, valid_at, known_at and signal. `page(previousResult, offset, options)` posts the previous response's exact query; `nextPage` returns null without a request at the end. Pages preserve definition references, temporal precision and semantic bindings. A changed population or incompatible response is an error, not an inferred empty result.

Generated server JSON schemas validate requests and responses without coercion or default insertion. Canonical attributes remain untouched. Additional checks bind definitions, interface implementations, type-group schemas, compatibility evidence and pagination to the captured request. This validates transport contracts; it does not independently attest server execution or grant current resource authority.

Membership predicates use `{field: 'source_column', operator: 'in', value: ['Y', 'AA']}` or `not_in`. Values must be distinct, non-null scalars of the same kind; root and traversal predicates share a total limit of 100 membership values. The server validates every value against the canonical field definition. Both operators exclude missing and null properties. Equality uses exact stored values, so text whitespace and decimal string representations remain significant. The client freezes the complete list before authentication and retains it through saved-set paging.

Root queries and relationship steps also accept `filter_expression: {op: 'any', conditions: [{field: 'debit_account_id', value: accountA}, {field: 'credit_account_id', value: accountB}]}`. Use `all` for conjunction; groups can nest up to three levels and contain two to twenty children. Legacy `filters` are combined with the expression using AND. All root and reached-object leaves share the existing twenty-predicate and hundred-membership-value limits. Each branch is schema-checked even when another branch could match. Global counts and pagination apply to the resulting canonical set, so an object matching two branches appears once. Exact expressions survive saved-set replay and paging; these selections do not assign accounting meaning or financial authority.

`OntologyClientError.status` preserves HTTP refusal status; zero denotes transport failure and 502 an invalid successful response. `detail` is bounded server detail or a safe generic message. AbortSignal cancellation propagates as cancellation. Authentication is requested afresh for each HTTP call; the client stores no token or persistent cache.
