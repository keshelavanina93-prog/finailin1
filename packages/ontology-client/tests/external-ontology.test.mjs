import assert from 'node:assert/strict';
import test from 'node:test';
import {createExternalOntologyClient, ExternalOntologyClientError} from '../dist/index.js';

const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const sha = 'a'.repeat(64), datasetHash = 'b'.repeat(64);
const scope = {tenant_id: id(1), legal_entity_id: 'SEG', period: '2026-09', currency: 'GEL'};
const release = {resource_id: id(2), version_id: id(3), content_hash: sha};
const source = {resource_id: id(4), version_id: id(5), content_hash: sha};
const time = '2026-09-08T08:00:00.123456Z';
const graph = 'https://example.org/ontology', subject = 'https://example.org/ontology#Company';
const document = hash => ({document_id: `doc_${hash}`, sha256: hash, byte_length: 90});
const definition = {
  contract: 'external-ontology-release/1', request: {source, release_label: 'fixture-v1', publication_status: 'DEVELOPMENT',
    modules: [{source, artifact_iri: graph, document: document(sha), format: 'TURTLE',
      owned_namespaces: [graph], permitted_import_iris: [], source_url: graph, license: 'CC0 fixture', retrieved_at: time}]},
  canonical_dataset: document(datasetHash), import_report: document(sha), request_sha256: sha,
  engine_manifest: {engine: 'pyoxigraph', engine_version: '0.5.11', network_retrieval: false},
  interpretation: 'EXTERNAL_MEANING_ONLY', reasoning: 'NONE', constraint_validation: 'NOT_PERFORMED',
};
const innerScope = {tenant_id: scope.tenant_id, legal_entity_id: scope.legal_entity_id, release_id: release.resource_id,
  release_version_id: release.version_id, release_content_hash: sha, dataset_sha256: datasetHash};
const context = request => ({release: structuredClone(release), scope: structuredClone(scope),
  mode: request.mode, known_at: request.known_at, current_use_authorized: false, business_effect_authorized: false});
const metadata = request => ({...context(request), definition: structuredClone(definition)});
const manifest = {scope: innerScope, index_key: sha, engine_version: '0.5.11', quad_count: 3, graph_iris: [graph], derived_only: true};
const quads = ['"Company"@en', '<mailto:contact@example.org>', '_:c14n0'].map(object =>
  ({subject: `<${subject}>`, predicate: '<http://www.w3.org/2000/01/rdf-schema#label>', object, graph_iri: graph}));
const projected = (request, rebuild) => ({...context(request), reasoning: 'NONE', constraint_validation: 'NOT_PERFORMED',
  projection: structuredClone(rebuild ? manifest : {scope: innerScope, subject_iri: request.subject_iri,
    quads: quads.slice(0, request.limit), truncated: request.limit < quads.length, derived_only: true})});
const json = value => new Response(JSON.stringify(value), {headers: {'Content-Type': 'application/json'}});
function setup(change = value => value, custom = {}) {
  const calls = [];
  const client = createExternalOntologyClient({baseUrl: '/api/ontology', expectedScope: scope, getToken: () => 'credential',
    fetch: async (url, init) => {
      calls.push({url, init}); const request = JSON.parse(init.body);
      const value = url.endsWith('/releases/inspect') ? metadata(request) : projected(request, url.endsWith('/index/rebuild'));
      return json(change(value, url));
    }, ...custom});
  return {client, calls};
}
const rejects = (fn, status = 502) => assert.rejects(fn, e => e instanceof ExternalOntologyClientError && e.status === status);

test('release, rebuild and subject reads use fresh auth and exactly bound retained data', async () => {
  let tokens = 0;
  const {client, calls} = setup(v => v, {getToken: () => `credential-${++tokens}`});
  const first = await client.inspectRelease({release});
  assert.deepEqual(first.definition, definition);
  assert.deepEqual((await client.rebuildIndex({release})).projection, manifest);
  const result = await client.inspectSubject({release, subject_iri: subject, limit: 2});
  assert.equal(result.projection.truncated, true);
  assert.deepEqual(result.projection.quads, quads.slice(0, 2));
  assert.equal(calls.length, 5); // Each index read also verifies its exact release's dataset pin.
  for (const [i, {init}] of calls.entries()) {
    assert.equal(init.headers.Authorization, `Bearer credential-${i + 1}`);
    assert.equal(init.redirect, 'error'); assert.equal(init.cache, 'no-store'); assert.equal(init.method, 'POST');
  }
  assert.equal(calls[2].url, '/api/ontology/external/index/rebuild');
  assert.equal(calls[4].url, '/api/ontology/external/terms/inspect');
  assert.deepEqual(JSON.parse(calls[4].init.body), {release, mode: 'CURRENT_RELEASE', known_at: null, subject_iri: subject, limit: 2});
});

test('historical timestamps preserve microseconds and freeze inputs before token retrieval', async () => {
  const request = {release: structuredClone(release), mode: 'HISTORICAL_INSPECTION', known_at: time};
  let unlock; const gate = new Promise(resolve => {unlock = resolve;});
  const {client, calls} = setup(v => ({...v, known_at: '2026-09-08T12:00:00.123456+04:00'}), {getToken: () => gate});
  const pending = client.inspectRelease(request);
  request.release.version_id = id(999); request.known_at = '2026-09-08T08:00:00.123457Z'; unlock('credential');
  await pending;
  assert.equal(JSON.parse(calls[0].init.body).release.version_id, release.version_id);
  assert.equal(JSON.parse(calls[0].init.body).known_at, time);
  await rejects(() => setup(v => ({...v, known_at: '2026-09-08T08:00:00.123457Z'})).client.inspectRelease(
    {release, mode: 'HISTORICAL_INSPECTION', known_at: time}));
});

