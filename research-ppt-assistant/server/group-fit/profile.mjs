import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PROFILE_PATH = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../visual-quality/profiles/default.json");
let defaultProfile;

export function resolveRelationFitProfile(profile) {
  if (profile?.relation_fit_rules) return structuredClone(profile.relation_fit_rules);
  if (profile?.group_fit && profile?.arbitration && profile?.credits) return structuredClone(profile);
  defaultProfile ??= JSON.parse(fs.readFileSync(PROFILE_PATH, "utf8")).relation_fit_rules;
  if (!defaultProfile?.group_fit || !defaultProfile?.arbitration || !defaultProfile?.credits) {
    throw new TypeError("default Quality Profile is missing relation_fit_rules");
  }
  return structuredClone(defaultProfile);
}
