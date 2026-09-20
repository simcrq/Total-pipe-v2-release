import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { runFigurePlacementGolden } from "../server/figure-placement-benchmark.mjs";

const dataset = JSON.parse(await fs.readFile(new URL("../benchmarks/figure-placement-golden.json", import.meta.url), "utf8"));

async function makeFixture(t, source) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "rpa-golden-"));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const sourcePath = path.join(directory, "source.pptx");
  const fixturePath = path.join(directory, "fixture.json");
  const expected = Buffer.from("known source bytes for integrity testing");
  if (source !== undefined) await fs.writeFile(sourcePath, source);
  await fs.writeFile(fixturePath, JSON.stringify({
    ...dataset,
    source_deck: sourcePath,
    source_deck_sha256: crypto.createHash("sha256").update(expected).digest("hex"),
  }));
  return fixturePath;
}

test("fixture-only golden pass explicitly excludes unavailable source verification", async (t) => {
  const fixture_path = await makeFixture(t);
  const result = await runFigurePlacementGolden({ fixture_path });
  assert.equal(result.status, "passed");
  assert.equal(result.validation_mode, "fixtures");
  assert.equal(result.fixture_status, "passed");
  assert.equal(result.source_integrity.status, "not_evaluable");
  assert.deepEqual(result.verified_checks, ["fixture_regressions"]);
});

test("source-backed golden fails when source bytes are unavailable", async (t) => {
  const fixture_path = await makeFixture(t);
  const result = await runFigurePlacementGolden({ fixture_path, require_source: true });
  assert.equal(result.status, "failed");
  assert.equal(result.validation_mode, "source_backed");
  assert.equal(result.fixture_status, "passed");
  assert.equal(result.source_integrity.status, "not_evaluable");
});

test("source-backed golden records verified hash without claiming render validation", async (t) => {
  const fixture_path = await makeFixture(t, "known source bytes for integrity testing");
  const result = await runFigurePlacementGolden({ fixture_path, require_source: true });
  assert.equal(result.status, "passed");
  assert.equal(result.source_integrity.status, "passed");
  assert.deepEqual(result.verified_checks, ["fixture_regressions", "source_deck_sha256"]);
});

test("a known source hash mismatch fails even in fixture mode", async (t) => {
  const fixture_path = await makeFixture(t, "different source bytes");
  const result = await runFigurePlacementGolden({ fixture_path });
  assert.equal(result.status, "failed");
  assert.equal(result.fixture_status, "passed");
  assert.equal(result.source_integrity.status, "failed");
  assert.deepEqual(result.verified_checks, ["fixture_regressions"]);
});

test("golden CLI source requirement fails closed and rejects unknown flags", () => {
  const script = fileURLToPath(new URL("../scripts/run-figure-placement-golden.mjs", import.meta.url));
  const strict = spawnSync(process.execPath, [script, "--require-source"], { encoding: "utf8" });
  const result = JSON.parse(strict.stdout);
  assert.equal(result.validation_mode, "source_backed");
  assert.equal(strict.status, result.status === "passed" ? 0 : 1);
  if (result.source_integrity.status !== "passed") assert.equal(result.status, "failed");
  const unknown = spawnSync(process.execPath, [script, "--requre-source"], { encoding: "utf8" });
  assert.equal(unknown.status, 1);
  assert.match(unknown.stderr, /Unknown argument/);
});

test("golden rejects ambiguous source requirements and empty fixture success", async (t) => {
  await assert.rejects(runFigurePlacementGolden({ require_source: "false" }), /must be a boolean/);
  const fixture_path = await makeFixture(t);
  const empty = JSON.parse(await fs.readFile(fixture_path, "utf8"));
  empty.fixtures = [];
  await fs.writeFile(fixture_path, JSON.stringify(empty));
  const result = await runFigurePlacementGolden({ fixture_path });
  assert.equal(result.fixture_status, "failed");
  assert.equal(result.status, "failed");
  assert.deepEqual(result.verified_checks, []);
});
