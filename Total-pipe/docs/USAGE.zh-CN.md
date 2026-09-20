# Total-pipe v2 使用说明

本文描述当前主链，不兼容 M5 已删除的旧 SlideDSL、sidecar 或 Team wrapper。

## 1. 输入与输出

完整输入从论文 PDF 开始，编译器直接输入从 `deck_ir.json` 开始。

```text
论文 PDF
  → PaperWorkflow workflow.json
  → Story Planner story_plan.json
  → pwf2rpa rpa_input.json
  → RPA deck_plan.json
  → canonical deck_ir.json
  → Deck Compiler build directory
```

build directory 中的重要文件：

| 文件 | 含义 |
|---|---|
| `deck_ir.json` | 本次编译冻结的 canonical input |
| `layout.json` | 确定性布局、文本契约与 adaptation log |
| `candidate.pptx` | artifact-tool 原始导出 |
| `staging.pptx` | OOXML finalizer 处理后的验收对象 |
| `native.pdf` / `native.json` | PowerPoint 原生证据 |
| `qa_report.json` | 统一 QA 结果 |
| `metrics.json` | 编译指标 |
| `state.json` | 生命周期状态 |
| `final.pptx` | 通过晋级后的交付文件 |

## 2. 从 PaperWorkflow 到 RPA

运行 PaperWorkflow 后，使用用户明确选择的高能力模型生成 Story。Story 节点只表达
`question / answer / evidence / next`，不决定最终版式或 bbox。

```bash
cd Total-pipe/pwf2rpa
PYTHONPATH=. python -m pwf2rpa workflow.json +  --story story_plan.json +  --story-model "<user-selected-model>" +  --story-reasoning high +  --model-selected-by-user +  --strict +  --out rpa_input.json
```

然后在同级 `research-ppt-assistant` 项目运行：

```bash
cd ../../research-ppt-assistant
node server/cli.mjs normalize-content +  --file ../Total-pipe/pwf2rpa/rpa_input.json +  --detail-level standard

node server/cli.mjs plan +  --file plan-input.json +  --detail-level full
```

实际路径按工作区调整。RPA 的 `normalize_content` 必须返回 `valid`，
`create_deck_plan` 必须完成 `plan_complete`，之后再运行 `validate-deck`。

## 3. RPA 到 Deck IR

该步骤是明确的契约映射，不允许复制 RPA 的最终 bbox：

- RPA title/goal/takeaway/evidence 映射到 `semantic`；
- 内容角色映射为稳定的 `composition.blocks[].component`；
- 视觉对象映射为 `figure_refs` 和 `assets`；
- RPA Layout 只用于选择合适 archetype/component，不把坐标写进 IR；
- 所有 `evidence_refs`、`caveats` 和 `speaker_notes` 必须保留。

Deck IR 只接受
[catalog.py](../deck_compiler/catalog.py) 中的 archetype/component。
超出容量时返回 `CONTENT_CAPACITY_EXCEEDED` 或 `SPLIT_REQUIRED`，应回到 Story/RPA
拆页，而不是继续缩小字号。

### 长多段正文

如果 RPA 输出 `design_ir.text_flow.mode = distributed_arrow_list`：

1. 保留 3–5 个条目的顺序；
2. 用换行连接到一个 Deck IR block 的 `text`；
3. 将该 block 的 `text_flow` 设置为 `distributed_arrow_list`。

也可以将 block 设为 `auto`，由 Deck Compiler 识别。示例：

```json
{
  "id": "limits",
  "component": "body",
  "label": "适用边界",
  "text_flow": "auto",
  "text": "实验覆盖当前材料和功率窗口。\n机制证据仍不能排除替代解释。\n跨材料结论需要新的对照实验。"
}
```

自动模式要求 3–5 个明确段落、总显示长度至少 72 单位、单项不超过 120 单位，
汉字按 2 单位计。公式、表格、图注、参考文献和单个长段落保持普通文本。

## 4. 编译

先做无渲染编译检查：

```bash
cd Total-pipe
python -m deck_compiler compile +  --ir /absolute/path/to/deck_ir.json +  --out /absolute/path/to/build
```

正式生成：

```bash
python -m deck_compiler build +  --ir /absolute/path/to/deck_ir.json +  --out /absolute/path/to/build +  --node /absolute/path/to/node
```

开发时可添加 `--skip-native`，但该结果只能用于检查，不能晋级 final。

## 5. PowerPoint 原生验收

验收对象始终是当前 `staging.pptx`。如果自动导出未完成：

1. 用 Microsoft PowerPoint 打开 staging；
2. 导出为同一 build directory 下的 `native.pdf`；
3. 逐页检查文字、图片比例、panel 标签、页脚、越界、碰撞和字体；
4. 绑定该 PDF：

```bash
python -m deck_compiler validate-native +  --out /absolute/path/to/build +  --pdf /absolute/path/to/build/native.pdf +  --reviewer "reviewer"
```

`validate-native` 会重新检查当前 staging 与 layout；不要复用其他版本的 PDF。

## 6. REVIEW acknowledgement 与晋级

如果 `qa_report.json` 含 REVIEW，acknowledgement 至少包含：

```json
{
  "artifact_sha256": "<staging sha256>",
  "reviewer": "<reviewer>",
  "accepted_review_ids": ["<review id>"]
}
```

必须列出当前报告中的全部 REVIEW ID：

```bash
python -m deck_compiler promote +  --out /absolute/path/to/build +  --ack /absolute/path/to/review_ack.json
```

只有结构检查、PowerPoint 证据和 REVIEW acknowledgement 都与当前 bytes 对应时，
才会生成 `final.pptx`。

## 7. 常见误区

- `compile` 只生成 IR/layout/QA，不生成 PPTX。
- `build --skip-native` 不代表正式通过。
- RPA `design_status: pass` 不代表 Deck Compiler 或 PowerPoint 验收通过。
- `candidate.pptx` 不是交付文件；验收和晋级针对 `staging.pptx`。
- 手工修改 staging 后，旧 QA、PDF 和 acknowledgement 都会失效。
- `final_msyh_decorated.pptx` 是 Test3 的人工修订变体，不是编译器自动输出基线。
- 不要恢复 M5 已删除的旧 adapter 或双轨 QA 作为兼容路径。

## 8. 回归检查

```bash
cd Total-pipe
python -m unittest discover -s tests -v

cd pwf2rpa
PYTHONPATH=. python -m unittest discover -s tests -v

cd ../../research-ppt-assistant
npm test
npm run audit:layouts
```

发布副本的 `SHA256SUMS` 必须在所有同步修改完成后重新校验。
