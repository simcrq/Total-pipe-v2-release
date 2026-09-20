#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { assertSupportedNodeVersion } from "../server/runtime.mjs";

assertSupportedNodeVersion();

const COVERAGE_GATES = Object.freeze({
  overall: { lines: 90, branches: 80 },
  "benchmark.mjs": { branches: 90 },
  "layout-audit.mjs": { branches: 90 },
});

const result = spawnSync(process.execPath, ["--test", "--experimental-test-coverage"], {
  cwd: process.cwd(),
  encoding: "utf8",
  maxBuffer: 20 * 1024 * 1024,
});
process.stdout.write(result.stdout ?? "");
process.stderr.write(result.stderr ?? "");
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);

const rows = new Map();
for (const rawLine of String(result.stdout ?? "").split(/\r?\n/u)) {
  // 行首前缀取决于 reporter：TTY 下是 spec reporter 的 `ℹ `，非 TTY（CI、管道重定向）
  // 下是 TAP 的 `# `。两者都要剥掉，否则覆盖率表在 CI 里一行都解析不出来，
  // 门禁会以 "did not contain the all-files summary" 的形式误报失败。
  const line = rawLine.replace(/\u001B\[[0-9;]*m/gu, "").replace(/^\s*(?:#|ℹ)\s*/u, "");
  const match = line.match(/^(.+?)\s+\|\s+([0-9.]+)\s+\|\s+([0-9.]+)\s+\|\s+([0-9.]+)/u);
  if (!match) continue;
  rows.set(match[1].trim(), {
    lines: Number(match[2]),
    branches: Number(match[3]),
    functions: Number(match[4]),
  });
}

const failures = [];
const overall = rows.get("all files");
if (!overall) failures.push("Coverage report did not contain the all-files summary.");
for (const [name, thresholds] of Object.entries(COVERAGE_GATES)) {
  const actual = name === "overall" ? overall : rows.get(name);
  if (!actual) {
    failures.push(`Coverage report did not contain ${name}.`);
    continue;
  }
  for (const [metric, minimum] of Object.entries(thresholds)) {
    if (actual[metric] < minimum) failures.push(`${name} ${metric} coverage ${actual[metric]}% is below ${minimum}%.`);
  }
}

if (failures.length) {
  throw new Error(`Coverage gate failed:\n- ${failures.join("\n- ")}`);
}
process.stdout.write(`Coverage gate passed: overall lines ${overall.lines}%, branches ${overall.branches}%; benchmark/layout-audit branches >= 90%.\n`);
