import type {OntologyClientOptions, RequestOptions} from './index.js';
import type {ExternalDocument, ExternalOntologyPin, ExternalOntologyScope} from './external-ontology.js';

export interface ValidationGraphSelection {release: ExternalOntologyPin; graph_iris: string[];}
export interface ValidationRunRequest {request_id: string; constraint_profile: ExternalOntologyPin; data: ValidationGraphSelection;}
export interface ValidationTargetSelection {
  mode: 'PROFILE_TARGETS' | 'FILTER_TARGETS' | 'EXPLICIT_SHAPE_FOCUS'; focus_iris: string[]; shape_iris: string[];
}
export interface ValidationRetainedGraph extends ValidationGraphSelection {canonical_dataset: ExternalDocument;}
export interface ValidationPlan {
  contract: 'ontology-validation-plan/1'; request_sha256: string; ontology_profile: ExternalOntologyPin;
  constraint_profile: ExternalOntologyPin; data: ValidationRetainedGraph; shapes: ValidationRetainedGraph;
  selection: ValidationTargetSelection; validator: 'pyshacl/0.40.1-core-offline/1';
  validator_manifest_sha256: string; business_effect_authorized: false;
}
export type ValidationOutcome = 'CONFORMS' | 'VIOLATES' | 'NOT_EVALUATED' | 'REFUSED';
export interface ValidationReportReference {
  contract: 'ontology-validation-report/1'; workflow_id: string; request_sha256: string; plan_sha256: string;
  report: ExternalDocument; outcome: ValidationOutcome; business_effect_authorized: false;
}
export interface ValidationEvaluatedResult {
  status: Exclude<ValidationOutcome, 'REFUSED'>; conforms: boolean | null;
  data_sha256: string; shapes_sha256: string; data_graph_iris: string[]; shape_graph_iris: string[];
  report_sha256: string; evaluated_shape_count: number; evaluated_focus_count: number;
  evaluated_constraint_count: number; violation_count: number; manifest: Record<string, string | number | boolean>;
}
export type ValidationObservation = {
  contract: 'ontology-validation-observation/1'; request_sha256: string; plan_sha256: string;
  business_effect_authorized: false;
} & ({outcome: Exclude<ValidationOutcome, 'REFUSED'>; result: ValidationEvaluatedResult; rdf_report: ExternalDocument}
  | {outcome: 'REFUSED'; refusal_code: string; conforms: null; rdf_report: null});
export interface ValidationStart {
  workflow_id: string; request_id: string; scope: ExternalOntologyScope; request_sha256: string;
  state: 'START_REQUEST_RECORDED' | 'RETAINED_DISPATCH_UNOBSERVABLE'; redispatch: 'RETRY_SAME_REQUEST';
  automatic_outbox_dispatch: false; business_effect_authorized: false;
}
export interface ValidationCancellation {request_id: string; command_id: string; reason: string;}
export interface ValidationCancellationReceipt {
  request_id: string; command_id: string; scope: ExternalOntologyScope;
  cancellation: {workflow_id: string; state: 'CANCELLED'};
  runtime_notified: boolean; business_effect_authorized: false;
}
export interface ValidationRead {
  workflow_id: string; scope: ExternalOntologyScope; request: ValidationRunRequest; plan: ValidationPlan;
  plan_sha256: string; state: 'INTENT_RETAINED' | 'RUNNING' | 'COMPLETED' | 'PUBLISHED' | 'CANCELLED';
  terminal: ValidationReportReference | null; report: ValidationObservation | null;
  publication_id: string | null; runtime_status: 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELED'
    | 'TERMINATED' | 'CONTINUED_AS_NEW' | 'TIMED_OUT' | 'UNKNOWN' | 'UNOBSERVABLE';
  execution: {state: 'PENDING' | 'VERIFYING_INPUTS' | 'VALIDATING' | 'PUBLISHING_REPORT' | 'COMPLETED' | 'INTERRUPTED'} | null;
  current_use_authorized: false; business_effect_authorized: false;
}
export interface OntologyValidationClientOptions extends OntologyClientOptions {expectedScope: ExternalOntologyScope;}
export class OntologyValidationClientError extends Error {
  constructor(public readonly status: number, message: string) {super(message); this.name = 'OntologyValidationClientError';}
}
type Obj = Record<string, unknown>;
const object = (v: unknown): v is Obj => v !== null && typeof v === 'object' && !Array.isArray(v);
const shape = (v: unknown, required: string[], optional: string[] = []): v is Obj => object(v)
  && required.every(k => Object.hasOwn(v, k)) && Object.keys(v).every(k => required.includes(k) || optional.includes(k));
