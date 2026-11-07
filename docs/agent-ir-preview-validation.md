# IR 选页预览验证记录

日期：2026-11-06。独立开发分支 `codex/audience-preview-loop`，基线 `f82b3b9`。
本记录仅覆盖草稿渲染反馈，不是论文 PPTX 的最终验收，不是 OCR 到交付的速度基准。

## 实现范围

四工具仍为 doctor/start/advance/status；advance 新增独立 preview 请求。
从 work/ 的一页或整套 canonical IR 选页，经原来源绑定、原科学/设计校验和 compiler/packer 测量，
用 OfficeCLI 生成独立 PPTX 并通过 officecli-html 输出 PNG。完整协议见
[接入层用法](../Total-pipe/docs/agent-adapter.md#ir-选页渲染与看图修订)。

不会接受产物、消费修订额度、推进阶段、写入 build/ 或改写正式候选/QA。
FAIL 原样报告，有可编译布局时可以生成明确带 FAIL 结果的调试图。没有任何预览被签收为 PowerPoint UI review。
没有修改 Deck IR、页面设计 Schema、编译器或质量门禁。

## 自动回归

在 Total-pipe/ 使用已有虚拟环境执行：

```bash
python -m unittest discover -s tests -p 'test_agent_ir_*.py' -v
python -m unittest discover -s tests -p 'test_agent_entry.py' -v
```

- 逐页 IR、IR 预检及新预览回归共 **22 项通过**（其中新预览 7 项）。
- 接入层入口回归 **9 项通过**，包含实际 OfficeCLI 候选构建和恢复路径。
- 新预览单元测试使用显式模拟渲染器，验证状态隔离、未变页复用、缓存损坏、源文件和资源并发变化、
  路径约束、未知页、FAIL 保留及拒绝混合提交。这些测试不冒充真实浏览器渲染。

## 真实渲染与实际看图

以当前论文 IR 的开发验证副本选 P01/P10/P19，用实际 OfficeCLI + 本机浏览器截图；三张 PNG 均已打开查看。
首次在受限沙箱中浏览器启动失败，保留了实际错误；获得本机进程启动权限后成功，并未伪造预览。
随后仅在验证副本将 P10 图表来源标签由内部证据键改为论文图号引文，数值、单位和 evidence_refs 未改；
再次渲染、打开新图，确认新引文出现且 P19 复用。原任务 IR 的 SHA-256 在这次验证前后相同。

| 本机操作 | 实测耗时 | 结果 |
| --- | --- | --- |
| 首次 P01 | 7.206 s | 1 页新渲染，0 FAIL / 0 WARNING |
| 首次 P10 + P19 | 10.877 s | 2 页新渲染，0 FAIL / 0 WARNING |
| P01 + P10 + P19 未改再次预览 | 1.774 s | 3 页均复用缓存 |
| 看图后仅改验证副本的 P10，再预览 P10 + P19 | 6.987 s | P10 新渲染，P19 复用 |

这些耗时包含本机校验与渲染/缓存操作，不包含模型写作和人工复核；单次小样本不支持整链提速倍率。
原始结果在本地忽略的 `build/ir-preview-validation/result-1.json` 至 `result-4.json`。
后续新增的缓存读取中资源变更防护已通过上述回归测试。

## 保留的限制

- HTML 与 PowerPoint 对中文字体、公式、形状和表格换行的渲染可能不同；P10/P19 的 HTML 截图右侧还可见
  滚动条。它们用于发现草稿问题，不作干净的最终页面预览或原生验收。
- 单页预览页码从头计，生成目录页省略；篇级 Design 合入前的图只表示当前草稿。
- 最终候选仍整套生成，未做 OfficeCLI 候选增量拼装，完整结构 QA 和原生验收仍必需。
- 这份预览验证不证明论文文案已修复。随后实现的职责/校验重构见[内容契约](../Total-pipe/docs/content-projection.md)；
  预览功能本身不评价语义忠实性，也不以追加“说人话”提示或关键词搬移来宣称完成。
- 该分支尚未安装到当前论文任务所用服务；不会因开发代码指纹变化使其检查点失效。
