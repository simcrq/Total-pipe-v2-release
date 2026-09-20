import { adaptTencentPptxTelemetry } from "./tencent-pptx.mjs";
import { adaptSlidepTelemetry } from "./slidep.mjs";
import { adaptArtifactToolTelemetry } from "./artifact-tool.mjs";
import { buildInputRoots, normalizeRendererName, readAlias } from "./common.mjs";

export const RENDERER_ADAPTERS = Object.freeze({
  slidep: adaptSlidepTelemetry,
  "tencent-pptx": adaptTencentPptxTelemetry,
  "artifact-tool": adaptArtifactToolTelemetry,
});
export const RENDERER_ADAPTER_REGISTRY = RENDERER_ADAPTERS;

export function adaptRendererTelemetry(input = {}) {
  const roots = buildInputRoots(input);
  const rendererValue = readAlias(roots, ["renderer", "renderer_name", "rendererName", "engine", "adapter"]);
  const schemaValue = readAlias(roots, ["schema"]);
  const renderer = !rendererValue.found && String(schemaValue.value ?? "").startsWith("openai.presentation.layout/")
    ? "artifact-tool"
    : normalizeRendererName(rendererValue.value);
  const adapter = RENDERER_ADAPTERS[renderer];
  if (!adapter) throw new RangeError(`Unsupported renderer: ${rendererValue.value}`);
  return adapter(input);
}
