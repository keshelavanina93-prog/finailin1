import type { NextRequest } from "next/server";

type Context = { params: Promise<{ path: string[] }> };

async function forward(request: NextRequest, context: Context) {
  const { path } = await context.params;
  // Fixed upstream host and explicitly allowed routes: never turn this into an arbitrary proxy.
  const route = path.join("/");
  if (!/^(session|summary|intake|objects(?:\/[a-zA-Z0-9_:.-]+)?|constructions\/[a-zA-Z0-9_-]+(?:\/(decision|source|export))?)$/.test(route)) {
    return Response.json({ detail: "Workspace route not found" }, { status: 404 });
  }
  const authorization = request.headers.get("authorization");
  if (!authorization) return Response.json({ detail: "Sign in to continue" }, { status: 401 });
  const body = request.method === "POST" ? await request.text() : undefined;
  if (body && Buffer.byteLength(body) > 8192) {
    return Response.json({ detail: "Review request too large" }, { status: 413 });
  }
  try {
    const result = await fetch(`${process.env.FINAI_API_URL ?? "http://127.0.0.1:8000"}/v1/workspace/${route}${request.nextUrl.search}`, {
      method: request.method, body, headers: { Authorization: authorization, "Content-Type": "application/json" },
      cache: "no-store", signal: AbortSignal.timeout(30_000),
    });
    const headers = new Headers({ "Cache-Control": "no-store" });
    for (const name of ["Content-Type", "Content-Disposition", "X-Content-SHA256"]) {
      const value = result.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(result.body, { status: result.status, headers });
  } catch {
    return Response.json({ detail: "Workspace service unavailable" }, { status: 503 });
  }
}

export const GET = forward;
export const POST = forward;