test('RDF term IRIs retain custom schemes and literal syntax without turning them into URLs', async () => {
  const objects = ['<mailto:contact@example.org>', '"opaque"^^<custom:datatype>', '"Quoted \\"text\\""@ka', '_:c14n0'];
  const {client} = setup((v, url) => url.endsWith('/terms/inspect') ? {...v, projection: {...v.projection,
    quads: objects.map(object => ({...quads[0], predicate: '<tag:example.org,2026:classification>', object})), truncated: false}} : v);
  const result = await client.inspectSubject({release, subject_iri: subject});
  assert.deepEqual(result.projection.quads.map(q => q.object), objects);
});

test('reject scope, release, mode, authority and unexpected response fields', async () => {
  for (const change of [
    v => ({...v, scope: {...v.scope, tenant_id: id(90)}}),
    v => ({...v, scope: {...v.scope, legal_entity_id: 'SOG'}}),
    v => ({...v, scope: {...v.scope, period: '2026-08'}}),
    v => ({...v, scope: {...v.scope, currency: 'USD'}}),
    v => ({...v, release: {...v.release, version_id: id(90)}}),
    v => ({...v, release: {...v.release, content_hash: 'c'.repeat(64)}}),
    v => ({...v, mode: 'HISTORICAL_INSPECTION'}), v => ({...v, known_at: time}),
    v => ({...v, current_use_authorized: true}), v => ({...v, business_effect_authorized: true}),
    v => ({...v, local_path: 'D:\\private'}),
    v => ({...v, definition: {...v.definition, interpretation: 'ACCOUNTING_AUTHORITY'}}),
    v => ({...v, definition: {...v.definition, request: {...v.definition.request, modules: []}}}),
  ]) await rejects(() => setup(change).client.inspectRelease({release}));
});

test('bind each derived projection to dataset, graph, subject and caller result bound', async () => {
  for (const patch of [
    p => ({...p, scope: {...p.scope, dataset_sha256: 'c'.repeat(64)}}),
    p => ({...p, scope: {...p.scope, tenant_id: id(90)}}),
    p => ({...p, scope: {...p.scope, release_version_id: id(90)}}),
    p => ({...p, derived_only: false}), p => ({...p, subject_iri: graph}),
    p => ({...p, quads: [...p.quads, ...p.quads]}),
    p => ({...p, quads: [{...p.quads[0], graph_iri: 'https://other.example/graph'}]}),
    p => ({...p, quads: [{...p.quads[0], subject: '<https://other.example/subject>'}]}),
    p => ({...p, quads: [{...p.quads[0], predicate: 'not-an-RDF-term'}]}),
    p => ({...p, quads: [{...p.quads[0], object: 'not-an-RDF-term'}]}),
    p => ({...p, index_path: 'D:\\cache'}),
  ]) await rejects(() => setup((v, url) => url.endsWith('/terms/inspect') ? {...v, projection: patch(v.projection)} : v)
    .client.inspectSubject({release, subject_iri: subject, limit: 1}));
  for (const patch of [{engine_version: '0.6.0'}, {quad_count: -1}, {graph_iris: ['https://other.example/graph']}, {index_key: 'invalid'}])
    await rejects(() => setup((v, url) => url.endsWith('/index/rebuild') ? {...v, projection: {...v.projection, ...patch}} : v)
      .client.rebuildIndex({release}));
});

test('invalid queries and local paths refuse before authentication or transport', async () => {
  const {client, calls} = setup();
  for (const input of [{release, mode: null}, {release, mode: 'HISTORICAL_INSPECTION'}, {release, known_at: time},
    {release, mode: 'HISTORICAL_INSPECTION', known_at: '2026-02-30T12:00:00Z'}, {release, path: 'D:\\cache'}, {release, query: 'SELECT * WHERE {?s ?p ?o}'}]) {
    await assert.rejects(async () => client.inspectRelease(input), e => e.status === 400);
  }
  for (const patch of [{subject_iri: 'file:///D:/private'}, {subject_iri: '<https://example.org/x>'},
    {limit: 0}, {limit: 101}, {limit: null}, {limit: true}, {limit: 1.5}])
    await assert.rejects(async () => client.inspectSubject({release, subject_iri: subject, ...patch}), e => e.status === 400);
  assert.equal(calls.length, 0);
  for (const baseUrl of ['//evil.example/api', '/\\evil.example', 'file:///D:/private', 'https://user:secret@example.org'])
    assert.throws(() => setup(v => v, {baseUrl}), e => e.status === 400);
});

test('cancellation stops between metadata and index work; errors never expose transport payloads', async () => {
  const controller = new AbortController();
  const {client, calls} = setup(v => {controller.abort(); return v;});
  await assert.rejects(() => client.rebuildIndex({release}, {signal: controller.signal}), e => e.name === 'AbortError');
  assert.equal(calls.length, 1);
  const aborted = new AbortController(); aborted.abort();
  let auth = 0;
  const before = setup(v => v, {getToken: () => {auth++; return 'token';}});
  await assert.rejects(() => before.client.inspectRelease({release}, {signal: aborted.signal}), e => e.name === 'AbortError');
  assert.equal(auth, 0);
  await rejects(() => setup(v => v, {getToken: () => ''}).client.inspectRelease({release}), 401);
  await rejects(() => setup(v => v, {fetch: async () => {throw Error('private transport detail');}}).client.inspectRelease({release}), 0);
  const failure = setup(v => v, {fetch: async () => new Response('{"detail":"private server detail"}', {status: 403})});
  await assert.rejects(() => failure.client.inspectRelease({release}), e => e.status === 403 && !e.message.includes('private'));
  await rejects(() => setup(v => v, {fetch: async () => new Response('not json')}).client.inspectRelease({release}));
});
