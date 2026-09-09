import type {ExactPin, ObjectSetQuery, OntologyClientOptions, RequestOptions} from './index.js';

export type FinanceJsonObject = Record<string, unknown>;
export interface FinanceScope {tenant_id: string; legal_entity_id: string; period: string; currency: string;}
export interface FinanceClientOptions extends OntologyClientOptions {expectedScope: FinanceScope;}
export type FinanceConstructionId = 'g8.candidate.coa-406' | 'g8.candidate.seg-entities';
export type FinanceDecision = 'APPROVED' | 'REJECTED' | null;
export interface FinanceDefinition {
  resource_id: string; object_type: string; identity_key: string; display_name: string;
  status: 'INSTALLED' | 'CHANGE_REQUIRED' | 'NOT_INSTALLED'; version_id: string | null;
  expected_attributes: FinanceJsonObject;
}
export interface FinanceCatalog {
  catalog_id: 'g8.ontology.finance.v1'; catalog_sha256: string;
  manifest: FinanceJsonObject; diagnostics: FinanceJsonObject[]; definitions: FinanceDefinition[];
  phases: {kind: string; pending: number}[]; ready: boolean; company_facts_published: false;
}
export interface FinanceDimensionPolicy {
  account_family_pattern: string; required_dimensions: string[]; observed_slot_order: string[];
  evidence_state: 'OBSERVED_LABEL_ONLY' | 'RULE_EVIDENCED' | 'UNKNOWN'; slot_note: string;
}
export interface FinanceDimensionValidationRequest {
  account_code: string; bindings?: Record<string, string | null>;
  evidence_state?: 'OBSERVED_LABEL_ONLY' | 'RULE_EVIDENCED' | 'UNKNOWN';
}
export interface FinanceConstruction {
  construction_id: FinanceConstructionId; status: 'CANDIDATE'; row_count: number;
  construction_content_sha256: string; candidate_file_sha256: string; source_sha256: string | null;
  authority: 'CANDIDATE_ONLY'; rows: FinanceJsonObject[];
}
export interface FinanceCatalogProposalRequest {
  catalog_sha256: string; phase: string; offset?: number; limit?: number;
  valid_from: string; rationale: string; request_id: string;
}
export interface FinanceCandidateRequest {
  construction_id: FinanceConstructionId; document_id?: string | null; evidence?: ExactPin | null;
  company?: ExactPin | null; chart?: ExactPin | null; valid_from: string;
  offset?: number; limit?: number; rationale: string;
}
export interface FinanceCandidatePreview {
  construction_id: FinanceConstructionId; construction_content_sha256: string; scope: FinanceScope;
  total_rows: number; offset: number; limit: number; next_offset: number | null;
  rows: FinanceJsonObject[]; blockers: string[]; proposal_id: string;
  proposal: FinanceJsonObject | null; mutation_count: number; reused_count: number;
  can_submit: boolean; authority: 'CANDIDATE_ONLY'; review_required: true;
}
export interface FinanceCandidateSubmission {
  proposal_id: string; decision: FinanceDecision; review_required: boolean;
  created: boolean; proposal: FinanceJsonObject;
}
export interface FinanceClassificationRequest {policy: ExactPin; document_id: string; offset?: number; limit?: number;}
export interface FinanceExecutionRequest {
  operation: 'trial_balance' | 'closing_as_of' | 'ytd_flow' | 'reconcile_parent' | 'project';
  contract: ExactPin; query: ObjectSetQuery; group_by?: string[]; starts_on?: string | null;
  as_of: string; account_field?: string; side_field?: string | null; projection?: ExactPin | null;
}
export interface FinanceJournalRequest {
  company: ExactPin; ledger: ExactPin; book: ExactPin; period: ExactPin;
  snapshot_at: string; starts_on: string; as_of: string; max_journals?: number;
}
/** Dynamic calculation details remain unknown until their specific contract is validated. */
export interface FinanceRetainedRun extends FinanceJsonObject {
  run_id: string; scope: FinanceScope; calculation_runtime: 'finance-catalog/1' | 'finance-classification/1';
  read_permissions: string[]; operation: string;
}
export interface FinanceClassificationRun extends FinanceRetainedRun {
  operation: 'classify_fact'; state: 'CANDIDATE_ONLY'; policy: ExactPin;
  source: {document_id: string; sha256: string; filename: string | null};
  rows: FinanceJsonObject[]; offset: number; next_offset: number | null;
  accounting_use_authorized: false;
}
export interface FinanceCalculationRun extends FinanceRetainedRun {
  contract: 'finance-calculation/1'; state: string; groups: FinanceJsonObject[];
  current_use_authorized: false; business_effect_authorized: false; financial_certification: null;
  source_versions: ExactPin[];
}
export class FinanceOntologyClientError extends Error {
  constructor(public readonly status: number, message: string) {super(message); this.name = 'FinanceOntologyClientError';}
}

