import type {OntologyClientOptions, RequestOptions} from './index.js';

export interface ExternalOntologyScope {tenant_id: string; legal_entity_id: string; period: string; currency: string;}
export interface ExternalOntologyPin {resource_id: string; version_id: string; content_hash: string;}
export interface ExternalDocument {document_id: string; sha256: string; byte_length: number;}
export interface ExternalReleaseRequest {
  release: ExternalOntologyPin;
  mode?: 'CURRENT_RELEASE' | 'HISTORICAL_INSPECTION';
  known_at?: string | null;
}
export interface ExternalSubjectRequest extends ExternalReleaseRequest {subject_iri: string; limit?: number;}
export interface ExternalModule {
  source: ExternalOntologyPin; artifact_iri: string; document: ExternalDocument;
  format: 'TURTLE' | 'RDF_XML'; owned_namespaces: string[]; permitted_import_iris: string[];
  source_url: string; license: string; retrieved_at: string;
}
export interface ExternalReleaseDefinition {
  contract: 'external-ontology-release/1';
  request: {source: ExternalOntologyPin; release_label: string;
    publication_status: 'PRODUCTION' | 'DEVELOPMENT'; modules: ExternalModule[]};
  canonical_dataset: ExternalDocument; import_report: ExternalDocument; request_sha256: string;
  engine_manifest: Record<string, string | number | boolean>;
  interpretation: 'EXTERNAL_MEANING_ONLY'; reasoning: 'NONE'; constraint_validation: 'NOT_PERFORMED';
}
export interface ExternalInspectionContext {
  release: ExternalOntologyPin; scope: ExternalOntologyScope;
  mode: 'CURRENT_RELEASE' | 'HISTORICAL_INSPECTION'; known_at: string | null;
  current_use_authorized: false; business_effect_authorized: false;
}
export interface ExternalReleaseInspection extends ExternalInspectionContext {definition: ExternalReleaseDefinition;}
export interface ExternalIndexScope {
  tenant_id: string; legal_entity_id: string; release_id: string; release_version_id: string;
  release_content_hash: string; dataset_sha256: string;
}
export interface ExternalIndexManifest {
  scope: ExternalIndexScope; index_key: string; engine_version: '0.5.11';
  quad_count: number; graph_iris: string[]; derived_only: true;
}
export interface ExternalRdfQuad {subject: string; predicate: string; object: string; graph_iri: string;}
export interface ExternalSubjectInspection {
  scope: ExternalIndexScope; subject_iri: string; quads: ExternalRdfQuad[]; truncated: boolean; derived_only: true;
}
export interface ExternalProjection<T> extends ExternalInspectionContext {
  projection: T; reasoning: 'NONE'; constraint_validation: 'NOT_PERFORMED';
}
export interface ExternalOntologyClientOptions extends OntologyClientOptions {expectedScope: ExternalOntologyScope;}
export class ExternalOntologyClientError extends Error {
  constructor(public readonly status: number, message: string) {super(message); this.name = 'ExternalOntologyClientError';}
}

type Obj = Record<string, unknown>;
const record = (v: unknown): v is Obj => v !== null && typeof v === 'object' && !Array.isArray(v);
const shape = (v: unknown, keys: string[]): v is Obj => record(v)
  && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const uuid = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(v);
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const text = (v: unknown, max: number): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
const integer = (v: unknown, max: number) => Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= max;
const pin = (v: unknown): v is Obj => shape(v, ['resource_id', 'version_id', 'content_hash'])
  && uuid(v.resource_id) && uuid(v.version_id) && hash(v.content_hash);
const sameId = (a: unknown, b: string) => typeof a === 'string' && a.toLowerCase() === b.toLowerCase();
const samePin = (v: unknown, p: ExternalOntologyPin) => pin(v) && sameId(v.resource_id, p.resource_id)
  && sameId(v.version_id, p.version_id) && v.content_hash === p.content_hash;
const scope = (v: unknown): v is Obj => shape(v, ['tenant_id', 'legal_entity_id', 'period', 'currency'])
  && uuid(v.tenant_id) && text(v.legal_entity_id, 128) && typeof v.period === 'string'
  && /^\d{4}-(0[1-9]|1[0-2])$/.test(v.period) && typeof v.currency === 'string' && /^[A-Z]{3}$/.test(v.currency);
