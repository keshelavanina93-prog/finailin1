import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {createOntologyValidationClient, OntologyValidationClientError} from '../dist/index.js';

const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const hash = 'a'.repeat(64), pin = n => ({resource_id: id(n), version_id: id(n + 1), content_hash: hash});
const scope = {tenant_id: id(1), legal_entity_id: 'SEG', period: '2026-09', currency: 'GEL'};
const request = {request_id: id(2), constraint_profile: pin(3), data: {release: pin(5), graph_iris: ['https://example.test/data']}};
const canonical = v => Array.isArray(v) ? '[' + v.map(canonical).join(',') + ']'
  : v && typeof v === 'object' ? '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}' : JSON.stringify(v);
const digest = v => createHash('sha256').update(canonical(v)).digest('hex');
const doc = (sha = hash, length = 50) => ({document_id: `doc_${sha}`, sha256: sha, byte_length: length});
const definition = {version: 'ontology-validation/1', nodes: [{id: 'validate', function: 'pyshacl/0.40.1-core-offline/1', depends_on: []}], outputs: {report: 'ontology-validation-report/1'}};
const manifest = {profile: 'G8_OFFLINE_SHACL_CORE_1', engine: 'pyshacl', engine_version: '0.40.1', rdflib_version: '7.6.0',
  canonicalizer: 'pyoxigraph/0.5.11/RDFC-1.0', inference: 'none', advanced: false, js: false, sparql_mode: false,
  network_retrieval: false, owl_imports: false, abort_on_first: false, allow_infos: false, allow_warnings: false, meta_shacl: true,
  report_message_policy: 'AUTHOR_MESSAGES_ONLY', blank_node_origin_policy: 'SELECTED_DATASET_SHA256_CANONICAL_LABEL_ROLE',
  coverage_policy: 'COMPLETED_SUBSTANTIVE_CORE_COMPONENT_SHAPE_FOCUS_TUPLES', selection_mode: 'PROFILE_TARGETS', focus_iris: '[]', shape_iris: '[]',
  source_hash_policy: 'UTF8_SOURCE_CRLF_TO_LF_SHA256', dependency_versions: JSON.stringify({pyshacl: '0.40.1', rdflib: '7.6.0', pyoxigraph: '0.5.11', owlrl: '7.6.2', pyparsing: '3.3.2'}),
  controller_source_sha256: hash, worker_source_sha256: hash, resource_caps_source_sha256: hash};
const identity = r => 'ontology-validation:' + r.request_id;
const start = r => ({workflow_id: identity(r), request_id: r.request_id, request_sha256: digest(r), scope: structuredClone(scope),
  state: 'RETAINED_DISPATCH_UNOBSERVABLE', redispatch: 'RETRY_SAME_REQUEST', automatic_outbox_dispatch: false, business_effect_authorized: false});
