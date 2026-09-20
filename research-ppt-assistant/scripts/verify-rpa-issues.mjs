import { searchLayouts, getLayout } from "../server/core.mjs";
import { planSlideClosedLoop, inferSemanticCategory } from "../server/planning-loop.mjs";
import { runVisualFitPreflight } from "../server/visual-fit/index.mjs";
import { validateDeckPlan } from "../server/core.mjs";

const fail = [];
const ok = (name) => console.log(`  PASS  ${name}`);
const bad = (name, extra = "") => { console.log(`  FAIL  ${name} ${extra}`); fail.push(name); };

// ---------- RPA-1: 1:1 方图 ----------
console.log("\n[RPA-1] plan 选型是否消费 visual_aspect_ratio");
const square = {
  text_chars: 120,
  title_chars: 12,
  image_count: 1,
  visuals: [{ visual_type: "schematic", visual_aspect_ratio: 1.0, panel_count: 1 }],
};
const withAr = await searchLayouts({ ...square, k: 3, include_slots: true });
const withoutAr = await searchLayouts({ text_chars: 120, title_chars: 12, image_count: 1, k: 3, include_slots: true });

const boxOf = (b) => ({ w: b?.width ?? b?.w, h: b?.height ?? b?.h });
function bestSlotAspect(result) {
  const slots = (result.slot_specs ?? []).filter((s) => ["image", "figure", "chart"].includes(s.slot_type));
  if (!slots.length) return null;
  return Math.max(...slots.map((s) => { const b = boxOf(s.box); return (b.w * 16 / 9) / b.h; }));
}
function fill(src, slot) {
  if (!src || !slot) return null;
  return Math.min(src / slot, slot / src);
}

const topWith = withAr.results[0];
const topWithout = withoutAr.results[0];
// 用选型自身报告的实际分配槽位宽高比，而不是"最大的图槽"。
const slotArWith = topWith.visual_fill?.slot_aspect_ratio ?? null;
const detailWith = await getLayout(topWith.id);
const slotArWithout = topWithout.visual_fill?.slot_aspect_ratio ?? null;
console.log(`  with visual_aspect_ratio=1.0 -> ${topWith.id}  slot_ar=${slotArWith?.toFixed(2)}  contain_fill=${(fill(1.0, slotArWith) * 100).toFixed(0)}%`);
console.log(`  without                      -> ${topWithout.id}  slot_ar=${slotArWithout?.toFixed(2)}  contain_fill=${(fill(1.0, slotArWithout) * 100).toFixed(0)}%`);

const geomScore = topWith.components?.visual_geometry_score;
console.log(`  components.visual_geometry_score = ${geomScore}`);
if (topWith.id !== topWithout.id) ok("选型结果因 visual_aspect_ratio 而改变（已消费该字段）");
else bad("选型结果未因 visual_aspect_ratio 改变");
if (geomScore !== undefined) ok("components 暴露 visual_geometry_score");
else bad("components 缺少 visual_geometry_score");
if (topWith.visual_fill?.estimated_contain_fill !== undefined) ok("候选结果暴露 visual_fill 预估值");
else bad("候选结果缺少 visual_fill 预估值");
if (Math.abs(slotArWith - 1) <= Math.abs(slotArWithout - 1)) ok("方图选到的槽宽高比更接近 1:1");
else bad("方图选到的槽宽高比没有改善");

// 从像素推导
const fromPx = await searchLayouts({
  text_chars: 120, title_chars: 12, image_count: 1, k: 1, include_slots: true,
  visuals: [{ visual_type: "schematic", source_width_px: 1000, source_height_px: 1000, panel_count: 1 }],
});
if (fromPx.results[0]?.id === topWith.id) ok("缺失 visual_aspect_ratio 时能从 source_width_px/height_px 推导");
else console.log(`  INFO  像素推导结果 ${fromPx.results[0]?.id} vs 显式声明 ${topWith.id}`);

// ---------- RPA-2 ----------
console.log("\n[RPA-2] visual-fit-preflight 对 schematic 的几何校验");
const schematic = runVisualFitPreflight({
  visual_id: "p06",
  source: { width: 1000, height: 1000 },
  allocated_visual_bbox: { x: 0, y: 0, width: 1000, height: 139 }, // ~7.19:1 扁槽
  visual_intent: { visual_type: "schematic", crop_policy: "full_figure", fit_policy: "contain", whitespace_policy: "minimal" },
});
console.log(`  status=${schematic.status} reason=${schematic.reason} governance=${schematic.governance} verified=${schematic.verified}`);
console.log(`  area_fill=${schematic.metrics.visual_fill.area_ratio}`);
if (schematic.status !== "pass") ok("15% 填充率的 schematic 不再静默 pass");
else bad("schematic 仍然静默 pass");
if (schematic.governance === "not_governed" && schematic.verified === false) ok("pass 场景显式标记 governance=not_governed / verified=false");
else console.log("  INFO  (该用例触发了 warning，pass 分支另测)");
const roomy = runVisualFitPreflight({
  visual_id: "p06b",
  source: { width: 1000, height: 1000 },
  allocated_visual_bbox: { x: 0, y: 0, width: 1000, height: 1000 },
  visual_intent: { visual_type: "schematic", crop_policy: "full_figure", fit_policy: "contain", whitespace_policy: "minimal" },
});
if (roomy.status === "pass" && roomy.governance === "not_governed" && roomy.verified === false) ok("未触发下限时为 pass + not_governed + verified=false");
else bad("宽松场景下 governance 标记不正确", JSON.stringify({ s: roomy.status, g: roomy.governance, v: roomy.verified }));

