# Agent 流水线瘦身：独立验证记录

日期：2026-11-05（Asia/Shanghai）。基线提交：`8ee70f7d87c614243877fcb146b4a6224f1047c9`。
当前分支：`codex/slim-agent-pipeline`，验证对象为该基线上的本次工作树改动。

实现与测试由不同 Agent 负责。本记录的执行者仅修改测试及本验证记录，未修改实现、安装配置、
科学门禁或依赖环境。重点回归通过；完整套件仍有基线已有失败，不能据此宣称全仓测试通过。

## 环境与结果

同一台 macOS、同一个已有虚拟环境：Python 3.12.12、Node.js 24.20.0、OfficeCLI 1.0.158。
解释器来自基线 checkout 的 `Total-pipe/.venv/bin/python`；测试当前改动时，`PYTHONPATH`
显式指向隔离工作树，避免误测基线或已安装插件。没有安装或更换依赖；该环境未安装 `matplotlib`。

| 验证范围 | 实际结果 | 说明 |
| --- | --- | --- |
| 原始基线 Total-pipe 完整套件 | 532 tests；21 failures、6 errors、0 skip | 同环境实跑，日志见下 |
| 当前改动完整套件，恢复兼容修复之前 | 546 tests；18 failures、5 errors、0 skip | 剩余 23 项全部在基线失败集合内；新增失败集合为空 |
| 最终恢复兼容修复后重点套件 | 115 tests；全部通过、0 skip | Agent 全组、页面设计、讲解覆盖、公式容量、Deck 规则、补充内容规则 |
| pwf2rpa | 96 tests；全部通过、0 skip | Story、证据适配与资源元数据 |
| RPA `npm test` | 316 tests；全部通过、0 skip | Node 本地测试 |
| 文档检查 | 128 个已有变更文档的本地文件链接有效；`git diff --check` 通过 | 链接检查未验证锚点；过时数量耦合关键词无残留 |

完整套件运行后又修复了旧别名请求的恢复兼容性，并新增三组恢复测试。按任务范围，最终再次运行
115 项受影响重点回归，没有在这次兼容修复后重复整个完整套件。上述不同范围存在重叠，不能相加
作为独立测试总数；测试数量和运行结果仅对应本次环境与工作树。

## 已验证的契约

- `slide_count=22` 可对应 9 个 Story 节点、11 条完整 briefs、22 页设计及 22 页合法 IR。
  不再以节点倍数或 brief 数量阻塞页面设计；显式设计数量不符返回 `PAGE_DESIGN_INVALID`，
  IR（包括已有 IR 导入）数量不符在 build 前返回 `SLIDE_COUNT_MISMATCH`。
- 两条完整 briefs 可以合成一页；丢失任一完整正文仍返回 `CONTENT_LOSS`。页面设计仍拒绝
  未使用的 Story 单元、跨页重复单元、未知 EV 与证据中没有的数字。没有 normalized RPA
  content 时，已批准设计的丢 EV、丢数字也返回 `DESIGN_REALIZATION_FAILED`。
- 独立纯补充文字页可在论文页目标之外；含论文 EV 的页面不能借 `supplement` 标签逃避论文页计数。
  补充开关、原始证据与论文内容门禁保持执行。
- 合法场合别名规范化；未知类型、非整数页数、布尔页数和范围外页数在创建输出前拒绝。
  旧 raw alias 请求与等价新别名可以恢复同一个 job，保留已有 `request`、`inputs` 与授权。
  听众说明、场合、`requirements`、语言或目标页数的实质变更仍返回 `JOB_OUTPUT_IN_USE`。
- start、advance、status 默认紧凑回复；MCP 与 CLI 的 full status 保留完整 request/artifacts。
  status 不执行组件、不写 job/events/work；上游变化、缺少已设计提示包时也不生成文件，
  缺提示时由 `ADVANCE_REQUIRED` 指向 advance。
- 真实本地 Python 组件 probe 验证了失败、恢复、显式修订与再次成功。JSONL 保持旧字节前缀，
  span 起止匹配且各轮 span 不复用，UTC 时间与非负执行耗时有效，事件有成功、失败和等待状态。
  固定字段中不含提示正文、密钥哨兵或模型私有推理哨兵。等待只记录时间点，不冒充模型耗时。
