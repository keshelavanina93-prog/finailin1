/** Read-only native Node proof of the shared ontology client against retained evidence. */
import assert from "node:assert/strict";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createOntologyClient } from "../packages/ontology-client/dist/index.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
assert.match(root, /^D:\\/i, "Proof artifacts must remain on D:");
const args = process.argv.slice(2);
let baseUrl = "http://127.0.0.1:3062/api/ontology";
let output = path.join(root, "docs/development/evidence/nin6-ontology-client-runtime.json");
for (let i = 0; i < args.length; i += 2) {
  assert.ok(args[i + 1], `Missing value for ${args[i]}`);
  if (args[i] === "--output") output = path.resolve(args[i + 1]);
  else if (args[i] === "--base-url") baseUrl = args[i + 1];
  else throw new Error(`Unknown argument ${args[i]}`);
}
assert.match(output, /^D:\\/i, "Output must remain on D:");
assert.equal(new URL(baseUrl).hostname, "127.0.0.1", "This proof targets the local runtime");
const grants = JSON.parse(process.env.FINAI_ACCESS_TOKENS ?? "{}");
const selected = Object.entries(grants).find(([, grant]) =>
  ["ontology_admin", "ontology_propose", "ontology_read"].every((permission) =>
    grant.permissions.includes(permission)));
assert.ok(selected, "Matching local evidence reader is unavailable");
const client = createOntologyClient({ baseUrl, getToken: () => selected[0] });
const readProof = async (name) => JSON.parse(await readFile(
  path.join(root, `docs/development/evidence/${name}`), "utf8"));
const pin = (value) => ({ resource_id: value.resource_id, version_id: value.version_id });
const exactUtcTime = (value) => {
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(?:Z|\+00:00)$/.exec(value);
  assert.ok(match, "Retained proof timestamps must explicitly use UTC");
  // Normalize only zero padding, preserving every significant fractional digit.
  return `${match[1]}.${(match[2] ?? "").replace(/0+$/, "")}Z`;
};
const sameTime = (left, right) => assert.equal(exactUtcTime(left), exactUtcTime(right));

async function verify(name, kind) {
  const proof = await readProof(name);
  const retained = proof.query;
  const request = proof.requests[0];
  const options = { valid_at: request.valid_at, known_at: request.known_at, limit: 1, offset: 0 };
  const first = await client.runSavedSet(proof.prepared.object_set, options);
  assert.equal(first.total, 2);
  assert.equal(first.objects.length, 1);
  const second = await client.nextPage(first);
  assert.ok(second);
  assert.equal(second.objects.length, 1);
  assert.equal(await client.nextPage(second), null);
  const returned = await client.page(second, 0);
  assert.deepEqual(returned, first);
  assert.deepEqual([...first.objects, ...second.objects], retained.objects);
  for (const result of [first, second, returned]) {
    sameTime(result.query.valid_at, request.valid_at);
    sameTime(result.query.known_at, request.known_at);
    assert.deepEqual(result.query[kind], proof.prepared.query[kind]);
    assert.deepEqual(result.query.resource_ids, proof.prepared.query.resource_ids);
    assert.deepEqual(result[`${kind}_bindings`], retained[`${kind}_bindings`]);
  }
  const raw = await client.query({ ...proof.prepared.query, ...options, limit: 10 });
  assert.deepEqual(raw.objects, retained.objects);
  const filtered = await client.query({ ...proof.prepared.query, ...options, limit: 10,
    filters: [{ field: kind === "interface" ? "evidence" : "evidence_id",
      value: retained.objects[0].attributes.evidence_id }] });
  assert.deepEqual(filtered.objects, proof.filtered.objects);
  const traversed = await client.query({ ...proof.prepared.query, ...options, limit: 10,
    traversal: [{ kind: "reference", direction: "outgoing",
      name: kind === "interface" ? "source_record" : "source_record_id" }] });
  assert.deepEqual(traversed.objects, proof.traversal.objects);
  for (const record of traversed.objects) {
    const edge = proof.exact_provenance.find((item) =>
      item.field === "source_record_id" && item.target.resource_id === record.resource_id);
    assert.ok(edge);
    assert.deepEqual(pin(record), edge.target);
    assert.equal(record.content_hash, edge.content_hash);
  }
  const evidence = await client.query({ ...proof.prepared.query, ...options, limit: 10,
    traversal: [{ kind: "reference", direction: "outgoing",
      name: kind === "interface" ? "evidence" : "evidence_id" }] });
  assert.equal(evidence.objects.length, 2);
  for (const record of evidence.objects) {
    const edge = proof.exact_provenance.find((item) =>
      item.field === "evidence_id" && item.target.resource_id === record.resource_id);
    assert.ok(edge);
    assert.deepEqual(pin(record), edge.target);
    assert.equal(record.content_hash, edge.content_hash);
  }
  let groupOpen = null;
  if (kind === "type_group") {
    // Deliberately bound this discovery read; total is not an authentic-source count.
    groupOpen = await client.runGroup(proof.prepared.type_group, options);
    assert.ok(groupOpen.objects.length <= 1);
    assert.deepEqual(groupOpen.query.type_group, proof.prepared.type_group);
    sameTime(groupOpen.query.known_at, request.known_at);
  }
  return { source_proof: name, saved_set: proof.prepared.object_set,
    pages: [first, second], returned_first_page_equal: true, end_returns_null: true,
    query: raw, filtered, traversed, evidence, group_open: groupOpen,
    group_open_total_is_not_authentic_source_count: true };
}

const results = [];
results.push(await verify("nin6-interface-query-runtime.json", "interface"));
results.push(await verify("nin6-type-group-query-runtime.json", "type_group"));
await mkdir(path.dirname(output), { recursive: true });
await writeFile(output, `${JSON.stringify({ checked_at: new Date().toISOString(),
  runtime: "NODE_SHARED_ONTOLOGY_CLIENT", read_only: true,
  financial_authority_established: false, results }, null, 2)}\n`, "utf8");
console.log("Shared ontology client verified against retained source evidence; no mutations.");
