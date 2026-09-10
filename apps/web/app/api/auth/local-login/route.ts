import { backendBaseUrl } from "../../backend";

export async function POST(request: Request) {
  if (process.env.NEXT_PUBLIC_FINAI_LOCAL_LOGIN !== "true") {
    return Response.json({ detail: "Local development login is disabled" }, { status: 404 });
  }
  try {
    const result = await fetch(`${backendBaseUrl()}/v1/auth/local-login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    return new Response(result.body, {
      status: result.status,
      headers: { "Cache-Control": "no-store", "Content-Type": "application/json" },
    });
  } catch {
    return Response.json({ detail: "Local authentication service unavailable" }, { status: 503 });
  }
}
