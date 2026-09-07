import assert from 'node:assert/strict';
import test from 'node:test';
import {createOntologyClient, OntologyClientError} from '../dist/index.js';

const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const time = '2026-09-07T08:00:00.123456Z';
const reference = {resource_id: id(10), version_id: id(11)};
const sha = 'a'.repeat(64);
const object = n => ({resource_id: id(n), version_id: id(n + 100), object_type: 'LegalEntity',
  identity_key: `source:${n}`, display_name: 'Retained original', access_entity: 'test',
  schema_version_id: id(500), attributes: {unrecognized_future_property: {source: ['unchanged', n]}},
  content_hash: sha, valid_from: time, valid_to: null, system_from: time,
  authority_state: 'APPROVED', evidence_class: 'SOURCE_BOUND', proposal_id: id(600)});
const query = (overrides = {}) => ({object_type: 'LegalEntity', resource_ids: null, search: '',
  filters: [], traversal: [], offset: 0, limit: 1, valid_at: time, known_at: time, ...overrides});
const result = (q = query(), total = 2) => ({contract: 'ontology-object-set/1', query: q, total,
  counts_by_type: total ? {LegalEntity: total} : {},
  objects: q.offset < total ? [object(q.offset + 1)] : [],
  next_offset: q.offset + q.limit < total ? q.offset + q.limit : null, filter_schema_versions: []});
const json = value => new Response(JSON.stringify(value), {headers: {'content-type': 'application/json'}});
function client(respond, getToken = () => 'token') {
  const calls = [];
  return {calls, sdk: createOntologyClient({baseUrl: '/api/ontology', getToken,
    fetch: async (url, init) => {calls.push({url, init}); return respond(url, init);}})};
}
const rejects = (fn, status = 502) => assert.rejects(fn, error => error instanceof OntologyClientError && error.status === status);

test('query authenticates each call, preserves attributes, defaults omission, and freezes paging', async () => {
  let auth = 0;
  const {sdk, calls} = client((url, init) => json(result(JSON.parse(init.body))), () => `token-${++auth}`);
  const first = await sdk.query(query());
  assert.deepEqual(first.objects[0].attributes, object(1).attributes);
  const second = await sdk.nextPage(first);
  assert.equal(second.query.offset, 1);
  assert.equal(second.query.known_at, time);
  assert.equal(await sdk.nextPage(second), null);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].init.headers.Authorization, 'Bearer token-2');
  assert.equal(calls[0].init.redirect, 'error');
  assert.equal(calls[0].init.cache, 'no-store');
  assert.deepEqual(JSON.parse(calls[1].init.body), {...first.query, offset: 1});
  assert.equal(first.query.offset, 0);
});

test('exact saved definition GET becomes frozen POST paging with definition metadata retained', async () => {
  const {sdk, calls} = client((url, init) => json(init.method === 'GET'
    ? {...result(), definition_id: reference.resource_id, definition_version_id: reference.version_id}
    : result(JSON.parse(init.body))));
  const first = await sdk.runSavedSet(reference, {limit: 1, valid_at: time, known_at: time});
  assert.ok(calls[0].url.includes(`/model/sets/${reference.resource_id}/objects?version=${reference.version_id}`));
  const next = await sdk.page(first, 1);
  assert.equal(calls[1].init.method, 'POST');
  assert.equal(next.definition_id, reference.resource_id);
  assert.equal(next.definition_version_id, reference.version_id);
  await rejects(() => sdk.runSavedSet({...reference, version_id: id(900)}, {limit: 1}));
});

test('timestamp equivalence preserves microseconds and refuses fractional changes', async () => {
  const equivalent = '2026-09-07T12:00:00.123456+04:00';
  const {sdk} = client(() => json(result(query({valid_at: equivalent, known_at: equivalent}))));
  await sdk.query(query());
  const changed = client(() => json(result(query({known_at: '2026-09-07T08:00:00.123457Z'}))));
  await rejects(() => changed.sdk.query(query()));
});

test('changed filters, source scope, traversal, and missing times are refused', async () => {
  for (const update of [{resource_ids: [id(7)]}, {filters: [{field: 'code', value: 'new'}]},
    {traversal: [{kind: 'reference', name: 'company_id', direction: 'outgoing'}]},
    {known_at: undefined}]) {
    const {sdk} = client(() => json(result(query(update))));
    await rejects(() => sdk.query(query()));
  }
});

test('malformed successful JSON, non-JSON, invalid counts and duplicate pages fail closed', async () => {
  const malformed = [null, {}, {...result(), total: '2'}, {...result(), next_offset: 0},
    {...result(), counts_by_type: {LegalEntity: 9}}, {...result(), objects: []},
    {...result(query({limit: 2})), objects: [object(1), object(1)], next_offset: null}];
  for (const payload of malformed) {
    await rejects(() => client(() => json(payload)).sdk.query(query()));
  }
  await rejects(() => client(() => new Response('<html>unexpected</html>')).sdk.query(query()));
});

