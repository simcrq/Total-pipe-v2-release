import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const DESIGN_REGISTRY_VERSION = "1.0.0";

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
const REGISTRY_DIR = path.resolve(MODULE_DIR, "..", "..", "registry");
let registryPromise;

function assertRecord(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new TypeError(`${label} must be an object`);
}

function validateRegistry(treatmentPayload, decorationPayload) {
  assertRecord(treatmentPayload, "visual treatment registry");
  assertRecord(decorationPayload, "decoration profile registry");
  if (treatmentPayload.schema_version !== DESIGN_REGISTRY_VERSION || decorationPayload.schema_version !== DESIGN_REGISTRY_VERSION) {
    throw new RangeError("Design registry schema versions must match the runtime contract");
  }
  const treatmentIds = new Set();
  for (const treatment of treatmentPayload.treatments ?? []) {
    assertRecord(treatment, "visual treatment");
    if (!treatment.id || treatmentIds.has(treatment.id)) throw new RangeError(`Duplicate or missing visual treatment id: ${treatment.id}`);
    treatmentIds.add(treatment.id);
  }
  const grammar = decorationPayload.grammar ?? {};
  const profileIds = new Set();
  for (const profile of decorationPayload.profiles ?? []) {
    assertRecord(profile, "decoration profile");
    if (!profile.id || profileIds.has(profile.id)) throw new RangeError(`Duplicate or missing decoration profile id: ${profile.id}`);
    profileIds.add(profile.id);
    for (const key of ["background", "section_marker", "figure_treatment", "emphasis", "container", "divider"]) {
      if (!Array.isArray(grammar[key]) || !grammar[key].includes(profile[key])) {
        throw new RangeError(`Decoration profile ${profile.id} uses unsupported ${key}: ${profile[key]}`);
      }
    }
    for (const treatmentId of profile.compatible_treatments ?? []) {
      if (!treatmentIds.has(treatmentId)) throw new RangeError(`Decoration profile ${profile.id} references unknown treatment ${treatmentId}`);
    }
  }
  for (const treatment of treatmentPayload.treatments ?? []) {
    for (const profileId of treatment.decoration_profiles ?? []) {
      if (!profileIds.has(profileId)) throw new RangeError(`Visual treatment ${treatment.id} references unknown decoration profile ${profileId}`);
    }
  }
}

async function readJson(fileName) {
  return JSON.parse(await fs.readFile(path.join(REGISTRY_DIR, fileName), "utf8"));
}

export async function loadDesignRegistry() {
  if (!registryPromise) {
    registryPromise = Promise.all([
      readJson("visual-treatments.json"),
      readJson("decoration-profiles.json"),
    ]).then(([treatmentPayload, decorationPayload]) => {
      validateRegistry(treatmentPayload, decorationPayload);
      const treatments = treatmentPayload.treatments.map((item) => structuredClone(item));
      const decorations = decorationPayload.profiles.map((item) => ({
        ...structuredClone(item),
        decoration_budget: structuredClone(decorationPayload.default_budget),
      }));
      return Object.freeze({
        schema_version: DESIGN_REGISTRY_VERSION,
        grammar: structuredClone(decorationPayload.grammar),
        default_budget: structuredClone(decorationPayload.default_budget),
        treatments,
        decorations,
        treatments_by_id: new Map(treatments.map((item) => [item.id, item])),
        decorations_by_id: new Map(decorations.map((item) => [item.id, item])),
      });
    });
  }
  return registryPromise;
}