- 旧 layout feedback 存在时，新提交失败指向当前 `submission_feedback.json`，不会返回旧 QA。
- doctor 的真实桥接子进程被注入 `utils.pdf_handler` 导入失败。版本握手仍 PASS，
  `paperworkflow.runtime_imports` 为 FAIL，PDF evidence 能力被阻塞；没有实例化 OCR 或上传 PDF。

未观察到本次改动降低字号、公式/图形/图片尺寸门禁或放宽 Story 模型授权。完整套件中仍有基线已有
科学/排版问题，尤其已有两项 supplement 泄漏测试失败；本记录不把这些问题描述为已修复或已通过。

## 真实本地集成与夹具调整

两条使用实际 OfficeCLI 的集成均通过，没有跳过：

1. 自带、已有 Design 的 `native-bullets.deck_ir.json` 导入后生成 candidate，检查 QA 零 FAIL、
   重启恢复、重复提交幂等、删除 candidate 后回到 build。
2. 合成研究 Markdown 经本地 evidence、RPA、必经 page_design、IR、整套 Design 后生成 candidate。
   Story 与页面设计明确为测试夹具，未伪造为真实模型的科研验收结果。

另保留了一份真实 native-bullets candidate：QA 为 0 FAIL、4 REVIEW、2 INFO。
这些 REVIEW 没有被自动签收，未产生正式 final。

旧成功导入测试原来使用复杂混排展示样例。原始 `8ee70f7` 的同一测试、当前原始 IR 直接 compile
均因 `INSUFFICIENT_DRAWING_SPACE` 失败：body 需要 `1168 × 476.6 px`，可用 `1168 × 450 px`。
因此仅该成功导入/恢复测试切换到自带 native-bullets 夹具；没有全局替换 `AgentCase.fixture_ir`，
没有缩字号、删除复杂混排内容或绕过容量门禁。独立复杂混排测试仍运行并如实保留失败。

其它旧测试的语义调整是：页面设计不再要求 forms/devices 能力清单，RPA mock 接受已有关键字参数，
Markdown 集成必须经过页面设计门禁，doctor 检查稳定的检查项 ID 而非固定检查总数。

## 完整套件的失败集合差

当前完整套件失败集合减去基线失败集合为 **空集**。基线独有的四项是上述已修正测试语义或夹具的
`test_design_task_is_a_capability_brief`、
`test_rpa_file_payload_and_full_original_content_validation`、
`test_actual_imported_ir_to_candidate_restart_and_idempotent_advance`、
`test_actual_markdown_evidence_rpa_ir_design_and_build_with_explicit_test_story`。

共同剩余的 23 项如下；没有因为它们是基线失败而删除或跳过：

| 文件 / 测试 | 当前结果 |
| --- | --- |
| test_formula / test_agent_math_delimiters_and_functions_are_supported | FAIL |
| test_formula / test_measure_is_exact_for_math_and_flagged_for_text | FAIL |
| test_formula / test_measure_typesets_math_instead_of_measuring_literal_latex | ERROR：缺 matplotlib |
| test_schematic / test_flow_and_trend_render_png | ERROR：缺 matplotlib |
| test_schematic / test_mermaid_without_cli_fails_loudly | ERROR：缺 matplotlib |
| test_native_graphics / test_tampering_with_native_objects_is_detected | ERROR：GRAPHIC_STYLE_MISMATCH 子项的 XML fill 不存在 |
| test_native_list / test_auto_lists_keep_native_markers_and_plain_mode_remains_optional | ERROR：StopIteration |
| test_complex_mixed_example / test_ir_compiles_one_page_with_all_native_content_and_measured_list | FAIL |
| test_dag_layout / test_linear_three_node_positions_and_commands_remain_v2 | FAIL |
| test_dag_layout / test_mixed_presets_and_different_text_lengths_are_preserved | FAIL |
| test_inline_emphasis / test_bold_advances_are_measured_with_the_bold_face | FAIL |
| test_layout_tree / test_wide_process_in_three_columns_returns_path_and_sizes_atomically | FAIL |
| test_matrix_formula / test_many_formulas_use_measured_rows_without_a_two_equation_limit | FAIL |
| test_matrix_formula / test_provider_never_packs_or_truncates_dense_formula_pages | FAIL |
| test_matrix_formula / test_parallel_matrix_spacing_is_preserved_and_measured | FAIL |
| test_native_graphics / test_deterministic_layout_preserves_content | FAIL |
| test_native_graphics / test_emphasis_tone_changes_only_the_node_fill_and_rule | FAIL |
| test_native_list / test_short_explicit_lists_fit_measured_boxes_below_220px | FAIL：designed=True |
| test_native_list / test_short_list_and_native_formula_share_the_measured_region | FAIL：designed=True |
| test_native_list / test_short_list_native_roundtrip_fits_below_the_old_height_floor | FAIL |
| test_reference_images / test_visual_plan_measures_short_list_with_the_configured_spacing | FAIL |
| test_supplement_agent / test_numeric_paper_value_in_supplement_is_rejected | FAIL |
| test_supplement_agent / test_supplement_page_title_is_checked | FAIL |

