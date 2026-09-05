export async function GET(request: Request) {
  const authorization = request.headers.get("authorization");
  if (!authorization) return Response.json({detail:"Identity required"},{status:401});
  const base = process.env.FINAI_API_URL ?? "http://127.0.0.1:8000";
  try {
    const session = await fetch(`${base}/v1/workspace/session`, {headers:{Authorization:authorization},cache:"no-store",signal:AbortSignal.timeout(5000)});
    if (!session.ok) return Response.json({detail:"Session unavailable"},{status:session.status});
    const response = await fetch(`${base}/ready`,{cache:"no-store",signal:AbortSignal.timeout(8000)});
    return new Response(response.body,{status:response.status,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});
  } catch { return Response.json({detail:"Service readiness unavailable"},{status:503}); }
}
