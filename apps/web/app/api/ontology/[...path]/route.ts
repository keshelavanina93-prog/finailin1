import type { NextRequest } from "next/server";

type Context = { params: Promise<{ path: string[] }> };
async function forward(request: NextRequest, context: Context) {
  const { path } = await context.params;
  const route = path.join("/");
  const documents = /^source-documents(?:\/doc_[a-f0-9]{64}\/(?:content|preview|(?:companies|accounts|facts|dimensions|corporate|licence)\/(?:inspect|proposal)|facts\/reconcile|dimensions\/query|accounting-context\/(?:inspect|observations|scope-proposal|binding-proposal|company-binding-proposal)))?$/.test(route)
    || /^source-documents\/ir_[a-f0-9]{64}\/accounting-context\/(?:inspect|observations|scope-proposal|binding-proposal|company-binding-proposal)$/.test(route);
  const lifecycle = /^lifecycle\/(?:requests(?:\/[a-fA-F0-9-]+\/review)?|versions\/[a-fA-F0-9-]+|consumptions\/[a-fA-F0-9-]+(?:\/status)?|consume)$/.test(route);
  const eventTime = /^event-time\/(?:events|streams\/[a-fA-F0-9-]+\/replay)$/.test(route);
  const model = /^model\/(?:fact-runs\/fcr_[a-f0-9]{64}(?:\/authority)?|definitions(?:\/(?:preview|contracts|[a-fA-F0-9-]+))?|proposals\/[a-fA-F0-9-]+\/decision|(?:sets|groups)\/[a-fA-F0-9-]+\/objects|bindings\/[a-fA-F0-9-]+\/proposal|facts\/[a-fA-F0-9-]+\/(?:aggregate(?:\/guarded)?|reconcile)|sources\/ir_[a-f0-9]{64}\/accounts(?:\/proposal)?|derived\/query)$/.test(route);
  if (route !== "history-search" && !/^operator\/trace\/[a-fA-F0-9-]+$/.test(route) && !/^operations(?:\/(?:licence-notices|bindings|opa_[a-f0-9]{64}(?:\/resume)?))?$/.test(route) && !documents && !/^regulation\/(monitors(?:\/rgm_[a-f0-9]{64}(?:\/control)?)?|rules|proposals|impacts(?:\/fcr_[a-f0-9]{64})|assessments(?:\/fcr_[a-f0-9]{64})?|sources(?:\/(?:capture|proposals|compare|inspect|impact))?)$/.test(route) && !model && !lifecycle && !eventTime && route !== "company-context" && route !== "object-sets/query" && !/^(catalog|context(?:\/(?:accounts|source-accounts))?|graph|aliases|reference-proposal|rollback-proposal|resources(?:\/[a-fA-F0-9-]+(?:\/graph)?)?|resolve\/[a-fA-F0-9-]+|proposals(?:\/[a-fA-F0-9-]+(?:\/(?:decision|promotion-check))?)?)$/.test(route)) {
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
    const result = await fetch(`${process.env.FINAI_API_URL ?? "http://127.0.0.1:8000"}/v1/ontology/${route}${request.nextUrl.search}`, {
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