function evidence(outcome = 'CONFORMS', input = request) {
  const r = structuredClone(input), workflow = identity(r);
  const plan = {contract: 'ontology-validation-plan/1', request_sha256: digest(r), ontology_profile: pin(8), constraint_profile: r.constraint_profile,
    data: {...r.data, canonical_dataset: doc()}, shapes: {release: pin(10), graph_iris: ['https://example.test/shapes'], canonical_dataset: doc()},
    selection: {mode: 'PROFILE_TARGETS', focus_iris: [], shape_iris: []}, validator: 'pyshacl/0.40.1-core-offline/1',
    validator_manifest_sha256: digest(manifest), business_effect_authorized: false};
  const planHash = digest(plan), evaluated = ['CONFORMS', 'VIOLATES'].includes(outcome);
  const report = {contract: 'ontology-validation-observation/1', request_sha256: digest(r), plan_sha256: planHash,
    business_effect_authorized: false, outcome, ...(outcome === 'REFUSED' ? {refusal_code: 'UNSUPPORTED_SHAPES', conforms: null, rdf_report: null}
      : {result: {status: outcome, conforms: outcome === 'CONFORMS' ? true : outcome === 'VIOLATES' ? false : null,
        data_sha256: hash, shapes_sha256: hash, data_graph_iris: r.data.graph_iris, shape_graph_iris: plan.shapes.graph_iris,
        report_sha256: hash, evaluated_shape_count: +evaluated, evaluated_focus_count: +evaluated,
        evaluated_constraint_count: +evaluated, violation_count: +(outcome === 'VIOLATES'), manifest: structuredClone(manifest)}, rdf_report: doc()})};
  const terminal = {contract: 'ontology-validation-report/1', workflow_id: workflow, request_sha256: digest(r), plan_sha256: planHash,
    report: doc(digest(report), Buffer.byteLength(canonical(report))), outcome, business_effect_authorized: false};
  const publication = {protocol: 'execution-publication/1', workflow_id: workflow, generation: 0, definition_sha256: digest(definition), authority: 'EXECUTION_ONLY',
    outputs: [{slot: 'report', artifact_type: 'ontology-validation-report/1', event_id: 'output:' + digest([0, 'report']), sha256: digest(terminal), value: terminal}]};
  publication.publication_id = 'pub_' + digest(publication);
  return {workflow_id: workflow, actor_id: 'synthetic-author', created_at: '2026-09-08T12:00:00Z',
    request: {request: r, plan, plan_sha256: planHash, definition}, definition, events: [], scope: structuredClone(scope),
    state: 'PUBLISHED', terminal, report, publications: [publication], current_use_authorized: false, business_effect_authorized: false,
    runtime_status: 'UNOBSERVABLE'};
}
function reseal(v) {
  v.request.plan.validator_manifest_sha256 = digest(v.report?.result?.manifest ?? manifest);
  v.request.plan_sha256 = digest(v.request.plan);
  v.terminal.plan_sha256 = v.request.plan_sha256; v.report.plan_sha256 = v.request.plan_sha256;
  v.terminal.report = doc(digest(v.report), Buffer.byteLength(canonical(v.report)));
  const p = v.publications[0]; p.outputs[0].value = v.terminal; p.outputs[0].sha256 = digest(v.terminal);
  delete p.publication_id; p.publication_id = 'pub_' + digest(p);
  return v;
}
function setup({change = v => v, outcome = 'CONFORMS', getToken = () => 'synthetic-token', fetch, input = request} = {}) {
  const calls = [];
  const client = createOntologyValidationClient({baseUrl: '/api/ontology', expectedScope: scope, getToken,
    fetch: fetch ?? (async (url, init) => {
      calls.push({url, init});
      const body = init.body ? JSON.parse(init.body) : undefined;
      const value = init.method === 'GET' ? evidence(outcome, input) : url.endsWith('/cancel')
        ? {request_id: input.request_id, command_id: body.command_id, scope: structuredClone(scope),
          cancellation: {workflow_id: identity(input), state: 'CANCELLED'}, runtime_notified: false, business_effect_authorized: false}
        : start(body);
      return new Response(JSON.stringify(change(value)), {status: init.method === 'POST' && !url.endsWith('/cancel') ? 202 : 200});
    })});
  return {client, calls};
}
const rejects = (fn, status = 502) => assert.rejects(fn, e => e instanceof OntologyValidationClientError && e.status === status);

test('start, read and cancel preserve evidence versus unobservable Temporal status', async () => {
  const {client, calls} = setup();
  assert.equal((await client.startValidation(request)).state, 'RETAINED_DISPATCH_UNOBSERVABLE');
  const read = await client.readValidation(request);
  assert.equal(read.state, 'PUBLISHED'); assert.equal(read.runtime_status, 'UNOBSERVABLE');
  assert.equal(read.report.result.conforms, true); assert.equal(read.business_effect_authorized, false);
  const cancelled = await client.cancelValidation({request_id: request.request_id, command_id: id(90), reason: 'Cancel synthetic validation'});
  assert.equal(cancelled.runtime_notified, false); assert.equal(cancelled.cancellation.state, 'CANCELLED');
  assert.equal(calls[1].init.method, 'GET'); assert.equal(calls[1].init.body, undefined);
  for (const {init} of calls) {assert.equal(init.cache, 'no-store'); assert.equal(init.redirect, 'error'); assert.equal(init.headers.Authorization, 'Bearer synthetic-token');}
});

test('all terminal outcomes remain distinct; incomplete work has no terminal report', async () => {
  for (const outcome of ['CONFORMS', 'VIOLATES', 'NOT_EVALUATED', 'REFUSED']) {
    const result = await setup({outcome}).client.readValidation(request);
    assert.equal(result.terminal.outcome, outcome);
    assert.equal(result.report.outcome, outcome);
    if (outcome === 'NOT_EVALUATED') assert.equal(result.report.result.conforms, null);
    if (outcome === 'REFUSED') assert.equal(result.report.conforms, null);
  }
  const pending = setup({change: v => ({...v, terminal: null, report: null, publications: [], state: 'INTENT_RETAINED'})});
  assert.equal((await pending.client.readValidation(request)).terminal, null);
});

test('request intent freezes before asynchronous authentication for start/read/cancel', async () => {
  for (const method of ['startValidation', 'readValidation', 'cancelValidation']) {
    let unlock; const token = new Promise(resolve => {unlock = resolve;});
    const {client, calls} = setup({getToken: () => token});
    const input = method === 'cancelValidation' ? {request_id: request.request_id, command_id: id(90), reason: 'Original cancellation reason'} : structuredClone(request);
    const pending = client[method](input); input.request_id = id(99);
    if (method === 'cancelValidation') {input.command_id = id(91); input.reason = 'Changed cancellation reason';}
    else input.data.release.version_id = id(99);
    unlock('synthetic-token'); await pending;
    if (method !== 'startValidation') assert.ok(calls[0].url.includes(request.request_id));
    if (method === 'startValidation') assert.deepEqual(JSON.parse(calls[0].init.body), request);
    if (method === 'cancelValidation') assert.deepEqual(JSON.parse(calls[0].init.body), {command_id: id(90), reason: 'Original cancellation reason'});
  }
});

