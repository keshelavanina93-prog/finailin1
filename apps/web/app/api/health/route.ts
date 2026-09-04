export function GET() {
  return Response.json({ status: "healthy", service: "finai-web", version: "0.1.0" });
}