test('401/409 preserve HTTP status and detail, never echo arbitrary response bodies or retry', async () => {
  for (const status of [401, 409]) {
    const {sdk, calls} = client(() => new Response(JSON.stringify({detail: 'Exact version unavailable'}), {status}));
    await assert.rejects(() => sdk.query(query()), error => error.status === status && error.detail === 'Exact version unavailable');
    assert.equal(calls.length, 1);
  }
  const {sdk} = client(() => new Response('private raw unexpected response', {status: 500}));
  await assert.rejects(() => sdk.query(query()), error => error.status === 500 && !error.message.includes('private'));
});

test('abort signal reaches transport and cancellation never triggers a retry', async () => {
  const controller = new AbortController();
  let calls = 0;
  const sdk = createOntologyClient({baseUrl: '/api/ontology', getToken: () => 'token',
    fetch: async (url, init) => {calls++; assert.equal(init.signal, controller.signal);
      controller.abort(); throw new Error('network raw');}});
  await assert.rejects(() => sdk.query(query(), {signal: controller.signal}), {name: 'AbortError'});
  assert.equal(calls, 1);
  await assert.rejects(() => sdk.query(query(), {signal: controller.signal}), {name: 'AbortError'});
  assert.equal(calls, 1);
});

test('input mutation during token retrieval cannot change the captured request', async () => {
  const input = query();
  const {sdk, calls} = client((url, init) => json(result(JSON.parse(init.body))), async () => {
    input.filters.push({field: 'code', value: 'changed'}); return 'token';
  });
  await sdk.query(input);
  assert.deepEqual(JSON.parse(calls[0].init.body).filters, []);
});

function grouped() {
  const q = query({object_type: 'ObjectTypeGroup', type_group: reference});
  return {...result(q, 1), type_group_bindings: {group: {...reference, content_hash: sha}, fields: {},
    schemas: [{object_type: 'LegalEntity', schema: {resource_id: id(501), version_id: id(500), content_hash: sha}}]},
    type_group_values: [{object_id: id(1), object_version_id: id(101), schema_version_id: id(500), status: 'AVAILABLE'}]};
}
test('group exact pins and per-object compatibility cannot be substituted', async () => {
  const value = grouped();
  await client(() => json(value)).sdk.query(value.query);
  for (const mutate of [r => {r.type_group_bindings.group.version_id = id(66);},
    r => {r.type_group_values[0].object_version_id = id(66);},
    r => {r.type_group_values[0].status = 'SCHEMA_CHANGED';},
    r => {r.type_group_values = [];}, r => {r.type_group_bindings.schemas = [null];}]) {
    const altered = structuredClone(value); mutate(altered);
    await rejects(() => client(() => json(altered)).sdk.query(value.query));
  }
});

test('runGroup requires exact definition and executable root to agree', async () => {
  const value = {...grouped(), definition_id: reference.resource_id, definition_version_id: reference.version_id};
  await client(() => json(value)).sdk.runGroup(reference, {limit: 1});
  value.definition_version_id = id(99);
  await rejects(() => client(() => json(value)).sdk.runGroup(reference, {limit: 1}));
});

test('interface implementation substitution and missing projection are refused', async () => {
  const impl = {resource_id: id(20), version_id: id(21)};
  const q = query({object_type: 'ObjectInterface', interface: {...reference, implementations: [impl]}});
  const value = {...result(q, 1), interface_bindings: {interface: {...reference, content_hash: sha}, fields: {},
    implementations: [{implementation: {...impl, content_hash: sha}, object_type: 'LegalEntity', fields: {},
      schema: {resource_id: id(501), version_id: id(500), content_hash: sha}}]},
    interface_values: [{object_id: id(1), object_version_id: id(101), schema_version_id: id(500),
      implementation_resource_id: impl.resource_id, implementation_version_id: impl.version_id,
      status: 'AVAILABLE', values: {}}]};
  await client(() => json(value)).sdk.query(q);
  const bad = structuredClone(value); bad.interface_bindings.implementations[0].implementation.version_id = id(99);
  await rejects(() => client(() => json(bad)).sdk.query(q));
  const missing = structuredClone(value); missing.interface_bindings.implementations = [null];
  await rejects(() => client(() => json(missing)).sdk.query(q));
});

test('invalid requests are rejected before authentication or transport', async () => {
  const {sdk, calls} = client(() => {throw Error('must not fetch');});
  await rejects(() => sdk.query(query({limit: 201})), 400);
  await rejects(() => sdk.query(query({offset: '1'})), 400);
  await rejects(() => sdk.runSavedSet({resource_id: id(1)}), 400);
  assert.equal(calls.length, 0);
});

