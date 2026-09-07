import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

// Emit beside the package so normal bare-package resolution is retained, while
// temporary files stay in the checkout (and therefore on D: on Windows).
const root = fileURLToPath(new URL("../.finai/test-modules/", import.meta.url));
await mkdir(root, { recursive: true });
const output = await mkdtemp(resolve(root, "esm-"));
const modules = new Map();

async function compile(filename) {
  if (modules.has(filename)) return modules.get(filename);
  const destination = resolve(output, `${modules.size}.mjs`);
  modules.set(filename, destination);
  const source = await readFile(filename, "utf8");
  const emitted = ts.transpileModule(source, {
    fileName: filename,
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const parsed = ts.createSourceFile(filename, emitted, ts.ScriptTarget.ES2022, true, ts.ScriptKind.JS);
  const replacements = [];
  for (const statement of parsed.statements) {
    if (!ts.isImportDeclaration(statement) && !ts.isExportDeclaration(statement)) continue;
    const specifier = statement.moduleSpecifier;
    if (!specifier || !ts.isStringLiteral(specifier) || !specifier.text.startsWith(".")) continue;
    const resolved = ts.resolveModuleName(specifier.text, filename, {
      moduleResolution: ts.ModuleResolutionKind.Bundler,
      allowJs: true,
    }, ts.sys).resolvedModule;
    if (!resolved) throw new Error(`Cannot resolve ${specifier.text} from ${filename}`);
    const dependency = await compile(resolve(dirname(filename), resolved.resolvedFileName));
    replacements.push([specifier.getStart(parsed), specifier.end, JSON.stringify(pathToFileURL(dependency).href)]);
  }
  let compiled = emitted;
  for (const [start, end, replacement] of replacements.reverse()) {
    compiled = compiled.slice(0, start) + replacement + compiled.slice(end);
  }
  await writeFile(destination, compiled);
  return destination;
}

export async function loadTypeScript(url) {
  return import(pathToFileURL(await compile(fileURLToPath(url))).href);
}
