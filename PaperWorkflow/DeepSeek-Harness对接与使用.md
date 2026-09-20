# PaperWorkflow 对接 DeepSeek Harness（WSL2）

本文是当前 WSL2 部署的实际使用说明。后续命令均在 WSL 的 Bash 终端执行，不在 Windows PowerShell 中执行。

## 1. 当前目录与组件

建议准备以下相对目录结构：

~~~text
<workspace>/
├── dsh/                              # DeepSeek Harness 源码
├── dsh-anchored-standard/            # 社区 Agent preset（可选）
└── paperworkflow/                    # 本项目
    └── integrations/deepseek-harness/ # 原生 dsh bundle 插件
~~~

下文通过环境变量定位项目，不依赖发布者机器上的固定绝对路径。当前 Web profile 示例名为 `web`，插件向模型暴露两个工具：

- `paperworkflow_literature_workflow`：以项目内 PDF 或 Markdown 为入口，自动执行文献接入、检查、索引、证据检索和下游交接。
- `paperworkflow_prompt_builder`：递归索引 `INput` 下的 PDF，以相对路径和编号供用户选择，并自动生成严格的主工作流提示词。

统一工具依次执行：

1. PDF 调用配置好的 MinerU OCR/转 Markdown；Markdown 输入直接复用。
2. 提取标题、DOI、arXiv、语言和章节覆盖。
3. 分别审计 OCR/Markdown、论文结构、证据检索和数值一致性。
4. 只发现文件名或目录关系明确的补充材料。
5. 建立带 `E###`、章节和行号的 manifest，对中英文问题执行意图扩展和章节感知检索。
6. 写出工作流清单、完整证据 manifest、紧凑证据报告和科学综合就绪度。

旧的 outline、search_evidence 和 process_pdf bridge 操作继续保留，便于脚本兼容，但不再占用模型工具目录。

## 2. 初始化 WSL 环境

每次打开新的 WSL 终端，先执行：

~~~bash
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
export DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
export DSH_SOURCE="${DSH_SOURCE:-../dsh}"
export PAPERWORKFLOW_ROOT="${PAPERWORKFLOW_ROOT:-$PWD}"
export DSH_TOOLS_ENTRY="$(realpath "$DSH_SOURCE/packages/core/tools/lib/index.js")"
source "$NVM_DIR/nvm.sh"
cd "$DSH_SOURCE"
node --version
pnpm --version
~~~

本次部署使用 Node 24 和 pnpm 11。若命令提示找不到 `node` 或 `pnpm`，说明尚未加载 nvm。

## 3. 启动 Harness Web

~~~bash
source "$NVM_DIR/nvm.sh"
cd "$DSH_SOURCE"
pnpm dsh web
~~~