const doc = (v: unknown): v is Obj => shape(v, ['document_id', 'sha256', 'byte_length'])
  && typeof v.document_id === 'string' && /^doc_[a-f0-9]{64}$/.test(v.document_id)
  && hash(v.sha256) && integer(v.byte_length, 32_000_000) && (v.byte_length as number) > 0;
function iri(v: unknown): v is string {
  if (!text(v, 2048) || /[\s\x00-\x1f<>"{}|^`\\]/.test(v)) return false;
  try {const u = new URL(v); return ['http:', 'https:', 'urn:'].includes(u.protocol)
    && !u.username && !u.password && (u.protocol === 'urn:' ? Boolean(u.pathname) : Boolean(u.hostname));}
  catch {return false;}
}
const rdfIri = (v: string) => /^[A-Za-z][A-Za-z0-9+.-]*:[^\s\x00-\x1f<>"{}|^`\\]+$/.test(v);
function rdfTerm(v: unknown): v is string {
  if (!text(v, 262144)) return false;
  if (v.startsWith('<') && v.endsWith('>')) return rdfIri(v.slice(1, -1));
  if (/^_:[A-Za-z0-9_](?:[A-Za-z0-9._-]*[A-Za-z0-9_-])?$/.test(v)) return true;
  if (!/^"(?:[^"\\\x00-\x1f]|\\(?:["'\\bfnrt]|u[a-fA-F0-9]{4}|U[a-fA-F0-9]{8}))*"(?:@[a-zA-Z]+(?:-[a-zA-Z0-9]+)*|\^\^<[^<>]*>)?$/.test(v)) return false;
  const datatype = /\^\^<([^<>]*)>$/.exec(v);
  return !datatype || rdfIri(datatype[1]!);
}
function instant(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(v);
  if (!m || m[1]!.startsWith('0000')) return null;
  const day = Date.parse(m[1] + 'T00:00:00Z'), second = Date.parse(`${m[1]}T${m[2]}${m[4]}`);
  if (!Number.isFinite(day) || !Number.isFinite(second) || new Date(day).toISOString().slice(0, 10) !== m[1]
    || !/^([01]\d|2[0-3]):[0-5]\d:[0-5]\d$/.test(m[2]!)) return null;
  return `${second / 1000}:${(m[3] ?? '').replace(/0+$/, '')}`;
}
const iris = (v: unknown, max: number, min = 0): v is string[] => Array.isArray(v)
  && v.length >= min && v.length <= max && v.every(iri) && new Set(v).size === v.length;
const moduleKeys = ['source', 'artifact_iri', 'document', 'format', 'owned_namespaces',
  'permitted_import_iris', 'source_url', 'license', 'retrieved_at'];
function module(v: unknown): v is Obj {
  return shape(v, moduleKeys) && pin(v.source) && iri(v.artifact_iri) && doc(v.document)
    && ['TURTLE', 'RDF_XML'].includes(String(v.format)) && iris(v.owned_namespaces, 32, 1)
    && iris(v.permitted_import_iris, 16) && iri(v.source_url) && text(v.license, 4000)
    && Boolean(v.license.trim()) && instant(v.retrieved_at) !== null;
}
function definition(v: unknown): v is Obj {
  if (!shape(v, ['contract', 'request', 'canonical_dataset', 'import_report', 'request_sha256',
    'engine_manifest', 'interpretation', 'reasoning', 'constraint_validation'])
    || v.contract !== 'external-ontology-release/1' || !doc(v.canonical_dataset) || !doc(v.import_report)
    || !hash(v.request_sha256) || v.interpretation !== 'EXTERNAL_MEANING_ONLY' || v.reasoning !== 'NONE'
    || v.constraint_validation !== 'NOT_PERFORMED' || !record(v.engine_manifest)
    || Object.keys(v.engine_manifest).length > 40 || !Object.values(v.engine_manifest).every(x =>
      typeof x === 'boolean' || typeof x === 'string' && x.length <= 4000 || typeof x === 'number' && Number.isSafeInteger(x))) return false;
  const r = v.request;
  return shape(r, ['source', 'release_label', 'publication_status', 'modules']) && pin(r.source)
    && text(r.release_label, 128) && Boolean(r.release_label.trim())
    && ['PRODUCTION', 'DEVELOPMENT'].includes(String(r.publication_status))
    && Array.isArray(r.modules) && r.modules.length > 0 && r.modules.length <= 16 && r.modules.every(module)
    && new Set(r.modules.map(m => m.artifact_iri)).size === r.modules.length
    && r.modules.some(m => samePin(m.source, r.source as unknown as ExternalOntologyPin));
}
function fail(message: string, status = 502): never {throw new ExternalOntologyClientError(status, message);}
const contextKeys = ['release', 'scope', 'mode', 'known_at', 'current_use_authorized', 'business_effect_authorized'];

/** Only retained, pinned release inspection; this client has no SPARQL or path interface. */
export function createExternalOntologyClient(options: ExternalOntologyClientOptions) {
  if (!scope(options.expectedScope)) fail('An exact expected scope is required', 400);
  const expected = structuredClone(options.expectedScope);
  const base = options.baseUrl.replace(/\/+$/, '');
  if (!base || /[?#\s\\]/.test(base) || base.startsWith('//') || !(base.startsWith('/') || /^https?:\/\//.test(base)))
    fail('Invalid ontology API base URL', 400);
  if (!base.startsWith('/')) {
    try {const u = new URL(base); if (u.username || u.password) fail('Invalid ontology API base URL', 400);}
    catch {fail('Invalid ontology API base URL', 400);}
  }
  const transport = options.fetch ?? globalThis.fetch;
  function capture(input: ExternalReleaseRequest, term: boolean): ExternalSubjectRequest {
    if (!record(input) || Object.keys(input).some(k => !(term
      ? ['release', 'mode', 'known_at', 'subject_iri', 'limit'] : ['release', 'mode', 'known_at']).includes(k))
      || !pin(input.release)) fail('An exact release request is required', 400);
    const mode = input.mode ?? 'CURRENT_RELEASE', known = input.known_at ?? null;
    if (input.mode === null || !['CURRENT_RELEASE', 'HISTORICAL_INSPECTION'].includes(mode)
      || (mode === 'HISTORICAL_INSPECTION' ? instant(known) === null : known !== null))
      fail('Historical inspection requires an exact knowledge time; current inspection forbids it', 400);
    if (term && (!iri(input.subject_iri) || input.limit === null || !integer(input.limit ?? 50, 100) || ((input.limit ?? 50) as number) < 1))
      fail('A bounded RDF subject inspection is required', 400);
    return structuredClone({...input, mode, known_at: known, ...(term ? {limit: input.limit ?? 50} : {})}) as ExternalSubjectRequest;
  }
  async function post(path: string, input: ExternalReleaseRequest, signal?: AbortSignal): Promise<unknown> {
    signal?.throwIfAborted();
    const token = await options.getToken();
    signal?.throwIfAborted();
    if (typeof token !== 'string' || !token.trim()) fail('Authentication is required', 401);
    let response: Response;
    try {response = await transport(`${base}/external${path}`, {method: 'POST',
      headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'}, body: JSON.stringify(input),
      cache: 'no-store', redirect: 'error', ...(signal ? {signal} : {})});}
    catch {signal?.throwIfAborted(); return fail('Ontology request could not reach the server', 0);}
    let data: unknown;
    try {data = await response.json();} catch {signal?.throwIfAborted(); return fail('Ontology response was not JSON', response.ok ? 502 : response.status);}
    signal?.throwIfAborted();
    if (!response.ok) fail('External ontology request failed', response.status);
    return data;
  }
  function context(v: Obj, input: ExternalReleaseRequest) {
    const s = v.scope;
    if (!samePin(v.release, input.release) || !scope(s) || !sameId(s.tenant_id, expected.tenant_id)
      || s.legal_entity_id !== expected.legal_entity_id || s.period !== expected.period || s.currency !== expected.currency
      || v.mode !== input.mode || v.current_use_authorized !== false || v.business_effect_authorized !== false
      || (input.mode === 'HISTORICAL_INSPECTION'
        ? instant(v.known_at) === null || instant(v.known_at) !== instant(input.known_at) : v.known_at !== null))
      fail('Response does not match the requested release, scope and inspection context');
  }
  async function release(input: ExternalReleaseRequest, signal?: AbortSignal): Promise<ExternalReleaseInspection> {
    const v = await post('/releases/inspect', input, signal);
    if (!shape(v, [...contextKeys, 'definition']) || !definition(v.definition)) fail('Invalid retained release response');
    context(v, input);
    return v as unknown as ExternalReleaseInspection;
  }
  function indexScope(v: unknown, input: ExternalReleaseRequest, dataset: string) {
    return shape(v, ['tenant_id', 'legal_entity_id', 'release_id', 'release_version_id', 'release_content_hash', 'dataset_sha256'])
      && sameId(v.tenant_id, expected.tenant_id) && v.legal_entity_id === expected.legal_entity_id
      && sameId(v.release_id, input.release.resource_id) && sameId(v.release_version_id, input.release.version_id)
      && v.release_content_hash === input.release.content_hash && v.dataset_sha256 === dataset;
  }
  async function projection(input: ExternalSubjectRequest, rebuild: boolean, signal?: AbortSignal) {
    const metadata = await release({release: input.release, mode: input.mode!, known_at: input.known_at!}, signal);
    const v = await post(rebuild ? '/index/rebuild' : '/terms/inspect', input, signal);
    if (!shape(v, [...contextKeys, 'projection', 'reasoning', 'constraint_validation'])
      || v.reasoning !== 'NONE' || v.constraint_validation !== 'NOT_PERFORMED' || !record(v.projection))
      fail('Invalid disposable ontology projection');
    context(v, input);
    const p = v.projection;
    if (!indexScope(p.scope, input, metadata.definition.canonical_dataset.sha256) || p.derived_only !== true)
      fail('Index projection does not match the retained dataset');
    const graphs = metadata.definition.request.modules.map(m => m.artifact_iri);
    if (rebuild) {
      if (!shape(p, ['scope', 'index_key', 'engine_version', 'quad_count', 'graph_iris', 'derived_only'])
        || !hash(p.index_key) || p.engine_version !== '0.5.11' || !integer(p.quad_count, 250_000) || p.quad_count === 0
        || !iris(p.graph_iris, 64, 1) || p.graph_iris.length > (p.quad_count as number)
        || p.graph_iris.some(g => !graphs.includes(g))) fail('Invalid index manifest');
    } else {
      if (!shape(p, ['scope', 'subject_iri', 'quads', 'truncated', 'derived_only']) || p.subject_iri !== input.subject_iri
        || typeof p.truncated !== 'boolean' || !Array.isArray(p.quads) || p.quads.length > input.limit!
        || p.quads.some(q => !shape(q, ['subject', 'predicate', 'object', 'graph_iri'])
          || q.subject !== `<${input.subject_iri}>` || !text(q.predicate, 2050) || !q.predicate.startsWith('<')
          || !q.predicate.endsWith('>') || !rdfIri(q.predicate.slice(1, -1)) || !rdfTerm(q.object)
          || !iri(q.graph_iri) || !graphs.includes(q.graph_iri))
        || new Set(p.quads.map(q => JSON.stringify(q))).size !== p.quads.length
        || new TextEncoder().encode(JSON.stringify(p)).length > 1_048_576) fail('Invalid bounded RDF subject response');
    }
    return v;
  }
  return {
    async inspectRelease(input: ExternalReleaseRequest, opts: RequestOptions = {}): Promise<ExternalReleaseInspection> {
      return await release(capture(input, false), opts.signal);
    },
    async rebuildIndex(input: ExternalReleaseRequest, opts: RequestOptions = {}): Promise<ExternalProjection<ExternalIndexManifest>> {
      return await projection(capture(input, false), true, opts.signal) as unknown as ExternalProjection<ExternalIndexManifest>;
    },
    async inspectSubject(input: ExternalSubjectRequest, opts: RequestOptions = {}): Promise<ExternalProjection<ExternalSubjectInspection>> {
      return await projection(capture(input, true), false, opts.signal) as unknown as ExternalProjection<ExternalSubjectInspection>;
    },
  };
}
