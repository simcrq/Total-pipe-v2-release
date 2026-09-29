# Total-pipe v3 实验接入

新增 `--layout-provider v26`；默认 `deterministic` 保持 v2 行为。
模型、推理源码与编译器均位于此实验目录，不依赖训练仓库源码或插件缓存。
当前机器复用已安装 PyTorch 的 Python 运行时：
`F:/Workbuddy/ppt-generator/layoutdiffusion_group_meeting_pptbench/.venv/Scripts/python.exe`。

## v3.2 可选流程意图

Story 后可由独立 DesignIntentPlanner 写 `design_intent.json`；仅支持四条
`key_points` 的纵向 `process`，可选强调其中一步。`pwf2rpa --story ... --design-intent ...`
只把关系写入 Brief metadata，不写 bbox，也不复制正文；无意图文件时仍走旧流程。
RPA 必须核对四点完整 Slot Binding 后输出 `layout_contract`，容量不足返回
`needs_replan`，硬流程组不能自动拆散。映射到 Deck IR 时，
`composition.visual_intent.members` 使用实际 block ID；编译器验证并绘制编号连线。
有一张图时用 `figure-parameters`，无图时用 `process-flow`，均保留四个完整文本块。
v26 检查点保持不变；既有节奏校正把候选框约束为同列等距，不新增排版器或整套 deck 设计 pass。

在 Total-pipe 目录执行：

```powershell
$python = 'F:/Workbuddy/ppt-generator/layoutdiffusion_group_meeting_pptbench/.venv/Scripts/python.exe'
& $python -m deck_compiler build --ir E:/pptx_re/Test1/total_pipe_fail_build/deck_ir.json `
  --out ../builds/graphene-v26 --layout-provider v26 --layout-candidates 32 `
  --layout-seed 20261007 --officecli C:/Users/Beibei/AppData/Local/OfficeCLI/officecli.exe --skip-native
```

## 边界与回退

- 主链仍为 canonical IR → 布局编译 → OfficeCLI → staging → 结构与原生验收。
- provider 只建议内容单元 bbox；编译器原有 block/figure/text 生成器负责最终元素和文字契约。
- `MODEL_PROPOSAL`、`PACKING_FALLBACK`、`COMPILER_FALLBACK` 逐页记录于 `layout_provider.json`。
- `derived/plan_to_layout.json` 同步记录逐页 `layout_provider_status`；PPTX 本身没有该 provenance，不要靠几何指纹猜测。
- Deck IR 顶层可指定 `presentation.frame_variant`。省略时有任一页请求 spacious，整套采用 spacious frame；否则整套为 default。实际选择和覆盖页见 `layout.json`。
- `figure-parameters` 的有序 block 是同级纵向组。模型候选先校正为 24 px 等距，容量允许时等高，文字较长时按所需高度分配；图像受宽度限制时收紧容器，使图注紧贴图像下方 12 px，然后重跑原有硬门禁。
- 显式 `composition.visual_intent` 的四点流程先核对成员 ID 与顺序；未声明时，单图四步、无 block 标签、角色从 `method` 经 `process-step` 到 `result` 的旧推断继续兼容。两者均增加编号与纵向连线。文本列为编号留出 56 px，v26 的容量门禁使用实际可用宽度；其他 `figure-parameters` 页面维持原呈现。
- 分布式列表等不支持内容交回原编译器；所有回退仍经过编译器检查，FAIL 不会被删除后放行。
- 模型文件必须匹配固定 SHA-256，载入使用 weights_only。文件缺失或损坏产生可追溯 FAIL。
- `layout.json` 嵌入 provider、模型与源码哈希；生成派生文件、OfficeCLI 命令和验收仍走同一 pipeline。
- 使用 `--layout-provider deterministic` 可完全回到原编译器；不导入 torch。
- 该版本不生成或伪造 PowerPoint 眼检记录。`--skip-native` 输出仅为候选，不能晋级 final。

## 运行测试

```powershell
& $python -m unittest discover -s tests -v
```

本目录已有的用户改动保留；安装前修改文件的原始内容备份到项目根目录的
`.v3-integration-backup`。根目录 `SHA256SUMS` 是 v2 来源记录，不代表 v3；
本次增量源码和模型哈希见 `V3_INTEGRATION_MANIFEST.json`。

## OfficeCLI 验收（按用户要求）

```powershell
& $python -m deck_compiler review-officecli --out ../builds/graphene-v26 `
  --officecli C:/Users/Beibei/AppData/Local/OfficeCLI/officecli.exe --render native
```

该命令重新验证 schema/结构、读取 issues/text、通过 OfficeCLI 导出每页截图，
并把截图及命令哈希绑定到 staging。存在原始 issues 时返回 REJECT（退出码 1），
不会把成功截图误报为全部验收通过，也不生成 PowerPoint UI 眼检记录。
本机未安装 OfficeCLI PDF exporter，PDF 导出不可用；逐页 PNG 可正常生成。