// ---------- RPA-3 ----------
console.log("\n[RPA-3] CLI get 与 layouts.json 字段一致性");
const got = await getLayout("RM-THEORY-03");
const L = got.layout;
const libEntry = JSON.parse((await import("node:fs")).default.readFileSync(new URL("../assets/layout-library/layouts.json", import.meta.url), "utf8"))
  .layouts.find((x) => x.id === "RM-THEORY-03");
if (Array.isArray(L.slots) && L.slots.length === libEntry.slots.length) ok(`get.layout.slots[] 与 layouts.json slots[] 对齐 (${L.slots.length})`);
else bad("get.layout.slots 缺失或长度不一致");
if (L.slots?.every((s, i) => s.id === libEntry.slots[i].id && s.type === libEntry.slots[i].type)) ok("slots[].id / slots[].type 与库文件逐项一致");
else bad("slots[].id/type 与库文件不一致");
if (L.capacity?.image_capacity === (libEntry.content_profile?.image_capacity ?? 0)) ok("capacity.image_capacity 与 content_profile.image_capacity 一致");
else bad("capacity.image_capacity 不一致", JSON.stringify(L.capacity));
if (L.capacity?.max_text_chars === libEntry.max_text_chars) ok("capacity.max_text_chars 与 max_text_chars 一致");
else bad("capacity.max_text_chars 不一致");
if (L.field_aliases) ok("提供 field_aliases 文档");
else bad("缺少 field_aliases");

// ---------- RPA-4 ----------
console.log("\n[RPA-4] validate-deck 返回结构");
const vd = await validateDeckPlan({
  slides: [
    { layout_id: "RM-THEORY-03", title: "T", content_metrics: { text_chars: 50, title_chars: 1 } },
  ],
});
console.log(`  keys=${Object.keys(vd).join(",")}`);
if (vd.summary) ok("validate-deck 返回 summary");
else bad("validate-deck 缺少 summary");
if (vd.result_contract) ok("validate-deck 返回 result_contract（说明 slides[]/index/status）");
else bad("缺少 result_contract");
if (vd.summary?.total_slides === 1 && typeof vd.summary.passed === "boolean") ok("summary 含 total_slides / passed");
else bad("summary 字段不完整", JSON.stringify(vd.summary));

// ---------- RPA-5 ----------
console.log("\n[RPA-5] plan 语义错配（Arrhenius 外推 vs decision）");
const brief = {
  slide_id: "P10",
  title: "保持时间的 Arrhenius 外推",
  goal: "说明保持时间随温度变化的机理，并用 Arrhenius 关系外推室温寿命",
  narrative_job: "给出理论依据",
  key_points: ["热激活过程服从 Arrhenius 定律", "由加速实验外推室温保持时间"],
  text_chars: 180,
  title_chars: 14,
  category_hint: "decision",
};
const sig = inferSemanticCategory(brief, ["decision"]);
console.log(`  signals=${JSON.stringify(sig.signals)} conflict=${sig.conflict}`);
if (sig.category === "theory" && sig.conflict) ok("识别出 theory 语义并与 decision hint 冲突");
else bad("未识别 theory/冲突", JSON.stringify(sig));

const seenCategories = [];
let firstCandidate = null;
const planned = await planSlideClosedLoop({ slide_brief: brief }, {
  searchLayouts: async (q) => {
    seenCategories.push(q.categories ?? null);
    const r = await searchLayouts({ ...q, k: 8, include_slots: true });
    firstCandidate ??= r.results[0]?.id ?? null;
    return r;
  },
  getLayout: async (id, theme, mode) => (await getLayout(id, theme, mode)).layout,
});
const pl = planned.slides?.[0];
console.log(`  categories sent to search = ${JSON.stringify(seenCategories[0])}`);
console.log(`  first candidate = ${firstCandidate}  planning.status=${planned.status}`);
if (JSON.stringify(seenCategories[0]) === JSON.stringify(["theory"])) ok("检索类别被语义信号改写为 theory（不再被 decision hint 绑死）");
else bad("检索类别未被改写", JSON.stringify(seenCategories));
if (String(firstCandidate).startsWith("RM-THEORY")) ok("首选候选落在 theory 版面族");
else bad("首选候选不在 theory 族", String(firstCandidate));

console.log(`\n${fail.length ? `FAILED (${fail.length}): ${fail.join(" | ")}` : "ALL CHECKS PASSED"}`);
process.exit(fail.length ? 1 : 0);
