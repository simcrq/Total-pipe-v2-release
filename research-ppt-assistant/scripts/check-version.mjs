#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const pluginRoot = path.resolve(process.argv[2] ?? path.join(SCRIPT_DIR, ".."));

async function readJson(relativePath) {
  return JSON.parse(await fs.readFile(path.join(pluginRoot, relativePath), "utf8"));
}

try {
  const [packageJson, pluginJson, serverSource] = await Promise.all([
    readJson("package.json"),
    readJson(path.join(".codex-plugin", "plugin.json")),
    fs.readFile(path.join(pluginRoot, "server", "mcp-server.mjs"), "utf8"),
  ]);
  const serverMatch = serverSource.match(/const\s+SERVER_INFO\s*=\s*\{[^}]*\bversion:\s*"([^"]+)"/s);
  if (!serverMatch) throw new Error("Unable to read MCP SERVER_INFO version");

  const versions = {
    package: String(packageJson.version ?? ""),
    manifest: String(pluginJson.version ?? "").split("+")[0],
    mcp: serverMatch[1],
  };
  if (!versions.package || new Set(Object.values(versions)).size !== 1) {
    throw new Error(`Version mismatch: package=${versions.package}, manifest=${versions.manifest}, mcp=${versions.mcp}`);
  }
  process.stdout.write(`Version check passed: ${versions.package}\n`);
} catch (error) {
  process.stderr.write(`${error.name}: ${error.message}\n`);
  process.exitCode = 1;
}
