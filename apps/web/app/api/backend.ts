// Keep direct web development aligned with the packaged local API runtime.
// Deployments and alternate local ports still use their explicit environment URL.
export function backendBaseUrl(): string {
  return process.env.FINAI_API_URL ?? "http://127.0.0.1:8061";
}