test('membership values remain exact through asynchronous capture, saved-set paging and hop predicates', async () => {
  const q = query({filters: [{field: 'source_column', operator: 'in', value: ['Y', 'AA']}],
    traversal: [{kind: 'reference', name: 'source_record_id', direction: 'outgoing',
      filters: [{field: 'sheet', operator: 'not_in', value: ['Excluded', ' Excluded ']}]}]});
  const expected = structuredClone(q);
  const {sdk, calls} = client((url, init) => json(init.method === 'GET'
    ? {...result(expected), definition_id: reference.resource_id, definition_version_id: reference.version_id}
    : result(JSON.parse(init.body))), async () => {
    q.filters[0].value.push('Z');
    q.traversal[0].filters[0].value[0] = 'changed';
    return 'token';
  });
  const direct = await sdk.query(q);
  assert.deepEqual(direct.query, expected);
  assert.deepEqual(JSON.parse(calls[0].init.body), expected);
  const saved = await sdk.runSavedSet(reference, {limit: 1, valid_at: time, known_at: time});
  const next = await sdk.nextPage(saved);
  assert.deepEqual(next.query, {...expected, offset: 1});
  assert.equal(next.definition_version_id, reference.version_id);
  const changed = client((url, init) => {
    const response = result(JSON.parse(init.body));
    response.query.filters[0].value = ['Y', 'Z'];
    return json(response);
  });
  await rejects(() => changed.sdk.query(expected));
});

test('membership rejects ambiguous scalar lists and shared budget overflow before authentication', async () => {
  let auth = 0;
  const {sdk, calls} = client(() => {throw Error('must not fetch');}, () => {auth++; return 'token';});
  for (const filter of [
    {field: 'code', operator: 'in', value: 'Y'},
    {field: 'code', operator: 'in', value: []},
    {field: 'code', operator: 'not_in', value: ['Y', 'Y']},
    {field: 'code', operator: 'in', value: [null]},
    {field: 'code', operator: 'in', value: [true, 1]},
    {field: 'code', operator: 'in', value: [Number.MAX_SAFE_INTEGER + 1]},
    {field: 'code', operator: 'eq', value: ['Y']},
    {field: 'code', operator: 'gte', value: [1, 2]},
  ]) await rejects(() => sdk.query(query({filters: [filter]})), 400);
  await rejects(() => sdk.query(query({
    filters: [{field: 'code', operator: 'in', value: Array.from({length: 60}, (_, i) => String(i))}],
    traversal: [{name: 'company_id', filters: [{field: 'code', operator: 'not_in',
      value: Array.from({length: 41}, (_, i) => String(i))}]}],
  })), 400);
  assert.equal(auth, 0);
  assert.equal(calls.length, 0);
});

test('compound root and reached filters stay exact through capture and saved paging', async () => {
  const expression = {op: 'all', conditions: [
    {op: 'any', conditions: [{field: 'debit_account_id', value: id(20)}, {field: 'credit_account_id', value: id(21)}]},
    {field: 'source_column', operator: 'in', value: ['Y', 'AA']},
  ]};
  const q = query({filter_expression: expression, traversal: [{name: 'source_record_id',
    filter_expression: {op: 'any', conditions: [{field: 'sheet', value: 'TR'}, {field: 'sheet', value: 'Base'}]}}]});
  const expected = structuredClone(q);
  const {sdk, calls} = client((url, init) => json(init.method === 'GET'
    ? {...result(expected), definition_id: reference.resource_id, definition_version_id: reference.version_id}
    : result(JSON.parse(init.body))), async () => {
    expression.conditions[0].op = 'all';
    expression.conditions[1].value.push('changed');
    q.traversal[0].filter_expression.conditions[0].value = 'changed';
    return 'token';
  });
  assert.deepEqual((await sdk.query(q)).query, expected);
  assert.deepEqual(JSON.parse(calls[0].init.body), expected);
  const saved = await sdk.runSavedSet(reference, {limit: 1, valid_at: time, known_at: time});
  assert.deepEqual((await sdk.nextPage(saved)).query, {...expected, offset: 1});
  const equivalent = structuredClone(expected);
  equivalent.filter_expression.conditions[0].conditions[0].operator = 'eq';
  await client(() => json(result(equivalent))).sdk.query(expected);
  const changed = structuredClone(expected);
  changed.traversal[0].filter_expression.op = 'all';
  await rejects(() => client(() => json(result(changed))).sdk.query(expected));
});

test('compound depth and shared leaf or membership limits fail before authentication', async () => {
  let auth = 0;
  const {sdk, calls} = client(() => {throw Error('must not fetch');}, () => {auth++; return 'token';});
  const leaf = {field: 'code', value: 'A'};
  const group = child => ({op: 'any', conditions: [leaf, child]});
  const cycle = group(leaf); cycle.conditions[1] = cycle;
  for (const filter_expression of [group(group(group(group(leaf)))), cycle,
    {op: 'any', conditions: [leaf]}, {op: 'not', conditions: [leaf, leaf]},
    {op: 'any', conditions: [leaf, {field: 'code', operator: 'in', value: ['A', true]}]},
  ]) await rejects(() => sdk.query(query({filter_expression})), 400);
  await rejects(() => sdk.query(query({filters: Array.from({length: 19}, () => leaf), filter_expression: group(leaf)})), 400);
  await rejects(() => sdk.query(query({filter_expression: group({field: 'code', operator: 'in',
    value: Array.from({length: 60}, (_, i) => String(i))}), traversal: [{name: 'source_record_id',
      filter_expression: group({field: 'code', operator: 'not_in', value: Array.from({length: 41}, (_, i) => String(i))})}]})), 400);
  assert.equal(auth, 0);
  assert.equal(calls.length, 0);
});
