import { BOUNDED_REPAIR_LOOP_VERSION } from "./contracts.mjs";
import { createRepairPlan, MAX_REPAIR_ITERATIONS } from "./repair-controller.mjs";

export async function runBoundedRepairLoop(input = {}, adapters = {}) {
  if (typeof adapters.observe !== "function" || typeof adapters.applyRepair !== "function" || typeof adapters.render !== "function") {
    throw new TypeError("observe, applyRepair, and render adapters are required");
  }
  let artifact = input.initial_artifact;
  let lineage = [];
  const iterations = [];
  for (let iteration = 0; iteration <= MAX_REPAIR_ITERATIONS; iteration += 1) {
    const observation = await adapters.observe(artifact, { iteration, lineage: structuredClone(lineage) });
    const repairPlan = createRepairPlan(observation, { iteration, repair_lineage: lineage });
    iterations.push({ iteration, observation: structuredClone(observation), repair_plan: structuredClone(repairPlan) });
    lineage = repairPlan.repair_lineage;
    if (repairPlan.action === "KEEP") {
      return { loop_version: BOUNDED_REPAIR_LOOP_VERSION, status: "pass", iteration_count: iteration, render_count: iteration, final_artifact: artifact, repair_lineage: lineage, iterations };
    }
    if (repairPlan.action === "ESCALATE") {
      return { loop_version: BOUNDED_REPAIR_LOOP_VERSION, status: repairPlan.status, iteration_count: iteration, render_count: iteration, final_artifact: artifact, repair_lineage: lineage, iterations };
    }
    const revised = await adapters.applyRepair(repairPlan, artifact, { iteration, observation });
    artifact = await adapters.render(revised, { iteration: iteration + 1, repair_plan: repairPlan });
  }
  throw new Error("Bounded repair loop exceeded its fixed iteration budget");
}
