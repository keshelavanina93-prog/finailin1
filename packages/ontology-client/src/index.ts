import type { FilterExpression, ObjectSetFilter, ObjectSetQuery, ObjectSetResult } from '@finai/contracts';
import { querySchema, responseSchema, definedResponseSchema } from '@finai/contracts/ontology-wire';
import { Ajv2020 } from 'ajv/dist/2020.js';
import formatsModule from 'ajv-formats';
import type { FormatsPlugin } from 'ajv-formats';

export type { FilterExpression, ObjectSetFilter, ObjectSetQuery, ObjectSetResult } from '@finai/contracts';
export interface ExactPin { resource_id: string; version_id: string; }
export interface RequestOptions { signal?: AbortSignal; }
export interface RunOptions extends RequestOptions {
  offset?: number; limit?: number; valid_at?: string; known_at?: string;
}
export interface OntologyClientOptions {
  /** API ontology prefix, e.g. /api/ontology or https://host/v1/ontology. */
  baseUrl: string;
  getToken: () => string | Promise<string>;
  fetch?: typeof globalThis.fetch;
}
export class OntologyClientError extends Error {
  constructor(public readonly status: number, public readonly detail: string) {
    super(detail);
    this.name = 'OntologyClientError';
  }
}

const ajv = new Ajv2020({ allErrors: false, strict: false, coerceTypes: false,
  useDefaults: false, removeAdditional: false });
const addFormats = formatsModule as unknown as FormatsPlugin;
addFormats(ajv);
const validateQuery = ajv.compile(querySchema);
const validateResponse = ajv.compile(responseSchema);
const validateDefinedResponse = ajv.compile(definedResponseSchema);
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const hash = /^[a-f0-9]{64}$/;
function fail(detail: string, status = 502): never { throw new OntologyClientError(status, detail); }
const record = (v: unknown): v is Record<string, unknown> => Boolean(v) && typeof v === 'object' && !Array.isArray(v);
const same = (a: unknown, b: unknown): boolean => canonical(a) === canonical(b);
function canonical(v: unknown): string {
  if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
  if (record(v)) return '{' + Object.keys(v).filter(k => v[k] !== undefined).sort()
    .map(k => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}';
  return JSON.stringify(v) ?? 'undefined';
}
function pin(v: unknown): v is ExactPin {
  return record(v) && typeof v.resource_id === 'string' && uuid.test(v.resource_id)
    && typeof v.version_id === 'string' && uuid.test(v.version_id);
}
function equalPin(a: ExactPin, b: ExactPin): boolean {
  return a.resource_id.toLowerCase() === b.resource_id.toLowerCase()
    && a.version_id.toLowerCase() === b.version_id.toLowerCase();
}
function hashedPin(v: unknown): v is ExactPin & {content_hash: string} {
  return pin(v) && record(v) && typeof v.content_hash === 'string' && hash.test(v.content_hash);
}

