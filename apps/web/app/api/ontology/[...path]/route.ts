import type { NextRequest } from "next/server";

type Context = { params: Promise<{ path: string[] }> };
async function forward(request: NextRequest, context: Context) {
  const { path } = await context.params;
  const route = path.join("/");
  if (!/^(catalog|context(?:\/(?:accounts|source-accounts))?|graph|aliases|reference-proposal|resources(?:\/[a-fA-F0-9-]+(?:\/graph)?)?|resolve\/[a-fA-F0-9-]+|proposals(?:\/[a-fA-F0-9-]+(?:\/decision)?)?)$/.test(route)) {
    return Response.json({ detail: "Ontology route not found" }, { status: 404 });
  }
  const authorization = request.headers.get("authorization");
  if (!authorization) return Response.json({ detail: "Identity required" }, { status: 401 });
  const body = request.method === "POST" ? await request.text() : undefined;
  if (body && Buffer.byteLength(body) > 1_000_000) return Response.json({ detail: "Proposal too large" }, { status: 413 });
  try {
    const result = await fetch(`${process.env.FINAI_API_URL ?? "http://127.0.0.1:8000"}/v1/ontology/${route}${request.nextUrl.search}`, {
      method: request.method, body, headers: { Authorization: authorization, "Content-Type": "application/json" },
      cache: "no-store", signal: AbortSignal.timeout(30_000),
    });
    return new Response(result.body, { status: result.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return Response.json({ detail: "Ontology service unavailable" }, { status: 503 }); }
}
export const GET = forward;
export const POST = forward;
