# Total-pipe Agent 接入层实施设计 v2

2026-10-25。依据当前 `b20b66c` 及用户提供的 v1 设计审阅后修订。
本文件先规定修订后的实施契约；验证结果记录在配套使用说明，不把计划写成完成声明。

## 评审结论与修正

保留四工具接入、组件子进程、Agent 编写科学产物和 CLI-only final 的方向。
v1 有以下阻断实现的问题，实施以本修订为准：

| 问题 | 修正 |
| --- | --- |
| 声称不改编译器，却新增 `deck_compiler ir-prompt` | 提示包属于接入层，入口改为 `python -m agent ir-prompt`；组件源码不改 |
| start 没有已有 IR 的路由，无法执行首个 smoke | 显式 source_kind=auto/pdf/markdown/workflow/deck_ir；已有 IR 直接进入校验 / Design / build |
| Story 提示包的模型字段位置错误 | 比较 `story.planner` 与提示包 `delegation`；reasoning 为 high 或更高，不能提供 medium |
| RPA `--file` 加 CLI 业务参数会被忽略 | 生成包含 presentation_type、完整 slide_briefs 和原始 workflow 的 plan-input.json；使用 full 输出 |
| 已有 briefs 时 slide_count 并不能覆盖页数 | 保留完整 briefs；数量不一致返回重规划，不截断 / 复制内容 |
| 阶段仅检查单个 artifact，且跳过 input 阶段 | 阶段声明 requires / produces；依次校验输入门禁、多产物、实际依赖哈希和配置指纹 |
| 上游文件变化仅比较旧 registry hash | 每次递归读取实际输入和先前阶段产物；接入层源码 / 阶段表及 Git 版本变化也使相关 checkpoint 失效 |
| 相同提交立即短路会阻止崩溃后继续 | 不重复接受 / 计次；仍继续派生未完成组件；成功组件逐阶段持久化 |
| job_id 无持久索引，重启无法查找 | 用户级 job registry 仅存输出路径；job.json 损坏返回可操作错误，不伪造模型授权或 provenance |
| 所有文件只能在 work，与 PWF 包根矛盾 | Agent 提交限定 work；组件证据包保留在 evidence；原始输入仅只读引用 |
| `synthesis_readiness.status`、容量错误名称不匹配源码 | readiness 使用 `readiness`；按实际 QA rule、退出码和结构化 payload 分类 |
| 普通 REVIEW 被当作 candidate 阻断 | FAIL 阻断；候选保留 REVIEW / 未签收数；复用候选 ack，绝不自动签收、晋级 |
| tools 数量 39、doctor 全 PASS 是固定假设 | 默认四工具固定；advanced 数量从三服务握手读取；平台 / OCR 缺失用能力区分 |
| TOML 标记块可能把后续根键纳入子表 | 托管块放文末；替换块后解析并比较非托管语义，冲突 / 坏 TOML 中止并备份 |
| 故障、重复调用都会消耗修订次数 | 仅被拒绝的 Agent 提交计次；读取状态和依赖失败不计次；新上游重置预算 |

## 边界

- PaperWorkflow、pwf2rpa、RPA、Deck Compiler 的科学 / 几何行为保持不变。
- 接入层只准备提示包、验证、记录和调用组件；queries、Story、IR、视觉提案由 Agent 编写。
- 模型选择来自当前或此前明确的用户选择，通过 model_selection 回填；不静默代填。
- Story provenance 自洽校验不证明真实调用。真实独立子代理及用户选择仍由宿主执行并如实记录。
- 不创建 final，不暴露 promote / validate-native / record-powerpoint-review；正式验收使用原 CLI。
- 安装器按调用者选择注册配置；开发测试只操作临时目录，不改开发机的全局设置或密钥。

## 阶段与入口

阶段顺序、Agent 产物名、依赖、执行超时、重试上限与文档路由由 `agent/stages.json` 维护。
12 个阶段保留 intake、queries、evidence、model_selection、story_prompt、story、rpa、deck_ir、
design、visual_design、build、candidate_ready。每个分支按源类型裁剪阶段：

- PDF / Markdown：queries → evidence → 用户模型输入 → Story prompt → Story → RPA → IR → Design → build。
- workflow.json：读取并验证现有证据包，从模型输入继续。
- Deck IR：引用源文件、在 work 中以绝对资源路径保存工作副本，从 IR 校验继续。
- 已完整设计的 IR：保持已有设计，直接 build；未完成设计仍须视觉提案。

默认四工具：`totalpipe_doctor`、`totalpipe_start`、`totalpipe_advance`、`totalpipe_status`。
start 收 source、out_dir、language、presentation_type，可选 requirements、queries、slide_count、
source_kind、supplementary_paths；不接受模型字段。PDF 的鉴权失败返回解决依赖动作。
advance 收 job_id，可提交 artifact_kind / artifact_path，回填 inputs，或明确 replan_from。
candidate acknowledgement 必须含 reviewer、note、review_ids；FAIL 无法签收。

next_action 保留七类 author_artifact / invoke_subagent / provide_input / replan /
resolve_dependency / review_required / none。每类附可执行的路径、字段或 remedy。
stage_index 从 1 开始；status 为 running / waiting_agent / blocked / candidate_ready / failed。
业务失败返回 envelope，参数类型或未知字段是协议错误。