/** Compare instants without discarding Python's microseconds (or longer wire fractions). */
function instant(value: unknown): string {
  if (typeof value !== 'string') return fail('A timezone-aware query timestamp is required');
  const m = /^(\d{4}-\d{2}-\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?([Zz]|[+-]\d{2}:\d{2})$/.exec(value);
  if (!m) return fail('A timezone-aware query timestamp is required');
  const milliseconds = Date.parse(`${m[1]}T${m[2]}:${m[3]}:${m[4]}Z`);
  if (!Number.isFinite(milliseconds)) return fail('Invalid query timestamp');
  const zone = m[6]!;
  const offset = zone.toUpperCase() === 'Z' ? 0
    : (Number(zone.slice(1, 3)) * 60 + Number(zone.slice(4, 6))) * 60 * (zone[0] === '-' ? -1 : 1);
  return `${BigInt(milliseconds / 1000) - BigInt(offset)}:${(m[5] ?? '').replace(/0+$/, '')}`;
}
function normalizedQuery(q: ObjectSetQuery) {
  const filters = (items: ObjectSetQuery['filters']) => (items ?? []).map(f => ({...f, operator: f.operator ?? 'eq'}));
  const expression = (group: FilterExpression): FilterExpression => ({...group,
    conditions: group.conditions.map(item => 'conditions' in item ? expression(item) : {...item, operator: item.operator ?? 'eq'})});
  return { ...q, resource_ids: q.resource_ids ?? null, search: q.search ?? '',
    offset: q.offset ?? 0, limit: q.limit ?? 50,
    filter_expression: q.filter_expression ? expression(q.filter_expression) : undefined,
    filters: filters(q.filters), traversal: (q.traversal ?? []).map(s => ({...s,
      filter_expression: s.filter_expression ? expression(s.filter_expression) : undefined,
      kind: s.kind ?? 'reference', direction: s.direction ?? 'outgoing', filters: filters(s.filters ?? [])})),
    valid_at: q.valid_at ? instant(q.valid_at) : null, known_at: q.known_at ? instant(q.known_at) : null };
}
/** Bound recursive input before schema validation or cloning can traverse it. */
function expressionLeaves(value: unknown, status: number): ObjectSetFilter[] {
  if (value === undefined || value === null) return [];
  const leaves: ObjectSetFilter[] = [];
  const pending = [{value, depth: 1}];
  while (pending.length) {
    const current = pending.pop()!;
    const group = current.value;
    if (!record(group) || !['all', 'any'].includes(String(group.op)) || current.depth > 3
      || !Array.isArray(group.conditions) || group.conditions.length < 2 || group.conditions.length > 20) {
      fail('Compound filters require two to twenty conditions and at most three group levels', status);
    }
    for (const child of group.conditions) {
      if (record(child) && ('conditions' in child || 'op' in child)) pending.push({value: child, depth: current.depth + 1});
      else leaves.push(child as ObjectSetFilter);
      if (leaves.length + pending.length > 20) fail('Ontology queries permit at most twenty predicates', status);
    }
  }
  return leaves;
}
function checkQuery(q: unknown, status = 400): asserts q is ObjectSetQuery {
  if (record(q) && Array.isArray(q.traversal) && q.traversal.length > 4) fail('Ontology queries permit at most four relationship steps', status);
  const nested = record(q) ? [...expressionLeaves(q.filter_expression, status),
    ...(Array.isArray(q.traversal) ? q.traversal.flatMap(step => record(step) ? expressionLeaves(step.filter_expression, status) : []) : [])] : [];
  if (!validateQuery(q)) fail('Invalid ontology query contract', status);
  const query = q as unknown as ObjectSetQuery;
  if (query.interface && (query.object_type !== 'ObjectInterface' || query.type_group
    || new Set(query.interface.implementations.map(p => p.resource_id.toLowerCase())).size !== query.interface.implementations.length)) {
    fail('Invalid exact interface root', status);
  }
  if (query.type_group && query.object_type !== 'ObjectTypeGroup') fail('Invalid exact type group root', status);
  const predicates = [...(query.filters ?? []), ...(query.traversal ?? []).flatMap(s => s.filters ?? []), ...nested];
  if (predicates.length > 20) {
    fail('Ontology queries permit at most twenty predicates', status);
  }
  let candidates = 0;
  for (const predicate of predicates) {
    const membership = predicate.operator === 'in' || predicate.operator === 'not_in';
    const values = Array.isArray(predicate.value) ? predicate.value : [predicate.value];
    if (membership) {
      if (!Array.isArray(predicate.value) || values.length < 1 || values.length > 100
        || values.some(v => v === null || !['string', 'number', 'boolean'].includes(typeof v))
        || new Set(values.map(v => typeof v)).size !== 1
        || new Set(values.map(canonical)).size !== values.length) {
        fail('Membership filters require one to one hundred distinct values of the same scalar kind', status);
      }
      candidates += values.length;
    } else if (Array.isArray(predicate.value)) {
      fail('Only membership filters accept a list of values', status);
    }
    if (values.some(v => typeof v === 'number' && !Number.isSafeInteger(v))) {
      fail('Numeric filter values must be exact safe integers; decimal thresholds use strings', status);
    }
  }
  if (candidates > 100) fail('Ontology root and traversal membership filters share a hundred-value limit', status);
}
function checkBindings(result: ObjectSetResult) {
  const q = result.query;
  if (q.interface) {
    const b = result.interface_bindings;
    if (!b || !hashedPin(b.interface) || !equalPin(b.interface, q.interface)
      || !record(b.fields) || !Array.isArray(b.implementations)
      || b.implementations.length !== q.interface.implementations.length
      || b.implementations.some(i => !record(i) || !hashedPin(i.implementation) || !hashedPin(i.schema)
        || typeof i.object_type !== 'string' || !record(i.fields))
      || new Set(b.implementations.map(i => i.implementation.resource_id)).size !== b.implementations.length
      || new Set(b.implementations.map(i => i.object_type)).size !== b.implementations.length
      || b.implementations.some(i => !hashedPin(i.implementation) || !hashedPin(i.schema)
        || !record(i.fields) || !q.interface!.implementations.some(p => equalPin(p, i.implementation)))) {
      fail('Interface response does not match the exact requested bindings');
    }
    if (!Array.isArray(result.interface_values)) fail('Interface compatibility evidence is missing');
  } else if (result.interface_bindings !== undefined || result.interface_values !== undefined) {
    fail('Unexpected interface response metadata');
  }
  if (q.type_group) {
    const b = result.type_group_bindings;
    if (!b || !hashedPin(b.group) || !equalPin(b.group, q.type_group) || !record(b.fields)
      || !Array.isArray(b.schemas) || b.schemas.length < 1 || b.schemas.length > 100
      || b.schemas.some(s => !record(s) || typeof s.object_type !== 'string' || !hashedPin(s.schema))
      || new Set(b.schemas.map(s => s.object_type)).size !== b.schemas.length) {
      fail('Type group response does not match the exact requested bindings');
    }
    if (!Array.isArray(result.type_group_values)) fail('Type group compatibility evidence is missing');
  } else if (result.type_group_bindings !== undefined || result.type_group_values !== undefined) {
    fail('Unexpected type group response metadata');
  }
  for (const [items, family] of [[result.interface_values, 'interface'], [result.type_group_values, 'group']] as const) {
    if (!items) continue;
    if (q.traversal.length) {
      if (items.length) fail('Traversed objects cannot be reported as root projections');
      continue;
    }
    if (items.length !== result.objects.length) fail('Root compatibility evidence is incomplete');
    const seen = new Set<string>();
    for (const value of items) {
      if (!record(value) || typeof value.object_id !== 'string' || typeof value.object_version_id !== 'string') fail('Invalid root compatibility evidence');
      const object = result.objects.find(o => o.resource_id === value.object_id && o.version_id === value.object_version_id);
      const key = `${value.object_id}:${value.object_version_id}`;
      if (!object || seen.has(key)) fail('Root compatibility evidence does not match returned objects');
      seen.add(key);
      const expected = family === 'interface'
        ? result.interface_bindings!.implementations.find(i => i.object_type === object.object_type)?.schema
        : result.type_group_bindings!.schemas.find(s => s.object_type === object.object_type)?.schema;
      if (!expected || value.schema_version_id !== expected.version_id
        || value.status !== (object.schema_version_id === expected.version_id ? 'AVAILABLE' : 'SCHEMA_CHANGED')) {
        fail('Root compatibility status does not match its exact schema');
      }
      if (family === 'interface') {
        const projected = value as unknown as Record<string, unknown>;
        const implementation = result.interface_bindings!.implementations.find(i => i.object_type === object.object_type)!;
        if (projected.implementation_resource_id !== implementation.implementation.resource_id
          || projected.implementation_version_id !== implementation.implementation.version_id
          || (value.status === 'AVAILABLE' ? !record(projected.values) : projected.values !== null)) {
          fail('Interface values do not match their exact implementation');
        }
      }
    }
  }
}
function checkResult(value: unknown, defined = false): ObjectSetResult {
  if (record(value)) checkQuery(value.query, 502);
  if (!(defined ? validateDefinedResponse(value) : validateResponse(value))) fail('Invalid ontology response contract');
  if (!record(value) || value.contract !== 'ontology-object-set/1') fail('Unsupported ontology response contract');
  const r = value as unknown as ObjectSetResult;
  instant(r.query.valid_at); instant(r.query.known_at);
  const {offset, limit} = r.query;
  if (!Number.isSafeInteger(r.total) || r.total < 0
    || r.objects.length !== Math.min(limit, Math.max(0, r.total - offset))
    || r.next_offset !== (offset + limit < r.total ? offset + limit : null)
    || !record(r.counts_by_type) || Object.values(r.counts_by_type).some(n => !Number.isSafeInteger(n) || n < 0)
    || Object.values(r.counts_by_type).reduce((n, count) => n + count, 0) !== r.total) {
    fail('Ontology response pagination or counts are inconsistent');
  }
  if (new Set(r.objects.map(o => o.resource_id + ':' + o.version_id)).size !== r.objects.length) fail('Ontology page contains duplicate object versions');
  for (const obj of r.objects) {
    if (!pin(obj) || typeof obj.content_hash !== 'string' || !hash.test(obj.content_hash)
      || (obj.schema_version_id !== null && !uuid.test(obj.schema_version_id))
      || !record(obj.attributes)) fail('Invalid exact canonical object in ontology response');
  }
  checkBindings(r);
  return r;
}
function checkFrozen(request: ObjectSetQuery, result: ObjectSetResult) {
  const expected = normalizedQuery(request);
  const actual = normalizedQuery(result.query);
  if (!request.valid_at) expected.valid_at = actual.valid_at;
  if (!request.known_at) expected.known_at = actual.known_at;
  if (!same(expected, actual)) fail('Ontology response changed the requested query or exact scope');
}
function clone<T>(value: T): T { return structuredClone(value); }

export function createOntologyClient(options: OntologyClientOptions) {
  const base = options.baseUrl.replace(/\/+$/, '');
  if (!base || base.startsWith('//') || /[?#]/.test(base)
    || !(base.startsWith('/') || /^https?:\/\//.test(base))) fail('Invalid ontology API base URL', 400);
  if (!base.startsWith('/')) {
    let parsed: URL;
    try { parsed = new URL(base); } catch { return fail('Invalid ontology API base URL', 400); }
    if (parsed.username || parsed.password) fail('Credentials cannot appear in the API URL', 400);
  }
  const transport = options.fetch ?? globalThis.fetch;
  async function request(path: string, method: 'GET' | 'POST', body: unknown, signal?: AbortSignal) {
    signal?.throwIfAborted();
    const token = await options.getToken();
    signal?.throwIfAborted();
    if (typeof token !== 'string' || !token.trim()) fail('Authentication is required', 401);
    let response: Response;
    try {
      response = await transport(base + path, {method, headers: {Authorization: `Bearer ${token}`,
        ...(method === 'POST' ? {'Content-Type': 'application/json'} : {})},
        ...(method === 'POST' ? {body: JSON.stringify(body)} : {}),
        ...(signal ? {signal} : {}), redirect: 'error', cache: 'no-store'});
    } catch {
      signal?.throwIfAborted();
      return fail('Ontology request could not reach the server', 0);
    }
    let data: unknown;
    try { data = await response.json(); } catch {
      signal?.throwIfAborted();
      return fail(response.ok ? 'Ontology server returned a non-JSON response'
        : 'Ontology request failed', response.ok ? 502 : response.status);
    }
    signal?.throwIfAborted();
    if (!response.ok) fail(record(data) && typeof data.detail === 'string'
      ? data.detail.slice(0, 1000) : 'Ontology request failed', response.status);
    return data;
  }
  async function query(input: ObjectSetQuery, opts: RequestOptions = {}): Promise<ObjectSetResult> {
    checkQuery(input);
    const captured = clone(input);
    checkQuery(captured);
    const result = checkResult(await request('/object-sets/query', 'POST', captured, opts.signal));
    checkFrozen(captured, result);
    return result;
  }
  async function run(family: 'sets' | 'groups', reference: ExactPin, opts: RunOptions = {}): Promise<ObjectSetResult> {
    if (!pin(reference)) fail('An exact definition reference is required', 400);
    const captured = clone(reference);
    opts = {...opts};
    const offset = opts.offset ?? 0, limit = opts.limit ?? 50;
    checkQuery({object_type: 'LegalEntity', offset, limit, ...(opts.valid_at ? {valid_at: opts.valid_at} : {}),
      ...(opts.known_at ? {known_at: opts.known_at} : {})});
    const params = new URLSearchParams({version: captured.version_id, offset: String(offset), limit: String(limit)});
    for (const key of ['valid_at', 'known_at'] as const) if (opts[key] !== undefined) params.set(key, opts[key]);
    const result = checkResult(await request(`/model/${family}/${captured.resource_id}/objects?${params}`, 'GET', undefined, opts.signal), true);
    if (result.definition_id?.toLowerCase() !== captured.resource_id.toLowerCase()
      || result.definition_version_id?.toLowerCase() !== captured.version_id.toLowerCase()) fail('Ontology response changed the exact definition reference');
    if (result.query.offset !== offset || result.query.limit !== limit) fail('Ontology response changed requested pagination');
    for (const key of ['valid_at', 'known_at'] as const) if (opts[key] && instant(opts[key]) !== instant(result.query[key])) fail('Ontology response changed requested temporal scope');
    if (family === 'groups') {
      const root = result.query.interface ?? result.query.type_group;
      if (!root || !equalPin(root, captured)) fail('Group execution changed the exact root reference');
    }
    return result;
  }
  async function page(previous: ObjectSetResult, offset: number, opts: RequestOptions = {}): Promise<ObjectSetResult> {
    const captured = clone(previous);
    checkResult(captured, captured.definition_id !== undefined || captured.definition_version_id !== undefined);
    const result = await query({...captured.query, offset}, opts);
    if (!same(captured.interface_bindings, result.interface_bindings)
      || !same(captured.type_group_bindings, result.type_group_bindings)
      || !same(captured.filter_schema_versions ?? [], result.filter_schema_versions ?? [])
      || !same(captured.traversal_schema_versions ?? [], result.traversal_schema_versions ?? [])
      || result.total !== captured.total || !same(result.counts_by_type, captured.counts_by_type)) {
      fail('Frozen ontology page changed its semantic pins or total population');
    }
    return {...result, ...(captured.definition_id !== undefined ? {
      definition_id: captured.definition_id, definition_version_id: captured.definition_version_id!
    } : {})};
  }
  return {
    query,
    runSavedSet: (reference: ExactPin, opts?: RunOptions) => run('sets', reference, opts),
    runGroup: (reference: ExactPin, opts?: RunOptions) => run('groups', reference, opts),
    page,
    async nextPage(previous: ObjectSetResult, opts: RequestOptions = {}): Promise<ObjectSetResult | null> {
      const captured = clone(previous);
      checkResult(captured, captured.definition_id !== undefined || captured.definition_version_id !== undefined);
      if (captured.next_offset === null) return null;
      return page(captured, captured.next_offset, opts);
    },
  };
}

export * from './external-ontology.js';
export * from './ontology-validation.js';