const obj = (v: unknown): v is FinanceJsonObject => v !== null && typeof v === 'object' && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === 'string' && v.length > 0;
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === 'string');
const uuid = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(v);
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const runId = (v: unknown): v is string => typeof v === 'string' && /^fcr_[a-f0-9]{64}$/.test(v);
const documentId = (v: unknown): v is string => typeof v === 'string' && /^doc_[a-f0-9]{64}$/.test(v);
const integer = (v: unknown, max = 100000): v is number => Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= max;
const pin = (v: unknown): v is ExactPin => obj(v) && uuid(v.resource_id) && uuid(v.version_id)
  && (!('content_hash' in v) || hash(v.content_hash));
const samePin = (v: unknown, p: ExactPin) => pin(v) && v.resource_id.toLowerCase() === p.resource_id.toLowerCase()
  && v.version_id.toLowerCase() === p.version_id.toLowerCase();
const construction = (v: unknown): v is FinanceConstructionId => ['g8.candidate.coa-406', 'g8.candidate.seg-entities'].includes(String(v));
const decision = (v: unknown): v is FinanceDecision => v === null || v === 'APPROVED' || v === 'REJECTED';
const objects = (v: unknown): v is FinanceJsonObject[] => Array.isArray(v) && v.every(obj);
const decimal = (v: unknown) => typeof v === 'string' && /^-?\d+(?:\.\d+)?$/.test(v);
function fail(message: string, status = 502): never {throw new FinanceOntologyClientError(status, message);}
function scope(v: unknown): v is FinanceScope {
  return obj(v) && uuid(v.tenant_id) && str(v.legal_entity_id) && v.legal_entity_id.length <= 128
    && typeof v.period === 'string' && /^\d{4}-(0[1-9]|1[0-2])$/.test(v.period)
    && typeof v.currency === 'string' && /^[A-Z]{3}$/.test(v.currency);
}
function date(v: unknown): v is string {
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return false;
  const n = Date.parse(v + 'T00:00:00Z');
  return Number.isFinite(n) && new Date(n).toISOString().slice(0, 10) === v;
}
function instant(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  const m = /^(\d{4}-\d{2}-\d{2})T([01]\d|2[0-3]):([0-5]\d):([0-5]\d)(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(v);
  if (!m || !date(m[1])) return null;
  const epoch = Date.parse(`${m[1]}T${m[2]}:${m[3]}:${m[4]}${m[6]}`);
  return Number.isFinite(epoch) ? `${epoch / 1000}:${(m[5] ?? '').replace(/0+$/, '')}` : null;
}
function exactScope(value: unknown, expected: FinanceScope): asserts value is FinanceScope {
  if (!scope(value) || value.tenant_id.toLowerCase() !== expected.tenant_id.toLowerCase()
    || value.legal_entity_id !== expected.legal_entity_id || value.period !== expected.period
    || value.currency !== expected.currency) fail('Finance response belongs to another exact scope');
}
function requestObject(input: unknown, keys: string[]): asserts input is FinanceJsonObject {
  if (!obj(input) || Object.keys(input).some(k => !keys.includes(k))) fail('Invalid finance request fields', 400);
}
function proposal(value: unknown, entity: string): asserts value is FinanceJsonObject {
  if (!obj(value) || !uuid(value.proposal_id) || value.access_entity !== entity || !objects(value.mutations)
    || value.mutations.length < 1 || value.mutations.length > 100
    || value.mutations.some(row => !uuid(row.resource_id) || !str(row.object_type) || !str(row.identity_key)
      || !obj(row.attributes) || instant(row.valid_from) === null
      || (row.expected_version_id !== null && row.expected_version_id !== undefined && !uuid(row.expected_version_id))))
    fail('Invalid finance review proposal');
}
function retained(value: unknown, expected: FinanceScope): asserts value is FinanceRetainedRun {
  if (!obj(value) || !runId(value.run_id) || !strings(value.read_permissions) || !str(value.operation)
    || !['finance-catalog/1', 'finance-classification/1'].includes(String(value.calculation_runtime)))
    fail('Invalid retained finance run');
  exactScope(value.scope, expected);
}
function classificationRun(value: FinanceRetainedRun, request?: FinanceClassificationRequest): asserts value is FinanceClassificationRun {
  if (value.calculation_runtime !== 'finance-classification/1' || value.operation !== 'classify_fact'
    || value.state !== 'CANDIDATE_ONLY' || value.accounting_use_authorized !== false || !pin(value.policy)
    || !obj(value.source) || !documentId(value.source.document_id) || !hash(value.source.sha256)
    || !(value.source.filename === null || typeof value.source.filename === 'string')
    || !objects(value.rows) || !integer(value.offset) || !(value.next_offset === null || integer(value.next_offset)))
    fail('Invalid retained classification contract');
  if (request && (!samePin(value.policy, request.policy) || value.source.document_id !== request.document_id
    || value.offset !== (request.offset ?? 0) || value.rows.length > (request.limit ?? 25)))
    fail('Classification response changed its requested source, policy or page');
  for (const row of value.rows) {
    const c = row.classification;
    if (!integer(row.source_row) || !obj(row.values) || !obj(c)
      || !['CANDIDATE', 'UNAVAILABLE'].includes(String(c.state)) || c.epistemic !== 'INFERRED'
      || c.accounting_use_authorized !== false || c.canonical_posting_created !== false
      || !(c.account === null || pin(c.account)) || !strings(c.missing)
      || !(c.amount === null || decimal(c.amount)) || !obj(c.dimensions)) fail('Invalid classified row evidence');
  }
}
function calculationRun(value: FinanceRetainedRun): asserts value is FinanceCalculationRun {
  if (value.calculation_runtime !== 'finance-catalog/1' || value.contract !== 'finance-calculation/1'
    || !['DERIVED', 'INCOMPLETE', 'UNAVAILABLE', 'MATCHED', 'UNRECONCILED'].includes(String(value.state))
    || value.current_use_authorized !== false || value.business_effect_authorized !== false
    || value.financial_certification !== null || !objects(value.groups)
    || !Array.isArray(value.source_versions) || !value.source_versions.every(pin))
    fail('Invalid finance calculation evidence');
  for (const group of value.groups) {
    if (!obj(group.dimensions) || !Array.isArray(group.inputs) || !group.inputs.every(pin)
      || !strings(group.missing) || !['DERIVED', 'INCOMPLETE', 'UNAVAILABLE'].includes(String(group.state))
      || ['value', 'observed_value', 'debit_turnover', 'credit_turnover', 'opening_balance', 'closing_balance']
        .some(key => group[key] !== null && group[key] !== undefined && !decimal(group[key])))
      fail('Finance amounts and lineage must use exact typed values');
  }
}

/** Review proposals and retained evidence; this client never approves company authority. */
export function createFinanceOntologyClient(options: FinanceClientOptions) {
  if (!scope(options.expectedScope)) fail('An expected finance scope is required', 400);
  const expected = structuredClone(options.expectedScope), base = options.baseUrl.replace(/\/+$/, '');
  if (!base || /[?#\s\\]/.test(base) || base.startsWith('//') || !(base.startsWith('/') || /^https?:\/\//.test(base)))
    fail('Invalid ontology API base URL', 400);
  if (!base.startsWith('/')) {const url = new URL(base); if (url.username || url.password) fail('Invalid ontology API base URL', 400);}
  const transport = options.fetch ?? globalThis.fetch;
  async function send(path: string, body: unknown, opts: RequestOptions): Promise<unknown> {
    opts.signal?.throwIfAborted();
    const token = await options.getToken();
    opts.signal?.throwIfAborted();
    if (typeof token !== 'string' || !token.trim()) fail('Authentication is required', 401);
    let response: Response;
    try {response = await transport(`${base}/finance${path}`, {method: body === undefined ? 'GET' : 'POST',
      headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
      ...(body === undefined ? {} : {body: JSON.stringify(body)}), ...(opts.signal ? {signal: opts.signal} : {}),
      credentials: 'omit', redirect: 'error'});}
    catch (error) {if (opts.signal?.aborted) throw error; return fail('Finance API transport failed', 503);}
    if (!response.ok) fail('Finance API request failed', response.status);
    try {return await response.json();} catch {return fail('Finance API returned invalid JSON');}
  }
  function candidate(input: FinanceCandidateRequest): FinanceCandidateRequest {
    requestObject(input, ['construction_id', 'document_id', 'evidence', 'company', 'chart', 'valid_from', 'offset', 'limit', 'rationale']);
    if (!construction(input.construction_id) || instant(input.valid_from) === null || !str(input.rationale)
      || input.rationale.trim().length < 10 || input.rationale.length > 1500
      || !integer(input.offset ?? 0) || !integer(input.limit ?? 25, 25) || (input.limit ?? 25) < 1
      || (input.document_id != null && !documentId(input.document_id))
      || [input.evidence, input.company, input.chart].some(p => p != null && !pin(p))) fail('Invalid finance candidate selection', 400);
    return structuredClone(input);
  }
  async function catalog(opts: RequestOptions = {}): Promise<FinanceCatalog> {
    const value = await send('/catalog', undefined, opts);
    if (!obj(value) || value.catalog_id !== 'g8.ontology.finance.v1' || !hash(value.catalog_sha256)
      || !obj(value.manifest) || !objects(value.diagnostics) || !objects(value.definitions) || !objects(value.phases)
      || typeof value.ready !== 'boolean' || value.company_facts_published !== false) fail('Invalid finance catalog response');
    for (const row of value.definitions) if (!uuid(row.resource_id) || !str(row.object_type) || !str(row.identity_key)
      || !str(row.display_name) || !obj(row.expected_attributes) || !(row.version_id === null || uuid(row.version_id))
      || !['INSTALLED', 'CHANGE_REQUIRED', 'NOT_INSTALLED'].includes(String(row.status))
      || (row.status === 'INSTALLED' && row.version_id === null)) fail('Invalid finance definition version');
    if (value.ready !== value.definitions.every(row => row.status === 'INSTALLED')
      || value.phases.some(p => !str(p.kind) || !integer(p.pending))) fail('Inconsistent finance installation status');
    return value as unknown as FinanceCatalog;
  }
  return {
    catalog,
    async domain(opts: RequestOptions = {}): Promise<FinanceJsonObject> {
      const value = await send('/domain', undefined, opts);
      if (!obj(value) || value.domain_id !== 'g8.finance.domain.v1' || !Array.isArray(value.capabilities)
        || !Array.isArray(value.modules) || !Array.isArray(value.account_dimension_policies))
        fail('Invalid finance domain contract');
      return value;
    },
    async dimensionPolicies(opts: RequestOptions = {}): Promise<FinanceDimensionPolicy[]> {
      const value = await send('/dimensions/policies', undefined, opts);
      if (!obj(value) || value.contract !== 'finance-dimension-policy/1' || value.authority !== 'OBSERVED_LABELS_ONLY'
        || !Array.isArray(value.policies) || value.policies.some(row => !obj(row)
          || !str(row.account_family_pattern) || !strings(row.required_dimensions)
          || !strings(row.observed_slot_order) || !['OBSERVED_LABEL_ONLY', 'RULE_EVIDENCED', 'UNKNOWN'].includes(String(row.evidence_state))
          || !str(row.slot_note))) fail('Invalid finance dimension policy contract');
      return value.policies as unknown as FinanceDimensionPolicy[];
    },
    async validateDimensions(input: FinanceDimensionValidationRequest, opts: RequestOptions = {}): Promise<FinanceJsonObject> {
      requestObject(input, ['account_code', 'bindings', 'evidence_state']);
      if (!str(input.account_code) || input.account_code.length > 128 || (input.bindings !== undefined && !obj(input.bindings)))
        fail('Invalid finance dimension validation request', 400);
      const value = await send('/dimensions/validate', structuredClone(input), opts);
      if (!obj(value) || value.contract !== 'finance-dimension-validation/1' || value.authority !== 'CANDIDATE_ONLY'
        || !str(value.account_code) || !['UNKNOWN', 'OBSERVED_LABEL_ONLY', 'RULE_EVIDENCED', 'INCOMPLETE'].includes(String(value.state))
        || !Array.isArray(value.required_dimensions) || !Array.isArray(value.missing_dimensions) || !obj(value.bindings))
        fail('Invalid finance dimension validation response');
      return value;
    },
    async constructions(opts: RequestOptions = {}): Promise<FinanceConstruction[]> {
      const value = await send('/constructions', undefined, opts);
      if (!objects(value) || value.some(row => !construction(row.construction_id) || row.status !== 'CANDIDATE'
        || row.authority !== 'CANDIDATE_ONLY' || !integer(row.row_count) || !objects(row.rows)
        || row.rows.length !== row.row_count || !hash(row.construction_content_sha256)
        || !hash(row.candidate_file_sha256) || !(row.source_sha256 === null || hash(row.source_sha256))))
        fail('Invalid retained candidate inventory');
      return value as unknown as FinanceConstruction[];
    },
    async proposeCatalog(input: FinanceCatalogProposalRequest, opts: RequestOptions = {}): Promise<FinanceJsonObject> {
      requestObject(input, ['catalog_sha256', 'phase', 'offset', 'limit', 'valid_from', 'rationale', 'request_id']);
      if (!hash(input.catalog_sha256) || !str(input.phase) || !uuid(input.request_id) || instant(input.valid_from) === null
        || !str(input.rationale) || input.rationale.trim().length < 10 || !integer(input.offset ?? 0, 10000)
        || !integer(input.limit ?? 40, 75) || (input.limit ?? 40) < 1) fail('Invalid catalog publication request', 400);
      const value = await send('/catalog/proposals', structuredClone(input), opts);
      if (!obj(value) || !decision(value.decision)) fail('Invalid catalog proposal response');
      proposal(value.proposal, '__PLATFORM__');
      return value;
    },
    async previewCandidates(input: FinanceCandidateRequest, opts: RequestOptions = {}): Promise<FinanceCandidatePreview> {
      const request = candidate(input), value = await send('/candidates/preview', request, opts);
      if (!obj(value) || value.construction_id !== request.construction_id || !hash(value.construction_content_sha256)
        || !integer(value.total_rows) || value.offset !== (request.offset ?? 0) || value.limit !== (request.limit ?? 25)
        || !(value.next_offset === null || integer(value.next_offset)) || !objects(value.rows) || !strings(value.blockers)
        || !uuid(value.proposal_id) || !integer(value.mutation_count, 100) || !integer(value.reused_count, 100)
        || typeof value.can_submit !== 'boolean' || value.authority !== 'CANDIDATE_ONLY' || value.review_required !== true)
        fail('Invalid candidate preview');
      exactScope(value.scope, expected);
      if (value.proposal !== null) {proposal(value.proposal, expected.legal_entity_id);
        if (value.proposal.proposal_id !== value.proposal_id) fail('Candidate proposal identity mismatch');}
      if (value.can_submit !== (value.proposal !== null) || value.can_submit && value.blockers.length > 0)
        fail('Candidate submission state conflicts with its evidence');
      return value as unknown as FinanceCandidatePreview;
    },
    async proposeCandidates(input: FinanceCandidateRequest, opts: RequestOptions = {}): Promise<FinanceCandidateSubmission> {
      const value = await send('/candidates/proposals', candidate(input), opts);
      if (!obj(value) || !uuid(value.proposal_id) || !decision(value.decision) || typeof value.created !== 'boolean'
        || value.review_required !== (value.decision === null)) fail('Invalid candidate proposal response');
      proposal(value.proposal, expected.legal_entity_id);
      if (value.proposal.proposal_id !== value.proposal_id) fail('Candidate proposal identity mismatch');
      return value as unknown as FinanceCandidateSubmission;
    },
    async classify(input: FinanceClassificationRequest, opts: RequestOptions = {}): Promise<FinanceClassificationRun> {
      requestObject(input, ['policy', 'document_id', 'offset', 'limit']);
      if (!pin(input.policy) || !documentId(input.document_id) || !integer(input.offset ?? 0, 30000)
        || !integer(input.limit ?? 25, 100) || (input.limit ?? 25) < 1) fail('Invalid classification request', 400);
      const request = structuredClone(input), value = await send('/classify', request, opts);
      retained(value, expected); classificationRun(value, request); return value;
    },
    async execute(input: FinanceExecutionRequest, opts: RequestOptions = {}): Promise<FinanceCalculationRun> {
      requestObject(input, ['operation', 'contract', 'query', 'group_by', 'starts_on', 'as_of', 'account_field', 'side_field', 'projection']);
      if (!['trial_balance', 'closing_as_of', 'ytd_flow', 'reconcile_parent', 'project'].includes(input.operation)
        || !pin(input.contract) || !obj(input.query) || !str(input.query.object_type) || !date(input.as_of)
        || instant(input.query.valid_at) === null || instant(input.query.known_at) === null
        || (input.query.offset ?? 0) !== 0 || (input.query.traversal?.length ?? 0) > 0 || input.query.interface || input.query.type_group
        || (input.starts_on != null && (!date(input.starts_on) || input.starts_on > input.as_of))
        || ['trial_balance', 'ytd_flow', 'project'].includes(input.operation) && !date(input.starts_on)
        || (input.operation === 'project' ? !pin(input.projection) : input.projection != null)
        || (input.group_by !== undefined && (!strings(input.group_by) || input.group_by.length > 20)))
        fail('Invalid exact finance execution request', 400);
      const request = structuredClone(input), value = await send('/execute', request, opts);
      retained(value, expected); calculationRun(value);
      if (value.operation !== request.operation || !samePin(value.fact_contract, request.contract) || !pin(value.schema)
        || (request.projection ? !samePin(value.projection, request.projection) : value.projection !== null)
        || value.as_of !== request.as_of || value.starts_on !== (request.starts_on ?? null))
        fail('Finance result changed the selected contract, projection or period');
      return value;
    },
    async journalTrialBalance(input: FinanceJournalRequest, opts: RequestOptions = {}): Promise<FinanceCalculationRun> {
      requestObject(input, ['company', 'ledger', 'book', 'period', 'snapshot_at', 'starts_on', 'as_of', 'max_journals']);
      if (![input.company, input.ledger, input.book, input.period].every(pin) || instant(input.snapshot_at) === null
        || !date(input.starts_on) || !date(input.as_of) || input.starts_on > input.as_of
        || !integer(input.max_journals ?? 200, 200) || (input.max_journals ?? 200) < 1) fail('Invalid canonical journal selection', 400);
      const request = structuredClone(input), value = await send('/journal-trial-balance', request, opts);
      retained(value, expected); calculationRun(value);
      if (value.implementation_id !== 'finance.canonical-journal-turnover/1' || !obj(value.request)
        || !samePin(value.request.company, request.company) || !samePin(value.request.ledger, request.ledger)
        || !samePin(value.request.book, request.book) || !samePin(value.request.period, request.period)
        || instant(value.request.snapshot_at) !== instant(request.snapshot_at)
        || value.starts_on !== request.starts_on || value.as_of !== request.as_of) fail('Journal response changed its exact selection');
      return value;
    },
    async readRun(id: string, opts: RequestOptions = {}): Promise<FinanceRetainedRun> {
      if (!runId(id)) fail('Invalid retained finance run identity', 400);
      const value = await send('/runs/' + id, undefined, opts);
      retained(value, expected);
      if (value.run_id !== id) fail('Retained finance run identity mismatch');
      if (value.calculation_runtime === 'finance-classification/1') classificationRun(value);
      else calculationRun(value);
      return value;
    },
    async contracts(opts: RequestOptions = {}): Promise<FinanceJsonObject> {
      const value = await send('/contracts', undefined, opts);
      if (!obj(value)) fail('Invalid finance schema inventory');
      return value;
    },
  };
}