test('scope, workflow, request pins, graphs, plan and retained hashes reject tampering', async () => {
  for (const change of [
    v => ({...v, scope: {...v.scope, legal_entity_id: 'SOG'}}), v => ({...v, workflow_id: 'ontology-validation:' + id(999)}),
    v => ({...v, request: {...v.request, request: {...v.request.request, constraint_profile: pin(999)}}}),
    v => ({...v, request: {...v.request, plan_sha256: 'b'.repeat(64)}}),
    v => {v.request.plan.data.graph_iris = ['https://example.test/other']; return reseal(v);},
    v => {v.report.result.data_sha256 = 'b'.repeat(64); return reseal(v);},
    v => {v.report.result.report_sha256 = 'b'.repeat(64); return reseal(v);},
    v => {v.report.result.manifest.inference = 'rdfs'; return reseal(v);},
    v => {v.terminal.report.byte_length += 1; return v;},
    v => ({...v, business_effect_authorized: true}), v => ({...v, current_use_authorized: true}),
    v => {v.publications[0].authority = 'ACCOUNTING_AUTHORITY'; return v;},
    v => {v.publications[0].publication_id = 'pub_' + 'b'.repeat(64); return v;},
    v => ({...v, state: 'RUNNING'}),
  ]) await rejects(() => setup({change}).client.readValidation(request));
});

test('rehashed false conformance and invented coverage still refuse', async () => {
  for (const outcome of ['NOT_EVALUATED', 'REFUSED']) await rejects(() => setup({outcome, change: v => {
    if (outcome === 'REFUSED') v.report.conforms = true;
    else {v.report.result.conforms = true; v.report.result.evaluated_constraint_count = 1;}
    return reseal(v);
  }}).client.readValidation(request));
  await rejects(() => setup({change: v => {v.report.result.evaluated_focus_count = 0; return reseal(v);}}).client.readValidation(request));
});

test('wrong start digest and cancellation acknowledgement refuse', async () => {
  await rejects(() => setup({change: v => ({...v, request_sha256: 'b'.repeat(64)})}).client.startValidation(request));
  await rejects(() => setup({change: v => ({...v, command_id: id(999)})}).client.cancelValidation(
    {request_id: request.request_id, command_id: id(90), reason: 'Cancel synthetic validation'}));
});

test('abort during token wait or response decode never accepts late evidence', async () => {
  let unlock; const token = new Promise(resolve => {unlock = resolve;});
  const {client, calls} = setup({getToken: () => token});
  const controller = new AbortController(), pending = client.readValidation(request, {signal: controller.signal});
  controller.abort(); unlock('synthetic-token');
  await assert.rejects(pending, e => e.name === 'AbortError'); assert.equal(calls.length, 0);
  const late = new AbortController();
  const client2 = setup({fetch: async () => ({ok: true, status: 200, json: async () => {late.abort(); return evidence();}})}).client;
  await assert.rejects(client2.readValidation(request, {signal: late.signal}), e => e.name === 'AbortError');
});

test('invalid intent refuses before auth and transport; denied scope stays an HTTP refusal', async () => {
  let tokens = 0; const {client, calls} = setup({getToken: () => {tokens++; return 'token';}});
  for (const patch of [{request_id: 'not-uuid'}, {data: {...request.data, graph_iris: ['file:///D:/private']}}, {data: {...request.data, graph_iris: []}}, {query: 'SELECT * WHERE {?s ?p ?o}'}])
    await rejects(() => client.startValidation({...request, ...patch}), 400);
  assert.equal(tokens, 0); assert.equal(calls.length, 0);
  await rejects(() => setup({fetch: async () => new Response('{}', {status: 403})}).client.readValidation(request), 403);
  await rejects(() => setup({fetch: async () => {throw new Error('private environment');}}).client.readValidation(request), 0);
});

test('Unicode graph request matches Python ensure_ascii=False retained hashing exactly', async () => {
  const input = structuredClone(request);
  input.data.graph_iris = ['https://example.test/მოდელი/😀'];
  // Independent Python ontology_import.encoded fixture: 533 UTF-8 bytes, compact sorted keys.
  const expected = '1f7a633f8b4e6c271f22f2f9ba20a46434957351d78c15ffecbf337a7c897efb';
  assert.equal(Buffer.byteLength(canonical(input)), 533);
  const {client} = setup({input});
  assert.equal((await client.startValidation(input)).request_sha256, expected);
  const retained = await client.readValidation(input);
  assert.equal(retained.plan.request_sha256, expected);
  assert.deepEqual(retained.request.data.graph_iris, input.data.graph_iris);
});
