# Normalize-only 与局部 Deck IR 修补：独立验证记录

日期：2026-11-05（Asia/Shanghai）。本批基于已提交的 `c9a9bc0`，验证分支为
`codex/slim-agent-pipeline`。实现与测试由不同 Agent 负责；本记录执行者只修改测试和本报告，
没有修改实现、依赖环境、安装配置或科学门禁。第二批提交由主代理处理。

## 实测范围与结果

环境与第一批相同：macOS、Python 3.12.12、Node.js 24.20.0、OfficeCLI 1.0.158。
使用已有虚拟环境，`PYTHONPATH` 明确指向当前隔离工作树及其 tests，未安装额外依赖。

| 范围 | 实际结果 | 运行时点 |
| --- | --- | --- |
| 本批完整 Total-pipe 套件 | 579 tests；18 failures、5 errors、0 skip | 限额后的完整 IR 指引修复之前 |
| 最终受影响重点套件 | 145 tests；全部通过、0 skip | 指引修复及新增字段断言之后 |
| 独立 RPA `npm test` | 316 tests；全部通过、0 skip | normalize-only/repair 首轮就绪后；后续仅改 Agent 缓存及指引，复用该结果 |
| pwf2rpa | 96 tests；全部通过、0 skip | 同上 |
| `git diff --check` | 通过 | 最终文档及测试收尾 |
| 变更文档本地文件链接 | 164 个有效、0 失效 | 未验证锚点；旧默认模板规划语义扫描无残留 |

完整套件中，受影响的 145 项也全部通过。完整运行后，独立审查发现 `PATCH_LIMIT_REACHED`
虽已请求完整 `deck_ir`，`instructions_path` 仍指向 patch schema。实现随后改为存在的完整 IR
任务/提示文件，fallback 完整 Deck IR schema；最终 145 项重跑验证了该字段和其他受影响行为，
没有再次运行整个 579 项套件。

完整套件的 23 项失败/错误与[第一批实际完整运行](agent-slimming-validation.md)的集合完全相同，
集合差的新增和减少均为空。它们包括已存在的数学测量/布局问题、三项缺 `matplotlib` 的错误、
原生图形/列表问题、复杂混排样例容量失败以及两项 supplement 泄漏测试失败。
没有删除、跳过或放宽这些测试；本报告不宣称全仓测试通过，也不把这些已有问题描述为已修复。

`c9a9bc0` 是本批开发基线；失败集合对照沿用第一批保留的实测日志，而非虚构一次
`c9a9bc0` 的新完整运行。不同表格范围互相重叠，不能相加为独立测试总数。

## Normalize-only 的内容守恒

测试确认默认四工具接入层的 RPA 阶段只调用一次 `normalize-content`，不再调用模板
`plan` 或 `validate-deck`。完整 body、key_points、证据及原始输入仍保存在实际文件中；
中间 IR 提示通过 `content_paths` 引用完整内容，不要求重复内联它们。
过时 `deck_plan` 不会重新流入提示包，随后仍必须经过独立 page_design 和最终 `check_ir`。

旧测试原来按 plan/validate 调用序号断言；现改为核对只规范化、完整内容文件与指针、
过时模板计划不传播。RPA 的独立模板 CLI 没有改动，316 项 Node 测试保留并通过。
本记录验证的是职责与调用次数，没有把少两次模板调用换算成未经测量的整链提速比例。

## 局部修补的准入与事务保护

新增 `test_agent_repair.py` 的 29 项测试覆盖：

- 四工具表面保持四个工具，advance 接受 `deck_ir_patch`。回复提供小型 repair descriptor、
  独立完整 schema 路径与 changed_slide_ids，不返回整个 IR；合成夹具的回复还检查了体积上界。
- Schema 与运行时拒绝 semantic、theme、正文/数据、来源元数据和手工尺寸编辑；拒绝新 slide、
  新 asset、重复 slide ID、缺失/损坏/非栅格图片。尺寸从真实图片读取，来源元数据保持不变。
- 既有 panel 标题绑定 node ID；Control/Treatment 等具名 panel 的叶子引用归属不能交换。
  只移动完整 panel 的位置仍被允许。原编译器继续拒绝过窄图片/文字布局和不足的原生图形宽度。
- IR 与资源双哈希均在测量前核对。资源绑定包括实际图片、解析后的字体字节及
  compiler/layout/schema/agent 源码指纹。当前资源变更、测量期间 base 或替换图片字节变更
  均拒绝为 stale；实现还在 canonical 提交边界重新核对测量过的资源。
- preflight 调用原 `compile_input`，明确关闭自动 overflow repair、保留 Design 要求，
  不调用 OfficeCLI 写 PPT。原 canonical 与所有既有 build 文件的字节及 mtime 保持不变，
  只另写 `work/repairs` 反馈。
- 真实几何失败、字段拒绝、提交 canonical 的模拟原子写故障均保全已有 candidate/QA。
  原子写故障也保全原 checkpoints；没有因为失败而自动签收 REVIEW。
- apply 成功后才重新 checkpoint IR 并执行正常 build。完整科学字段、request、既有模型授权、
  Story/design 文件字节及 mtime 保持；相同已成功 patch 再提交不重复构建。
  现有图片缺失时，可按当前哈希把它重新绑定到可读的搬移副本。
- patch 不能与模型输入、重规划或 acknowledgement 混合提交；没有 canonical IR 或阶段不适合时
  不会构造或推进新的科学内容。三个不同科学修订拒绝后请求完整 IR 重规划，指引不再指向 patch 格式。

