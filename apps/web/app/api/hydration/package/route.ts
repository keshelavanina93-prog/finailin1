import { backendBaseUrl } from "../../backend";

export async function POST(request: Request) {
  const authorization = request.headers.get("authorization");
  if (!authorization) return Response.json({ detail: "Access token required" }, { status: 401 });
  const body = await request.text();
  if (Buffer.byteLength(body) > 22_000_000) {
    return Response.json({ detail: "Request too large" }, { status: 413 });
  }
  try {
    const upstream = await fetch(`${backendBaseUrl()}/v1/hydration/trial-balance-package`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: authorization },
      body,
      cache: "no-store",
      // Twelve BIFF workbooks need more than the single-file 30 second budget.
      signal: AbortSignal.timeout(5 * 60_000),
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ detail: "Historical intake service unavailable" }, { status: 503 });
  }
}

