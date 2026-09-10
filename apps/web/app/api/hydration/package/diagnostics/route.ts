import { backendBaseUrl } from "../../../backend";

export async function POST(request: Request) {
  const authorization = request.headers.get("authorization");
  if (!authorization) return Response.json({ detail: "Access token required" }, { status: 401 });
  const body = await request.text();
  if (Buffer.byteLength(body) > 2_000_000) {
    return Response.json({ detail: "Diagnostic request too large" }, { status: 413 });
  }
  try {
    const upstream = await fetch(`${backendBaseUrl()}/v1/hydration/trial-balance-package/diagnostics`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: authorization },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ detail: "Diagnostic service unavailable" }, { status: 503 });
  }
}