## 回复体积

按 `len(json.dumps(response, ensure_ascii=False).encode("utf-8"))` 测量返回对象序列化字节数：

| 夹具 | compact | full | 体积下降 |
| --- | ---: | ---: | ---: |
| 实际 native-bullets candidate status | 983 B | 2,603 B | 62.24% |
| 合成 1,000 个引用、200 个独立 asset 的清单 | 1,092 B | 147,393 B | 99.26% |

第二项仅构造清单并调用 envelope，没有生成、读取或编译那些合成资产。该数据说明输出体积，
不是整链提速、模型 token、科研质量或宿主模型生成耗时基准。

## 可复现命令与日志

以下路径变量对应实际执行时的绝对 checkout 路径；基线与当前 checkout 必须分开：

```bash
TP_BASELINE=/absolute/path/to/baseline-8ee70f7
TP_REPO=/absolute/path/to/totalpipe-slimming
TP_PY="$TP_BASELINE/Total-pipe/.venv/bin/python"

# 基线完整套件
cd "$TP_BASELINE/Total-pipe"
PYTHONPATH="$TP_BASELINE/Total-pipe" "$TP_PY" -m unittest discover -s tests -v

# 原始 complex-mixed 导入测试的基线复现
PYTHONPATH="$TP_BASELINE/Total-pipe:$TP_BASELINE/Total-pipe/tests" "$TP_PY" -m unittest \
  test_agent_entry.EntryTests.test_actual_imported_ir_to_candidate_restart_and_idempotent_advance -v

# 当前完整套件（恢复兼容修复前的 546 项）
cd "$TP_REPO/Total-pipe"
PYTHONPATH="$TP_REPO/Total-pipe:$TP_REPO/Total-pipe/tests" "$TP_PY" -m unittest discover -s tests -v

# 最终兼容修复后的 115 项重点回归
PYTHONPATH="$TP_REPO/Total-pipe:$TP_REPO/Total-pipe/tests" "$TP_PY" -m unittest \
  test_agent_adapters test_agent_doctor test_agent_entry test_agent_install test_agent_slimming \
  test_agent_state test_page_design test_explanation_contract test_formula_capacity test_deck_rules test_supplement -v

PYTHONPATH="$TP_REPO/Total-pipe" "$TP_PY" -m unittest discover -s pwf2rpa/tests -v
cd "$TP_REPO/research-ppt-assistant"
npm test
cd "$TP_REPO"
git diff --check
```

本次本机原始日志保存在临时目录，不是仓库内长期归档：

- `/private/tmp/totalpipe-slimming-baseline-full.log`
- `/private/tmp/totalpipe-slimming-baseline-imported.log`
- `/private/tmp/totalpipe-slimming-full-final.log`
- `/private/tmp/totalpipe-slimming-targeted-final-compatible.log`
- `/private/tmp/totalpipe-slimming-pwf2rpa.log`
- `/private/tmp/totalpipe-slimming-rpa.log`
- `/private/tmp/totalpipe-slimming-imported-integration-2/build/qa_report.json`
- `/private/tmp/totalpipe-slimming-native-bullets-integration/build/qa_report.json`

未调用云 OCR、未上传论文、未调用真实模型生成 Story/Design、未运行 PowerPoint UI/原生 PDF 导出，
未执行正式 final 晋级。本验证执行者未执行 commit、merge 或 push。