const text = (v: unknown, max: number): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
const uuid = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(v);
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const count = (v: unknown, max: number) => Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= max;
const pin = (v: unknown): v is ExternalOntologyPin => shape(v, ['resource_id', 'version_id', 'content_hash'])
  && uuid(v.resource_id) && uuid(v.version_id) && hash(v.content_hash);
const scope = (v: unknown): v is ExternalOntologyScope => shape(v, ['tenant_id', 'legal_entity_id', 'period', 'currency'])
  && uuid(v.tenant_id) && text(v.legal_entity_id, 128) && typeof v.period === 'string'
  && /^\d{4}-(0[1-9]|1[0-2])$/.test(v.period) && typeof v.currency === 'string' && /^[A-Z]{3}$/.test(v.currency);
const document = (v: unknown): v is ExternalDocument => shape(v, ['document_id', 'sha256', 'byte_length'])
  && typeof v.document_id === 'string' && /^doc_[a-f0-9]{64}$/.test(v.document_id)
  && hash(v.sha256) && count(v.byte_length, 32_000_000) && (v.byte_length as number) > 0;
function iri(v: unknown): v is string {
  if (!text(v, 2048) || /[\s\x00-\x1f<>"{}|^`\\]/.test(v)) return false;
  try {const u = new URL(v); return ['http:', 'https:', 'urn:'].includes(u.protocol)
    && !u.username && !u.password && (u.protocol === 'urn:' ? Boolean(u.pathname) : Boolean(u.hostname));}
  catch {return false;}
}
const iris = (v: unknown, max: number, min = 0): v is string[] => Array.isArray(v) && v.length >= min
  && v.length <= max && v.every(iri) && new Set(v).size === v.length;
const graph = (v: unknown, retained = false): v is ValidationRetainedGraph => shape(v,
  ['release', 'graph_iris', ...(retained ? ['canonical_dataset'] : [])]) && pin(v.release)
  && iris(v.graph_iris, 16, 1) && (!retained || document(v.canonical_dataset));
const sameId = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();
const samePin = (a: ExternalOntologyPin, b: ExternalOntologyPin) => sameId(a.resource_id, b.resource_id)
  && sameId(a.version_id, b.version_id) && a.content_hash === b.content_hash;
// Match Python's Unicode code-point ordering for retained UTF-8 canonical JSON.
function compare(a: string, b: string): number {
  const x = Array.from(a), y = Array.from(b);
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const d = x[i]!.codePointAt(0)! - y[i]!.codePointAt(0)!; if (d) return d;
  }
  return x.length - y.length;
}
function canonical(v: unknown): string {
  if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
  if (object(v)) return '{' + Object.keys(v).sort(compare).map(k => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}';
  return JSON.stringify(v) ?? 'undefined';
}
const same = (a: unknown, b: unknown) => canonical(a) === canonical(b);
async function digest(v: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonical(v));
  return Array.from(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
}
function fail(message: string, status = 502): never {throw new OntologyValidationClientError(status, message);}
function capture(v: ValidationRunRequest): ValidationRunRequest {
  if (!shape(v, ['request_id', 'constraint_profile', 'data']) || !uuid(v.request_id) || !pin(v.constraint_profile) || !graph(v.data))
    fail('A complete exact validation request is required', 400);
  const result = structuredClone(v);
  result.request_id = result.request_id.toLowerCase();
  for (const p of [result.constraint_profile, result.data.release]) {p.resource_id = p.resource_id.toLowerCase(); p.version_id = p.version_id.toLowerCase();}
  result.data.graph_iris.sort(compare);
  return result;
}
function selection(v: unknown): v is ValidationTargetSelection {
  if (!shape(v, ['mode', 'focus_iris', 'shape_iris']) || !iris(v.focus_iris, 100) || !iris(v.shape_iris, 32)) return false;
  return v.mode === 'PROFILE_TARGETS' ? v.focus_iris.length === 0 && v.shape_iris.length === 0
    : v.mode === 'FILTER_TARGETS' ? v.focus_iris.length > 0
    : v.mode === 'EXPLICIT_SHAPE_FOCUS' && v.focus_iris.length > 0 && v.shape_iris.length > 0;
}
const DEFINITION = {version: 'ontology-validation/1', nodes: [{id: 'validate', function: 'pyshacl/0.40.1-core-offline/1', depends_on: []}], outputs: {report: 'ontology-validation-report/1'}};
const outcomes = ['CONFORMS', 'VIOLATES', 'NOT_EVALUATED', 'REFUSED'];
function fixedManifest(v: Obj, selected: ValidationTargetSelection): boolean {
  const fixed = {profile: 'G8_OFFLINE_SHACL_CORE_1', engine: 'pyshacl', engine_version: '0.40.1',
    rdflib_version: '7.6.0', canonicalizer: 'pyoxigraph/0.5.11/RDFC-1.0', inference: 'none', advanced: false,
    js: false, sparql_mode: false, network_retrieval: false, owl_imports: false, abort_on_first: false,
    allow_infos: false, allow_warnings: false, meta_shacl: true, report_message_policy: 'AUTHOR_MESSAGES_ONLY',
    blank_node_origin_policy: 'SELECTED_DATASET_SHA256_CANONICAL_LABEL_ROLE',
    coverage_policy: 'COMPLETED_SUBSTANTIVE_CORE_COMPONENT_SHAPE_FOCUS_TUPLES',
    source_hash_policy: 'UTF8_SOURCE_CRLF_TO_LF_SHA256', selection_mode: selected.mode};
  if (!Object.entries(fixed).every(([k, value]) => v[k] === value)
    || !['controller_source_sha256', 'worker_source_sha256', 'resource_caps_source_sha256'].every(k => hash(v[k]))) return false;
  try {return same(JSON.parse(String(v.focus_iris)), selected.focus_iris) && same(JSON.parse(String(v.shape_iris)), selected.shape_iris)
    && same(JSON.parse(String(v.dependency_versions)), {pyshacl: '0.40.1', rdflib: '7.6.0', pyoxigraph: '0.5.11', owlrl: '7.6.2', pyparsing: '3.3.2'});}
  catch {return false;}
}

/** Read and control retained validation intent; no shape authoring or business promotion. */
export function createOntologyValidationClient(options: OntologyValidationClientOptions) {
  if (!scope(options.expectedScope)) fail('An exact expected scope is required', 400);
  const expected = structuredClone(options.expectedScope), base = options.baseUrl.replace(/\/+$/, '');
  if (!base || /[?#\s\\]/.test(base) || base.startsWith('//') || !(base.startsWith('/') || /^https?:\/\//.test(base))) fail('Invalid ontology API base URL', 400);
  if (!base.startsWith('/')) {try {const u = new URL(base); if (u.username || u.password) fail('Invalid ontology API base URL', 400);} catch {fail('Invalid ontology API base URL', 400);}}
  const transport = options.fetch ?? globalThis.fetch;
  function checkScope(v: unknown) {
    if (!scope(v) || !sameId(v.tenant_id, expected.tenant_id) || v.legal_entity_id !== expected.legal_entity_id
      || v.period !== expected.period || v.currency !== expected.currency) fail('Validation response changed exact scope');
  }
  async function request(path: string, method: 'GET' | 'POST', body: unknown, signal?: AbortSignal): Promise<unknown> {
    signal?.throwIfAborted(); const token = await options.getToken(); signal?.throwIfAborted();
    if (typeof token !== 'string' || !token.trim()) fail('Authentication is required', 401);
    let response: Response;
    try {response = await transport(`${base}/external/validation/runs${path}`, {method,
      headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
      ...(body === undefined ? {} : {body: JSON.stringify(body)}), cache: 'no-store', redirect: 'error', ...(signal ? {signal} : {})});}
    catch {signal?.throwIfAborted(); return fail('Validation server is unreachable', 0);}
    let v: unknown;
    try {v = await response.json();} catch {signal?.throwIfAborted(); return fail('Invalid validation response', response.ok ? 502 : response.status);}
    signal?.throwIfAborted(); if (!response.ok) fail('Validation request failed', response.status);
    if (response.status !== (method === 'POST' && path === '' ? 202 : 200)) fail('Unexpected validation response status');
    return v;
  }
  async function startValidation(input: ValidationRunRequest, opts: RequestOptions = {}): Promise<ValidationStart> {
    const captured = capture(input), signal = opts.signal;
    const sha = await digest(captured), workflow = 'ontology-validation:' + captured.request_id;
    const v = await request('', 'POST', captured, signal);
    if (!shape(v, ['workflow_id', 'request_id', 'scope', 'request_sha256', 'state', 'redispatch', 'automatic_outbox_dispatch', 'business_effect_authorized'])
      || v.workflow_id !== workflow || v.request_id !== captured.request_id || v.request_sha256 !== sha
      || !['START_REQUEST_RECORDED', 'RETAINED_DISPATCH_UNOBSERVABLE'].includes(String(v.state))
      || v.redispatch !== 'RETRY_SAME_REQUEST' || v.automatic_outbox_dispatch !== false || v.business_effect_authorized !== false) fail('Start receipt changed retained validation intent');
    checkScope(v.scope); return v as unknown as ValidationStart;
  }
  async function readValidation(input: ValidationRunRequest, opts: RequestOptions = {}): Promise<ValidationRead> {
    const captured = capture(input), signal = opts.signal, workflow = 'ontology-validation:' + captured.request_id;
    const sha = await digest(captured);
    const v = await request('/' + captured.request_id, 'GET', undefined, signal);
    if (!shape(v, ['workflow_id', 'actor_id', 'created_at', 'request', 'definition', 'events', 'scope', 'state', 'terminal', 'report', 'publications', 'current_use_authorized', 'business_effect_authorized', 'runtime_status'], ['execution'])
      || v.workflow_id !== workflow || !text(v.actor_id, 256) || !text(v.created_at, 64) || !Number.isFinite(Date.parse(v.created_at))
      || v.current_use_authorized !== false || v.business_effect_authorized !== false
      || !same(v.definition, DEFINITION) || !Array.isArray(v.events) || v.events.length > 10000
      || !shape(v.request, ['request', 'plan', 'plan_sha256', 'definition']) || !same(v.request.request, captured)
      || !same(v.request.definition, DEFINITION) || !hash(v.request.plan_sha256)) fail('Validation evidence changed retained intent');
    checkScope(v.scope);
    const plan = v.request.plan;
    if (!shape(plan, ['contract', 'request_sha256', 'ontology_profile', 'constraint_profile', 'data', 'shapes', 'selection', 'validator', 'validator_manifest_sha256', 'business_effect_authorized'])
      || plan.contract !== 'ontology-validation-plan/1' || plan.request_sha256 !== sha || !pin(plan.ontology_profile)
      || !pin(plan.constraint_profile) || !samePin(plan.constraint_profile, captured.constraint_profile)
      || !graph(plan.data, true) || !graph(plan.shapes, true) || !samePin(plan.data.release, captured.data.release)
      || !same(plan.data.graph_iris, captured.data.graph_iris) || !selection(plan.selection)
      || plan.validator !== 'pyshacl/0.40.1-core-offline/1' || !hash(plan.validator_manifest_sha256)
      || plan.business_effect_authorized !== false || await digest(plan) !== v.request.plan_sha256) fail('Validation plan integrity failed');
    const terminal = v.terminal, observation = v.report;
    if (terminal !== null) {
      if (!shape(terminal, ['contract', 'workflow_id', 'request_sha256', 'plan_sha256', 'report', 'outcome', 'business_effect_authorized'])
        || terminal.contract !== 'ontology-validation-report/1' || terminal.workflow_id !== workflow
        || terminal.request_sha256 !== sha || terminal.plan_sha256 !== v.request.plan_sha256
        || !document(terminal.report) || !outcomes.includes(String(terminal.outcome)) || terminal.business_effect_authorized !== false
        || !object(observation) || observation.contract !== 'ontology-validation-observation/1'
        || observation.request_sha256 !== sha || observation.plan_sha256 !== v.request.plan_sha256
        || observation.outcome !== terminal.outcome || observation.business_effect_authorized !== false
        || await digest(observation) !== terminal.report.sha256
        || new TextEncoder().encode(canonical(observation)).length !== terminal.report.byte_length) fail('Retained validation report integrity failed');
      const common = ['contract', 'request_sha256', 'plan_sha256', 'business_effect_authorized', 'outcome', 'rdf_report'];
      if (observation.outcome === 'REFUSED') {
        if (!shape(observation, [...common, 'refusal_code', 'conforms']) || observation.conforms !== null || observation.rdf_report !== null
          || typeof observation.refusal_code !== 'string' || !/^[A-Z_]{1,80}$/.test(observation.refusal_code)) fail('Refusal cannot claim conformance');
      } else {
        const r = observation.result;
        if (!shape(observation, [...common, 'result']) || !document(observation.rdf_report)
          || !shape(r, ['status', 'conforms', 'data_sha256', 'shapes_sha256', 'data_graph_iris', 'shape_graph_iris', 'report_sha256', 'evaluated_shape_count', 'evaluated_focus_count', 'evaluated_constraint_count', 'violation_count', 'manifest'])
          || r.status !== observation.outcome || r.conforms !== (r.status === 'CONFORMS' ? true : r.status === 'VIOLATES' ? false : null)
          || r.data_sha256 !== plan.data.canonical_dataset.sha256 || r.shapes_sha256 !== plan.shapes.canonical_dataset.sha256
          || !same(r.data_graph_iris, plan.data.graph_iris) || !same(r.shape_graph_iris, plan.shapes.graph_iris)
          || r.report_sha256 !== observation.rdf_report.sha256 || !count(r.evaluated_shape_count, 1000)
          || !count(r.evaluated_focus_count, 5000) || !count(r.evaluated_constraint_count, 140000000) || !count(r.violation_count, 1000)
          || !object(r.manifest) || Object.keys(r.manifest).length > 64 || !Object.values(r.manifest).every(x => typeof x === 'boolean'
            || text(x, 262144) || typeof x === 'number' && Number.isSafeInteger(x))
          || !fixedManifest(r.manifest, plan.selection)
          || await digest(r.manifest) !== plan.validator_manifest_sha256) fail('Validation observation changed plan or result integrity');
        if (r.status === 'NOT_EVALUATED' ? r.evaluated_shape_count !== 0 || r.evaluated_focus_count !== 0 || r.evaluated_constraint_count !== 0
          : !r.evaluated_shape_count || !r.evaluated_focus_count || !r.evaluated_constraint_count) fail('Vacuous validation cannot claim conformance');
        if (r.status === 'CONFORMS' && r.violation_count !== 0 || r.status === 'VIOLATES' && r.violation_count === 0) fail('Validation outcome contradicts violations');
      }
    } else if (observation !== null) fail('Unbound validation observation');
    if (!Array.isArray(v.publications) || v.publications.length > 1) fail('Invalid validation publication');
    let publicationId: string | null = null;
    for (const p of v.publications) {
      if (!shape(p, ['protocol', 'workflow_id', 'generation', 'definition_sha256', 'authority', 'outputs', 'publication_id'])
        || p.protocol !== 'execution-publication/1' || p.workflow_id !== workflow || p.generation !== 0 || p.authority !== 'EXECUTION_ONLY'
        || p.definition_sha256 !== await digest(DEFINITION) || !Array.isArray(p.outputs) || p.outputs.length !== 1 || terminal === null) fail('Invalid published validation authority');
      const output = p.outputs[0];
      if (!shape(output, ['slot', 'artifact_type', 'event_id', 'sha256', 'value']) || output.slot !== 'report'
        || output.artifact_type !== 'ontology-validation-report/1' || !same(output.value, terminal)
        || output.event_id !== 'output:' + await digest([0, 'report']) || output.sha256 !== await digest(terminal)) fail('Published validation output changed retained report');
      const {publication_id: id, ...body} = p;
      if (id !== 'pub_' + await digest(body)) fail('Publication hash mismatch');
      publicationId = id as string;
    }
    if (!['INTENT_RETAINED', 'RUNNING', 'COMPLETED', 'PUBLISHED', 'CANCELLED'].includes(String(v.state))
      || (v.state === 'PUBLISHED' ? !publicationId : publicationId !== null)
      || (v.state === 'COMPLETED' || v.state === 'PUBLISHED') && terminal === null
      || (v.state === 'INTENT_RETAINED' || v.state === 'RUNNING') && terminal !== null) fail('Retained state contradicts evidence');
    if (!['RUNNING', 'COMPLETED', 'FAILED', 'CANCELED', 'TERMINATED', 'CONTINUED_AS_NEW', 'TIMED_OUT', 'UNKNOWN', 'UNOBSERVABLE'].includes(String(v.runtime_status))
      || v.execution !== undefined && (!shape(v.execution, ['state']) || !['PENDING', 'VERIFYING_INPUTS', 'VALIDATING', 'PUBLISHING_REPORT', 'COMPLETED', 'INTERRUPTED'].includes(String(v.execution.state)))) fail('Invalid runtime observation');
    signal?.throwIfAborted();
    return {workflow_id: workflow, scope: structuredClone(expected), request: captured, plan, plan_sha256: v.request.plan_sha256,
      state: v.state, terminal, report: observation, publication_id: publicationId, runtime_status: v.runtime_status,
      execution: v.execution ?? null, current_use_authorized: false, business_effect_authorized: false} as unknown as ValidationRead;
  }
  async function cancelValidation(input: ValidationCancellation, opts: RequestOptions = {}): Promise<ValidationCancellationReceipt> {
    if (!shape(input, ['request_id', 'command_id', 'reason']) || !uuid(input.request_id) || !uuid(input.command_id)
      || !text(input.reason, 2000) || input.reason.trim().length < 10) fail('An exact cancellation command and substantive reason are required', 400);
    const captured = {request_id: input.request_id.toLowerCase(), command_id: input.command_id.toLowerCase(), reason: input.reason.trim()}, signal = opts.signal;
    const v = await request('/' + captured.request_id + '/cancel', 'POST', {command_id: captured.command_id, reason: captured.reason}, signal);
    if (!shape(v, ['request_id', 'command_id', 'scope', 'cancellation', 'runtime_notified', 'business_effect_authorized'])
      || v.request_id !== captured.request_id || v.command_id !== captured.command_id
      || !shape(v.cancellation, ['workflow_id', 'state']) || v.cancellation.workflow_id !== 'ontology-validation:' + captured.request_id
      || v.cancellation.state !== 'CANCELLED'
      || typeof v.runtime_notified !== 'boolean' || v.business_effect_authorized !== false) fail('Cancellation acknowledgement changed command or scope');
    checkScope(v.scope); return v as unknown as ValidationCancellationReceipt;
  }
  return {startValidation, readValidation, cancelValidation};
}
