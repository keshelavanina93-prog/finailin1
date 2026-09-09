import { backendBaseUrl } from "../../backend";

type Context = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, context: Context) {
  const { path } = await context.params;
  const route = path.join("/");
  if (route !== "readiness" && route !== "evidence-context") {
    return Response.json({ detail: "Diagnostic route not found" }, { status: 404 });
  }
  const authorization = request.headers.get("authorization");
  if (!authorization) return Response.json({ detail: "Access token required" }, { status: 401 });
  try {
    const upstream = await fetch(`${backendBaseUrl()}/v1/diagnostics/${route}${new URL(request.url).search}`, {
      headers: { Authorization: authorization },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ detail: "Diagnostic service unavailable" }, { status: 503 });
  }
}
