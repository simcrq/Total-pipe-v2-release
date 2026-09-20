import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { assertJsonSchema } from "../schema-validator.mjs";
import { QUALITY_PROFILE_SCHEMA } from "./contracts.mjs";

const PROFILE_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "profiles");
const PROFILE_FILES = Object.freeze({
  default: "default.json",
  slidep: "slidep.json",
  "tencent-pptx": "tencent-pptx.json",
  "artifact-tool": "artifact-tool.json",
});

const cache = new Map();
const isRecord = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);

function mergeProfile(base, override) {
  const output = { ...base };
  for (const [key, value] of Object.entries(override ?? {})) {
    if (isRecord(value) && isRecord(base?.[key])) output[key] = mergeProfile(base[key], value);
    else output[key] = value;
  }
  return output;
}

async function readProfile(profileId) {
  if (!PROFILE_FILES[profileId]) throw new RangeError(`Unknown visual quality profile: ${profileId}`);
  if (!cache.has(profileId)) {
    cache.set(profileId, fs.readFile(path.join(PROFILE_DIR, PROFILE_FILES[profileId]), "utf8").then(JSON.parse));
  }
  return cache.get(profileId);
}

async function loadResolvedProfile(profileId, ancestry = []) {
  if (ancestry.includes(profileId)) {
    throw new RangeError(`Visual quality profile inheritance cycle: ${[...ancestry, profileId].join(" -> ")}`);
  }
  const selected = await readProfile(profileId);
  const profile = selected.extends
    ? mergeProfile(await loadResolvedProfile(selected.extends, [...ancestry, profileId]), selected)
    : mergeProfile({}, selected);
  assertJsonSchema(QUALITY_PROFILE_SCHEMA, profile, { toolName: "visual_quality_profile" });
  return profile;
}

export async function loadQualityProfile(profileId = "default") {
  return loadResolvedProfile(profileId);
}

export async function resolveQualityProfile({ profile, profile_id: profileId, renderer } = {}) {
  if (profile !== undefined) {
    assertJsonSchema(QUALITY_PROFILE_SCHEMA, profile, { toolName: "visual_quality_profile" });
    if (profile.extends === profile.profile_id) {
      throw new RangeError(`Visual quality profile inheritance cycle: ${profile.profile_id} -> ${profile.extends}`);
    }
    const resolved = profile.extends
      ? mergeProfile(await loadResolvedProfile(profile.extends, [profile.profile_id]), profile)
      : mergeProfile({}, profile);
    assertJsonSchema(QUALITY_PROFILE_SCHEMA, resolved, { toolName: "visual_quality_profile" });
    return resolved;
  }
  const normalizedRenderer = String(renderer ?? "").trim().toLowerCase().replaceAll("_", "-");
  return loadQualityProfile(profileId ?? (PROFILE_FILES[normalizedRenderer] ? normalizedRenderer : "default"));
}

export { mergeProfile };