## 状态与恢复

`out/.totalpipe/job.json` 保存请求、源指纹、Agent 输入与产物 / checkpoint 指针，
不保存科学内容副本或密钥。用户级 `TOTALPIPE_AGENT_HOME/jobs/<job_id>.json` 只保存 out 路径。
文件原子替换，job 目录使用非阻塞 OS 文件锁；进程退出释放，冲突返回 JOB_BUSY。

阶段完成是派生结果：所有前置阶段有效、输入仍满足、输出文件存在且哈希相同、
当前依赖指纹与 checkpoint 相同。组件成功后立刻保存，失败后重跑当前阶段，跳过成功上游。
证据目录整体文件清单纳入哈希；IR 引用的图像 / 本地字体也纳入依赖。
同一 Agent 文件提交不重复计次；状态查询只检查与返回，不运行组件。
上游改变 / 显式 replan_from 使下游失效。注册文件或 job.json 损坏返回修复说明，
不能从散落产物自动重建用户授权。

## 实际组件契约

| 阶段 | 入口与验证 |
| --- | --- |
| evidence | bridge 在独立进程导入 PWF tool_literature_workflow；stdout 只返回 JSON，日志转 stderr；包目录不重排 |
| story_prompt | 在 Total-pipe/pwf2rpa cwd 执行 `python -m pwf2rpa ... --make-story-prompt` |
| story | 原有 story_to_specs 校验，加 delegation 的 model / reasoning 绑定；缺失 / 不一致分别报告 |
| rpa | 严格 convert → normalize full → plan full → validate-deck full；validation_input 携原始完整 content_model |
| deck_ir | 复用 canonical 语义校验；核对原始 briefs 的 body / key_points 在 IR 页面文字或讲稿中完整保留 |
| design | 既有 visual-prompt；提案只合入 presentation，相对资源路径保持语义 |
| build | apply-visual-plan（如需要）→ build --skip-native；检查当前 candidate / staging / QA 的哈希与 FAIL |

未知非零退出、坏 JSON、超时和依赖缺失均保留诊断日志路径，并给出下一步。
日志先屏蔽当前环境中的 token / key 等敏感值；不把密钥写入 job 或报告。
容量 / 契约失败回到正确产物阶段，不重复跑相同内容，也不自动缩写或删图。

IR 提示包含完整 workflow、原始 RPA 输入 / normalized content / plan、真实 catalog 与 schema、
素材根和完整保留检查表。提示包是输入，接受产物时由状态依赖及语义 / 内容校验绑定。
不从 catalog 伪造 figure_refs / graphics 固定容量；用 catalog 的 blocks / figures 字段，
图形、表格与树限制取当前能力声明。

## 安装与诊断

`python install.py --client codex|claude|none --profile agent|advanced` 创建 / 复用仓库 .venv，
读取真实 requirements 和 PaperWorkflow pyproject 依赖，安装后检查目标解释器与组件。
`--dry-run` 无写入 / 安装 / 配置副作用；`--config` 可指定测试或非默认客户端配置。
Codex TOML 使用受管块 + 备份 + 解析前后语义检查；Claude JSON 合并保留其他字段。
检测同名非托管服务冲突时中止；--force 只允许明确替换冲突的 JSON 服务，不重写用户 TOML。
仓库 .mcp.json 保持相对路径；用户配置使用绝对解释器、cwd、Node 路径及 UTF-8 环境。
安装前先握手目标 profile，再注册；默认准确检查四个工具，advanced 数量动态统计。

doctor 的 12 类检查保留 Python / import / Node / RPA / OfficeCLI present-version-runtime /
MinerU / bridge / 字体 / pdfplumber / PowerPoint。默认不写探针；deep 模式在临时目录实际写 PPTX。
OCR 支持官方 CLI 已登录或环境 token，配置 / CLI 状态不确定时不宣称已认证。
字体使用现有字体解析能力，不将字体白名单等同于中文覆盖。
原生 final 能力只表示依赖就绪，实际晋级仍需真实 UI / PDF / review 证据。

## 实施与验收

按安装 / 状态及 adapter / 四工具闭环 / 轻量 Skill 与入口切换的依赖顺序实施。
轻量 Skill ≤60 行，直接解释 stage / next_action，不自建第二份阶段表。
advanced 保留三服务，回切只更换用户配置；默认与 advanced 不同时注册同名服务。

必须验证：配置幂等与坏 TOML / 冲突；真实 MCP 握手；未知 job；跨进程恢复与锁；
上游变更 / 删除 / 相对资源；模型与 reasoning 绑定；RPA 内容丢失；Design 缺页；
容量失败重规划；相同提交幂等；候选 ack 不绕过 final；已有 IR 的真实 OfficeCLI 构建。
已有 Markdown 使用真实 PWF / RPA 运行，Story 用明确标为测试的固定 fixture，不冒充模型调用。
PDF 云 OCR、Windows 锁与 PowerPoint 正式验收必须区分已执行和未执行，不把 skip 计作通过。
