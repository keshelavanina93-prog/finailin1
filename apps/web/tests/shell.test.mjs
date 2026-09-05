import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../app/api/hydration/route.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const { POST } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString("base64")}`);
const request = (body = "{}", auth = true) => new Request("http://localhost/api/hydration", {
  method: "POST", body, headers: auth ? { authorization: "Bearer test-token" } : {},
});

test("proxy rejects missing credentials and oversized input", async () => {
  assert.equal((await POST(request("{}", false))).status, 401);
  assert.equal((await POST(request("x".repeat(22_000_001)))).status, 413);
});

test("proxy forwards exact body and credential and preserves upstream denial", async (t) => {
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    assert.equal(options.headers.Authorization, "Bearer test-token");
    assert.equal(options.body, '{"scope":"unchanged"}');
    assert.equal(options.cache, "no-store");
    return Response.json({ detail: "Exact scope does not match credential" }, { status: 403 });
  });
  const response = await POST(request('{"scope":"unchanged"}'));
  assert.equal(response.status, 403);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.equal((await response.json()).detail, "Exact scope does not match credential");
});

test("proxy fails closed when evidence service is unreachable", async (t) => {
  t.mock.method(globalThis, "fetch", async () => { throw new Error("connection refused"); });
  const response = await POST(request());
  assert.equal(response.status, 503);
  assert.equal((await response.json()).detail, "Evidence service unavailable");
});
