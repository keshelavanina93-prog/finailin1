import type {NextRequest} from "next/server";
import { backendBaseUrl } from "../../backend";
type Context = {params: Promise<{path: string[]}>};
async function forward(request:NextRequest,context:Context) {
 const {path}=await context.params; const route=path.join("/");
 if(!/^(map(?:\/[a-fA-F0-9-]+\/connections)?|import-proposal)$/.test(route)) return Response.json({detail:"Operations route not found"},{status:404});
 const authorization=request.headers.get("authorization");
 if(!authorization)return Response.json({detail:"Identity required"},{status:401});
 const body=request.method==="POST"?await request.text():undefined;
 if(body&&Buffer.byteLength(body)>2_000_000)return Response.json({detail:"Map source is too large; split into smaller reviewed batches"},{status:413});
 try {const upstream=await fetch(`${backendBaseUrl()}/v1/operations/${route}${request.nextUrl.search}`,{method:request.method,body,headers:{Authorization:authorization,"Content-Type":"application/json"},cache:"no-store",signal:AbortSignal.timeout(30000)});return new Response(upstream.body,{status:upstream.status,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});}catch{return Response.json({detail:"Operations service unavailable"},{status:503});}
}
export const GET=forward;
export const POST=forward;
