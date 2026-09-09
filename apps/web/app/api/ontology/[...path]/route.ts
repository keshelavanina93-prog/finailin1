import type { NextRequest } from "next/server";
import { backendBaseUrl } from "../../backend";

type Context = { params: Promise<{ path: string[] }> };
async function forward(request: NextRequest, context: Context) {
  const { path } = await context.params;
  const route = path.join("/");
  const documents = /^source-documents(?:\/doc_[a-f0-9]{64}\/(?:content|preview|(?:companies|accounts|facts|dimensions|corporate|licence)\/(?:inspect|proposal)|facts\/reconcile|dimensions\/query|accounting-context\/(?:inspect|observations|account-observations|scope-proposal|binding-proposal|company-binding-proposal|setup-proposal)))?$/.test(route)
    || /^source-documents\/ir_[a-f0-9]{64}\/accounting-context\/(?:inspect|observations|account-observations|scope-proposal|binding-proposal|company-binding-proposal|setup-proposal)$/.test(route);
  const lifecycle = /^lifecycle\/(?:requests(?:\/[a-fA-F0-9-]+\/review)?|versions\/[a-fA-F0-9-]+|consumptions\/[a-fA-F0-9-]+(?:\/status)?|consume)$/.test(route);
  const eventTime = /^event-time\/(?:events|streams\/[a-fA-F0-9-]+\/replay)$/.test(route);
  const certification = /^certifications\/(?:evaluations|receipts\/[a-fA-F0-9-]+)$/.test(route);
  const transformations = /^transformations(?:\/runs(?:\/[a-fA-F0-9-]+(?:\/(?:control|publication-review))?)?)?$/.test(route);
  const functions = /^functions(?:\/(?:implementation|invocations(?:\/[a-fA-F0-9-]+)?))?$/.test(route);
  const runtimeObservations = request.method === "GET" && /^runtime-observations(?:\/[a-fA-F0-9-]+)?$/.test(route);
  const finance = (request.method === "GET" && /^finance\/(?:catalog|domain|dimensions\/policies|constructions|contracts|functions|actions|runs\/fcr_[a-f0-9]{64}(?:\/export)?)$/.test(route))
    || (request.method === "POST" && /^finance\/(?:catalog\/proposals|candidates\/(?:preview|proposals)|dimensions\/validate|classify|execute|journal-trial-balance)$/.test(route));
  const companyJournals = request.method === "GET" && /^company-journals(?:\/[a-fA-F0-9-]+)?$/.test(route);
  const journalDispositions=request.method==="GET"&&/^company-journals\/production\/attempts\/[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}(?:\/dispositions)?$/.test(route);
  const metricObservations=(request.method==="GET"&&route==="metrics")||(request.method==="POST"&&route==="metrics/observations")||(request.method==="GET"&&/^metrics\/observations\/fcr_[a-f0-9]{64}$/.test(route));
  const analysisProjection=request.method==="POST"&&(route==="analysis/project"||route==="company-home"||route==="company-changes"||route==="company-journals/reconciliation/projection"||route==="company-journals/reconciliation/metrics");
  const companyCondition=request.method==="GET"&&route==="company-condition";
  const sourceExceptions=(request.method==="POST"&&route==="source-exceptions")||(request.method==="GET"&&/^source-exceptions\/fcr_[a-f0-9]{64}$/.test(route));
  const investigationActions=request.method==="POST"&&(route==="operations/investigations"||route==="operations/investigation-resolutions");
  const sourceJournalReconciliation=request.method==="GET"&&/^company-journals\/reconciliation\/source\/[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}$/.test(route);
  const sourceAdoption=request.method==="POST"&&/^source-adoption\/(?:(?:families|transitions)\/(?:inspect|proposal)|successor)$/.test(route);
  const periodControl = (request.method === "GET" && route === "period-control") || (request.method === "POST" && route === "period-control/proposal");
  const accountDimensionPolicy = (request.method === "GET" && route === "account-dimension-policy") || (request.method === "POST" && route === "account-dimension-policy/proposal");
  const retention = /^retention\/(?:inspect|history|policies|evaluations|receipts\/[a-fA-F0-9-]+)$/.test(route);
  const model = /^model\/(?:fact-runs\/fcr_[a-f0-9]{64}(?:\/authority)?|definitions(?:\/(?:preview|contracts|[a-fA-F0-9-]+))?|proposals\/[a-fA-F0-9-]+\/decision|(?:sets|groups)\/[a-fA-F0-9-]+\/objects|bindings\/[a-fA-F0-9-]+\/proposal|facts\/[a-fA-F0-9-]+\/(?:aggregate(?:\/guarded)?|reconcile)|sources\/ir_[a-f0-9]{64}\/accounts(?:\/proposal)?|derived\/query)$/.test(route);
  if (route !== "proposal-queue" && route !== "history-search" && route !== "install/preflight" && !/^operator\/(?:trace|resources)\/[a-fA-F0-9-]+$/.test(route) && !/^operations(?:\/(?:licence-notices|bindings|opa_[a-f0-9]{64}(?:\/resume)?))?$/.test(route) && !documents && !/^regulation\/(monitors(?:\/rgm_[a-f0-9]{64}(?:\/control)?)?|rules|proposals|impacts(?:\/fcr_[a-f0-9]{64})|assessments(?:\/fcr_[a-f0-9]{64})?|sources(?:\/(?:capture|proposals|compare|inspect|impact))?)$/.test(route) && !model && !finance && !lifecycle && !eventTime && !certification && !retention && !functions && !transformations && !runtimeObservations && !companyJournals && !journalDispositions && !periodControl && !accountDimensionPolicy && !sourceAdoption && !analysisProjection && !metricObservations && !sourceExceptions && !investigationActions && !sourceJournalReconciliation && !companyCondition && route !== "company-context" && route !== "object-sets/query" && !/^(catalog|context(?:\/(?:accounts|source-accounts))?|graph|aliases|reference-proposal|rollback-proposal|resources(?:\/[a-fA-F0-9-]+(?:\/graph)?)?|resolve\/[a-fA-F0-9-]+|proposals(?:\/[a-fA-F0-9-]+(?:\/(?:decision|promotion-check))?)?)$/.test(route)) {
    return Response.json({ detail: "Ontology route not found" }, { status: 404 });
  }
  const authorization = request.headers.get("authorization");
  if (!authorization) return Response.json({ detail: "Identity required" }, { status: 401 });
  const binary = route === "source-documents";
  const bodyLimit = binary ? 32_000_000 : route === "context/source-accounts" ? 22_000_000 : 1_000_000;
  let body: Uint8Array<ArrayBuffer> | undefined;
  if (request.method === "POST" && request.body) {
    const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
    try {
      while (true) {
        const next = await reader.read(); if (next.done) break;
        size += next.value.byteLength;
        if (size > bodyLimit) { await reader.cancel(); return Response.json({detail:"Request too large"},{status:413}); }
        chunks.push(next.value);
      }
    } finally { reader.releaseLock(); }
    body = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  }
  try {
    const result = await fetch(`${backendBaseUrl()}/v1/ontology/${route}${request.nextUrl.search}`, {
      method: request.method, body, headers: { Authorization: authorization, "Content-Type": binary ? "application/octet-stream" : "application/json" },
      cache: "no-store", signal: AbortSignal.timeout(30_000),
    });
    const headers = new Headers({"Content-Type":result.headers.get("content-type") ?? "application/json", "Cache-Control":"no-store"});
    for (const name of ["content-disposition", "x-source-sha256"]) { const value=result.headers.get(name); if(value)headers.set(name,value); }
    return new Response(result.body, { status: result.status, headers });
  } catch { return Response.json({ detail: "Ontology service unavailable" }, { status: 503 }); }
}
export const GET = forward;
export const POST = forward;