快速状态测试中的 candidate 是明确标记的非 PPTX 假数据，仅验证事务和状态，不能视为可编辑交付。
它们没有代替下面单独执行的真实 OfficeCLI 集成。

## 拒绝缓存、依赖失败与预算

真实 compiler QA FAIL 才可复用独立预检结果；固定条件是相同 patch fingerprint（含替换图片字节）、
相同当前 base 资源/源码指纹且反馈文件仍存在。测试实测：

- 相同几何失败提交两次，compiler 只调用一次，反馈路径相同，`reused_preflight=true`，只消耗一次预算。
- 同一 JSON 的替换图片字节变化后会重新测量并计作新修订；再次提交相同字节复用新反馈。
- 反馈文件删除后重新测量；base 字节变更不能复用旧拒绝结果，旧哈希请求返回 stale。
- 三次不同科学失败达到有限预算，重复拒绝不叠加；stale 和提交依赖错误不消耗科学修订预算。
- 连续三次模拟临时 compiler `OSError` 返回 `PATCH_PREFLIGHT_UNAVAILABLE/resolve_dependency`，
  不缓存、不耗预算；依赖恢复后同一 patch 第四次调用成功预检。

缓存不是对已损坏状态的授权恢复，也不把异常当成版面失败缓存。依赖/提交错误与真实几何 QA
失败的返回行为分别检查，避免用户必须改动科学内容才能重试基础设施问题。

## 真实本地 OfficeCLI 与科学图审边界

最终受影响运行实际执行了三条 OfficeCLI 集成，没有 skip：

1. 已设计的 native-bullets IR 导入、candidate、重启/幂等与删除 candidate 后的恢复。
2. 合成 Markdown 的本地 evidence、normalize-only RPA、必经 page_design、IR、Design、candidate。
3. 本地 reference 栅格图与原生文字页：真实初始 candidate → 不写 PPT 的修补预检 →
   布局/搬移图片路径 apply → 正常全套重建 → 拒绝禁止字段的 patch 并保全新 candidate/QA。

第三条集成先显式写入**合成测试审核记录**，用于检查已有 REVIEW acknowledgement 的失效。
它不是对真实科研内容的人类验收。apply 后 QA 为零 FAIL，旧记录不再匹配、acked_count 为零，
仍有待人工复核的 REVIEW；repair 没有自动签收新 REVIEW，也没有生成正式 final。

栅格路径更新可以指向重新裁图后的不同像素；元数据不变和几何通过不能证明科学内容等价。
实现返回 `scientific_image_review_required`，原科学图/参考图审核门禁继续保留，必须人工重新核对。
本测试没有声称验证像素中的科学结论或来源真实性。

未调用云 OCR、未上传论文、未调用真实模型生成 Story/Design；未运行 PowerPoint UI、
原生 PDF 导出或正式 final 晋级。测试中的 Story/page_design 和显式审核记录均为合成夹具。

## 命令、日志与变更文件

以下路径变量对应实际执行时的绝对 checkout 路径。解释器复用已有环境，不等于从该旧目录导入当前源码：

```bash
TP_REPO=/absolute/path/to/totalpipe-slimming
TP_ENV=/absolute/path/to/existing-checkout/Total-pipe/.venv
TP_PY="$TP_ENV/bin/python"
cd "$TP_REPO/Total-pipe"

# 指引修复前：579 项完整运行
PYTHONPATH="$TP_REPO/Total-pipe:$TP_REPO/Total-pipe/tests" "$TP_PY" -m unittest discover -s tests -v

# 指引修复后：145 项最终受影响集合
PYTHONPATH="$TP_REPO/Total-pipe:$TP_REPO/Total-pipe/tests" "$TP_PY" -m unittest \
  test_agent_adapters test_agent_doctor test_agent_entry test_agent_install test_agent_slimming \
  test_agent_state test_agent_repair test_page_design test_explanation_contract test_formula_capacity \
  test_deck_rules test_supplement -v

PYTHONPATH="$TP_REPO/Total-pipe" "$TP_PY" -m unittest discover -s pwf2rpa/tests -v
cd "$TP_REPO/research-ppt-assistant"
npm test
cd "$TP_REPO"
git diff --check
```

本机原始日志在临时目录，不是仓库内长期归档：

- `/private/tmp/totalpipe-repair-full-final.log`：579 项完整结果。
- `/private/tmp/totalpipe-repair-targeted-after-guidance.log`：最终 145 项通过。
- `/private/tmp/totalpipe-repair-rpa.log`：独立 RPA 316 项通过。
- `/private/tmp/totalpipe-repair-pwf2rpa.log`：pwf2rpa 96 项通过。
- `/private/tmp/totalpipe-slimming-full-final.log`：第一批完整失败集合对照。

失败集合按日志的 `FAIL:` / `ERROR:` 测试名取集合比较；当前减去第一批、第一批减去当前均为空。
开发中曾按主代理要求中断一次测试（退出 130），以及修正一个把两节点错误写作 process 的新测试
夹具；中断运行和该错误夹具不计作最终通过结果，最终使用合法 DAG 并在完整及最终受影响运行中验证。

本测试执行者的文件改动：

- `Total-pipe/tests/test_agent_adapters.py`：normalize-only 与完整内容/过时计划回归。
- `Total-pipe/tests/test_agent_repair.py`：schema、事务、科学约束、缓存、预算及真实 OfficeCLI 集成。
- `docs/agent-repair-validation.md`：本独立记录。

实现、入口及使用文档由主代理维护。本测试执行者未自行 commit、merge 或 push。
