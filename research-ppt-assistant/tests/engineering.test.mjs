import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { assertSupportedNodeVersion, nodeMajor } from "../server/runtime.mjs";

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(TEST_DIR, "..");

function runVersionCheck(root) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ["./scripts/check-version.mjs", root], {
      cwd: ROOT,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

async function writeVersionFixture(root, versions) {
  await fs.mkdir(path.join(root, ".codex-plugin"), { recursive: true });
  await fs.mkdir(path.join(root, "server"), { recursive: true });
  await fs.writeFile(path.join(root, "package.json"), JSON.stringify({ version: versions.package }));
  await fs.writeFile(path.join(root, ".codex-plugin", "plugin.json"), JSON.stringify({ name: "fixture", version: versions.manifest }));
  await fs.writeFile(path.join(root, "server", "mcp-server.mjs"), `const SERVER_INFO = { name: "fixture", version: "${versions.mcp}" };\n`);
}

test("runtime policy rejects Node 18 and accepts supported majors", () => {
  assert.equal(nodeMajor("v24.19.0"), 24);
  assert.throws(() => assertSupportedNodeVersion("18.19.1"), /Node\.js >=22 is required/);
  assert.equal(assertSupportedNodeVersion("22.0.0"), 22);
  assert.equal(assertSupportedNodeVersion("24.19.0"), 24);
});

test("version audit accepts a cachebuster when base versions match", async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "rpa-version-match-"));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  await writeVersionFixture(root, { package: "0.2.3", manifest: "0.2.3+codex.local-test", mcp: "0.2.3" });
  const result = await runVersionCheck(root);
  assert.equal(result.code, 0, result.stderr);
  assert.match(result.stdout, /Version check passed: 0\.2\.3/);
});

test("version audit fails on version drift", async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "rpa-version-drift-"));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  await writeVersionFixture(root, { package: "0.2.3", manifest: "0.2.2", mcp: "0.2.3" });
  const result = await runVersionCheck(root);
  assert.equal(result.code, 1);
  assert.match(result.stderr, /Version mismatch/);
});
