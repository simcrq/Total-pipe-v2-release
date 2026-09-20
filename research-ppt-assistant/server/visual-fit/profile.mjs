import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PROFILE_PATH = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../visual-quality/profiles/default.json");
let defaultProfile;

export function resolveVisualFitProfile(profile) {
  if (profile?.visual_fit_rules) return profile.visual_fit_rules;
  if (profile?.scientific_figure) return profile;
  defaultProfile ??= JSON.parse(fs.readFileSync(PROFILE_PATH, "utf8")).visual_fit_rules;
  if (!defaultProfile?.scientific_figure) throw new TypeError("default Quality Profile is missing visual_fit_rules.scientific_figure");
  return structuredClone(defaultProfile);
}