浏览器打开 [http://127.0.0.1:3080](http://127.0.0.1:3080)。保持该 Bash 进程运行；停止服务时在同一终端按 `Ctrl+C`。

如果只想确认 profile 的配置层，不启动服务：

~~~bash
source "$NVM_DIR/nvm.sh"
cd "$DSH_SOURCE"
pnpm dsh --profile web --dump-config | grep -n -E 'paperworkflow|paperwork'
~~~

输出中应出现：

~~~text
# == paperworkflow-dsh-plugin
- id: paperworkflow-tools
  name: paperworkflow-dsh-plugin
~~~

## 4. 安装、更新和移除插件

插件 bundle 的源码目录：

~~~text
$PAPERWORKFLOW_ROOT/integrations/deepseek-harness
~~~

首次安装或重新安装：

~~~bash
source "$NVM_DIR/nvm.sh"
cd "$DSH_SOURCE"
pnpm dsh plugin --profile web add "$PAPERWORKFLOW_ROOT/integrations/deepseek-harness"
~~~

修改插件源码后，重新执行上面的 `add`（本地 link 会指向同一目录），再重启 `pnpm dsh web`。移除：

~~~bash
source "$NVM_DIR/nvm.sh"
cd "$DSH_SOURCE"
pnpm dsh plugin --profile web remove paperworkflow-dsh-plugin
~~~

该 bundle 遵循 Harness 官方格式：`package.json` 声明 `dsh.bundle`，`cordis.patch.yml` 插入插件行，`index.js` 注册工具，`bridge.py` 负责 JSON 桥接。参考官方 [插件打包与安装文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/publish.md)。

> 启动前将 `DSH_TOOLS_ENTRY` 设置为 Harness tools 模块路径，例如 `$DSH_SOURCE/packages/core/tools/lib/index.js`。插件运行时动态加载该路径，源码中不包含机器相关绝对路径。

## 5. 直接测试 JSON bridge

不依赖模型即可测试统一工作流。输入和输出既可使用相对路径，也可使用任意本地绝对路径；发布 bundle 内部只写相对路径。

PDF 输入可能通过 MinerU 上传并执行 OCR；Markdown 输入不会调用 MinerU。两种输入都会完成后续审计、索引、证据检索和交接产物生成。

~~~bash
cd "$PAPERWORKFLOW_ROOT"

printf '%s' '{"operation":"literature_workflow","source_path":"INput/4668/paper-a.pdf","queries":["样品制备与测量条件","关键结果与局限性"],"top_k":5}' \
  | python3 integrations/deepseek-harness/bridge.py \
  | python3 -m json.tool
~~~

若已经有 Markdown，把 `source_path` 换成项目内的 `full.md`；该工具会跳过 OCR。

## 6. 在 Harness 中使用

如果还没有选定论文，先输入：

~~~text
请调用 paperworkflow_prompt_builder 列出输入目录中的全部 PDF。
~~~

返回结果只包含相对于 `INput` 的路径，例如：

~~~text
P001  300u.pdf
P002  4668/2601.11319v1.pdf
P003  e1.pdf
P004  Li.pdf
~~~

然后输入编号和研究信息：

~~~text
选择 P004，研究目标是解释结构色的制备与物理机制。
重点回答样品制备、物理图像、关键结果和局限性，请自动生成提示词。
~~~

在 Web 对话中可以直接这样要求 Agent：

~~~text
请调用 paperworkflow_literature_workflow 处理：
INput/4668/paper-a.pdf
自定义问题：样品如何制备？物理图像是什么？最关键结果和局限性是什么？
回答时遵守 workflow.json 中的 claim_ledger_contract：
1. 每个主要结论和数字分别给出 E### 与精确行号。
2. 区分实验观察、测量、模拟和推断。
3. 区分实验室、优化批次与 R2R 工艺参数。
4. 不合并不同上下文中的数值范围。
完成后返回 evidence.md、workflow.json、原始 Markdown 路径和分维度质量审计结论。
~~~

一次调用完成后：

1. `quality_audit` 只表示 OCR/Markdown 提取质量；该字段为 `review` 或 `blocked` 时先检查 OCR。
2. 科学回答以前必须检查 `synthesis_readiness`；它不是 `ready` 时要明确提示人工复核。
3. 下一个总结、比较、教程或知识库插件优先读取 `evidence.md`，需要上下文时再读取原始 Markdown。
4. 下游结论保留 `E###`、精确行号和证据类型，并使用 `workflow.json` 追溯参数与源文件哈希。

## 7. 运行完整 PaperWorkflow

PDF 放在任务 ID 子目录，例如：

~~~text
INput/4668/paper-a.pdf
~~~

先检查任务映射：

~~~bash
cd "$PAPERWORKFLOW_ROOT"
python3 main.py --dry-run
~~~

确认无误后执行：

~~~bash
python3 main.py
~~~

运行前，若 Python 工作流需要调用 DeepSeek API，在同一个 Bash 终端设置环境变量：

~~~bash
export DEEPSEEK_API_KEY='你的 DeepSeek API Key'
export OPENAI_API_KEY="$DEEPSEEK_API_KEY"
~~~

不要把真实 Key 写入 `config.yaml`、Markdown、manifest 或 Git。

MinerU 建议使用官方 CLI 管理认证：

~~~bash
curl --compressed -fsSL https://cdn-mineru.openxlab.org.cn/open-api-cli/install.sh -o /tmp/mineru-open-api-install.sh
INSTALL_DIR="$HOME/.local/bin" sh /tmp/mineru-open-api-install.sh
mineru-open-api auth
# 配置中的 api.mineru.ocr 已设为 true；统一工作流处理 PDF 时会把它转换为官方 CLI 的 --ocr 参数。
~~~

PaperWorkflow 默认的 `official_cli` 后端会调用该 CLI；旧的手写 HTTP 适配器只在明确配置 `legacy_http: true` 时启用。

## 8. 输出与证据接口

统一工具成功后通常生成：

~~~text
temp_markdowns/<cache>/.../full.md
output/workflows/<source fingerprint>/
├── workflow.json
├── document.manifest.json
└── evidence.md
~~~

workflow.json 记录阶段状态、文件哈希、参数、分维度质量审计、检索诊断、数值范围和主张证据契约；document.manifest.json 保存完整的行号证据块；evidence.md 是供下一个插件优先读取的紧凑上下文。原始 Markdown 是最终核查入口。

传统 python3 main.py 批处理仍会生成 Summary_<mode>_<filename>.md 和同名 manifest。Python 代码可直接调用 utils/literature_workflow.py 中的 build_literature_workflow。

## 9. 常见问题

### 工具没有出现在对话中

确认安装命令成功、`dump-config` 中有插件层，然后完全停止并重新启动 `pnpm dsh web`。正在运行的 Harness 不会自动重新加载 bundle 入口文件。

### bridge 报 source_path 或 file not found

确认路径存在且扩展名是 `.pdf` 或 `.md`。Markdown 可先这样查找：

~~~bash
find "$PAPERWORKFLOW_ROOT/temp_markdowns" -type f -name '*.md' | head
~~~

### Harness 能聊天，但 Python 工作流报 API Key 缺失

Harness 页面保存的模型凭证与 Python 子进程环境变量是两套配置。请在启动 Harness 的同一个 Bash 终端设置 `DEEPSEEK_API_KEY` 和 `OPENAI_API_KEY`。

### Node 或 pnpm 找不到

重新执行：

~~~bash
source "$NVM_DIR/nvm.sh"
node --version
pnpm --version
~~~

### 需要开发或更新 Harness 本身

~~~bash
cd "$DSH_SOURCE"
pnpm install
pnpm run build
~~~

不要修改 Windows 工作区；本部署的代码和 profile 都在 WSL 路径。

## 10. 最小验收清单

~~~bash
cd "$PAPERWORKFLOW_ROOT"
python3 -m py_compile utils/literature_workflow.py integrations/deepseek-harness/bridge.py
python3 -m unittest discover -s tests -v
# 直接 bridge 示例见第 5 节。

cd "$DSH_SOURCE"
source "$NVM_DIR/nvm.sh"
pnpm dsh --profile web --dump-config | grep -n paperwork
curl -fsSI http://127.0.0.1:3080
~~~

通过 bridge、profile 和 HTTP 三项检查，就完成了当前 WSL 部署的插件级接入。

## 11. 参考资料

- [DeepSeek Harness 官方仓库](https://github.com/deepseek-ai/deepseek-harness)
- [Harness Web UI 使用说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/index.md)
- [Harness 工具插件开发](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/tool.zh.md)
- [Harness 插件打包安装](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/publish.md)
- [DeepSeek API 文档](https://api-docs.deepseek.com/zh-cn/)
- [MinerU 官方 Open API CLI](https://github.com/opendatalab/MinerU-Ecosystem/blob/main/cli/mineru-open-api/README.zh-CN.md)
