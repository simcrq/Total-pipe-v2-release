# 页面设计 1.1 验证记录

日期：2026-11-05。范围是页面设计的职责、协议、证据继承与 IR 交接；本次未新编译 PPTX，
不声明新样例的几何或原生 PowerPoint 验收已通过。当前安装缓存/MCP 服务未被替换。

## 实际独立子代理

宿主通过 spawn_agent 实际创建 `/root/page_design_v11_sample`，请求模型为 `gpt-6-luna`，
reasoning_effort 为 `max`，fork_turns 为 `none`。子代理运行时不提供可独立核对的精确模型变体标签；
这里记录宿主接受的调用设置，不把自报当作额外验证。

子代理先在不读编译器能力源码的设计角色中完整读取任务书、提示包和 Schema，查看图片后生成样例。
最终提示为 40,093 字节，去掉 RPA 重复正文与二次听众分析；子代理完整重读并确认 Story/证据未变。
已有 Story 的 13 个内容路径在 10 页中各分配一次，开场页为空引用。未选用缺失的 S9/S6/S16 图像。

样例：[page_design.json](../Total-pipe/examples/page-design-v11/page_design.json)。
本机原始产物与模型报告：`build/page-design-v11/work/`；初版提示保存在 `input-history/`，
人工复核前版本与问题记录保存在 `review-history/`。

## 人工复核

主代理完整阅读实际 JSON，并核对相关原文证据及图像；要求独立作者修订两处：

- P5 移除 Story/EV0011 未给出的“正/负极性到导带/价带”具体对应，保留已给出的极性相关陈述。
- P8 在视觉设计上把 Oracle-MNIST 另一个系统评估说明与 16%→62% 的比较分隔，避免混为同一实验。

两处均由独立作者修订，主代理再次阅读修订后的 JSON；结构校验再次通过。
最终 JSON SHA-256：`71b0288d438d2f9b24e91d40fe0c1a18ab1d460217c743c98659ee16767e38a3`。

P3 的器件原图与材料功能对应，以及 P9 的 reservoir 系统原图已实际查看；
归一化说明按原 Figure 4 图注定位于分布结果，不能套在轨迹点数或 reservoir 数据上。
自由 design 文字不自动证明科学正确；其图形关系、来源及后续实际布局仍需人工与 IR QA 复核。

## 自动验证

主代理实际运行 finalize_design，确认 10 页的自定 design 与 content_refs 完整传给 IR 提示，
自动 content_catalog 包含全部 13 个内容路径，原 page_design.json 未注入重复正文 items。
本机检查记录为 `build/page-design-v11/handoff_checks.json`。

同一个独立子代理随后切换到测试角色，新增 `test_page_design_v11.py` 并更新旧任务书断言，未修改实现。
实际结果：

- 最终样例同时通过 JSON Schema 和 `check_design`（10 页，13 个内容引用各一次）。
- 新协议最终 14 项测试通过；适配器模块最终 12 项通过。
- 组合执行 113 项，唯一失败是旧任务书断言仍期待“5 条 briefs”，其余通过。
  更新为“5 条参考 briefs”后，适配器模块重跑通过；新增接线测试后，新协议模块重跑通过。
  没有把这些分次结果描述为一次全套绿灯，也没有在测试修改后重复运行整套。
- 新测试覆盖省略旧必填字段、内容遗漏/重复/未知引用、未知 EV/图片、标题数值、坏输入、
  Schema 一致性、不修改原设计、定制设计保留、IR 数值/证据/选图、原生图形与图表内容，
  以及 runner 接收、design_complete、局部修补预检三处实际绑定接线。
- 首轮测试编写曾有 `%` 断言和 mock 返回物不完整，修正测试后对应模块通过；未发现实现问题。
  接线测试使用 mock，不把它们称作真实 IR/PPT 编译。

本机详细报告：`build/page-design-v11/tests/report.md`。复现所选范围可在仓库根目录使用：

```bash
PYTHONPATH=Total-pipe:Total-pipe/pwf2rpa:Total-pipe/tests python -m unittest \
  test_page_design test_page_design_v11 test_agent_adapters test_agent_entry \
  test_agent_slimming test_agent_repair test_agent_native test_art_direction -v
```

本次使用既有 Python 3.12 虚拟环境；未新增运行时依赖，也未重跑完整仓库测试或 MinerU OCR。
