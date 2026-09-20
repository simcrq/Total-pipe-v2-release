---
name: local-project-mcp-bridge
description: 把本地 Python/Node 项目包装成 MCP stdio 连接器并注册到 ~/.workbuddy/mcp.json。当用户要求"把某个本地项目安装成连接器/MCP server""给这个项目加 MCP 接口"时使用。
agent_created: true
---

# 本地项目 → MCP 连接器

## 何时用

用户说"把这个项目装成连接器""给 X 加 MCP 接口""让 Agent 能调用我这个脚本"。
目标是让本地 CLI/库项目通过 MCP 暴露工具给 WorkBuddy。

## 第一步：先找现成的桥

**不要一上来就写工具逻辑。** 先找项目里是否已有 JSON-in/JSON-out 的入口：

- 插件目录（`integrations/`、`plugins/`）里的 `bridge.py`、`index.js`
- 自带的 `agent_tools.py` / `tools.py` 等"给 Agent 用的包装层"
- CLI 的 `--json` 输出模式

多数成熟项目已有一个被别的宿主（如 DeepSeek Harness）驱动的桥。找到它，
你只需要写协议外壳，工具契约和参数校验直接沿用，不用重新设计。

```
grep -rn "def run\|operation\|json.load(sys.stdin)" --include=*.py --include=*.mjs .
ls integrations plugins
```

## 第二步：准备运行环境

先判断项目有没有第三方依赖：

- **纯标准库项目**（pyproject 的 dependencies 为空或全是 stdlib）：跳过 venv，
  `command` 直接用 managed python 的绝对路径，例如
  `C:/Users/<user>/.workbuddy/binaries/python/versions/3.13.12/python.exe`。
- **有依赖**：系统 Python 几乎总是缺包，优先用项目自带的锁文件建隔离 venv：

```bash
uv sync --frozen     # 有 uv.lock 时；通常十几秒
```

`command` 指向 `<project>/.venv/Scripts/python.exe`（Windows）
或 `<project>/.venv/bin/python`（WSL/Linux）。**不要用系统 python 裸跑**。
Node 项目同理，用 managed node 的绝对路径。

## 第三步：写 stdio 协议外壳

纯标准库即可，不要引入 mcp SDK。必须实现的方法：

| 方法 | 说明 |
|---|---|
| `initialize` | 回 `protocolVersion` / `capabilities` / `serverInfo` / `instructions` |
| `notifications/initialized` | 不回复 |
| `tools/list` | 工具数组（name + description + inputSchema） |
| `tools/call` | 调桥，返回 `{content:[{type:"text",text}], isError}` |
| `ping`、`resources/list`、`prompts/list` | 空实现，避免客户端报错 |

工具执行异常要转成 `isError: true` 的结果，**不要让 server 崩溃**。

### 工具怎么切

- **只读校验和写文件拆成两个工具**（如 `pwf2rpa_check` / `pwf2rpa_convert`）。
  Agent 先 dry-run 看警告、修好再落盘，比一把梭写坏文件强得多。
- 给每个工具配独立 `timeout`：列表/查询类 30s，常规转换 120s，
  要 spawn 外部工具链的（如调 node 重建数据表）给 600s。
- 若项目的异常本身会收集多个问题（如 pwf2rpa 的 `AdapterError.problems`），
  单独捕获并把全部问题一次性回传。**只抛第一条**会把修 bug 变成慢速猜错循环。

参考实现（两个已落地的外壳，结构一致，可直接抄）：
`F:/Workbuddy/Total-pipe/paperworkflow/integrations/mcp/server.py`
`F:/Workbuddy/pwf2rpa/integrations/mcp/server.py`

## 三个必踩的坑

1. **stdout 是协议通道。** 被调用的库和它的进度条（tqdm）、`print` 会写 stdout，
   一个字节就污染响应。执行期间把 `sys.stdout` 换成转发到 stderr 的代理对象，
   主线程保留原始 stdout 写响应 —— 这样即使超时线程残留也不会污染。
   代理要实现 `write` / `flush` / `isatty` / `fileno`。

2. **长任务必须能超时。** 在线程里跑，`join(timeout)`，超时抛错。
   超时上限用环境变量暴露（如 `PAPERWORKFLOW_TOOL_TIMEOUT`），默认给足
   （OCR/批处理类给 1800s），因为 MCP 客户端超时往往比实际任务短。

3. **路径沙箱。** 如果桥没有边界检查，自己加：解析后必须
   `path.relative_to(PROJECT_ROOT)`，否则拒绝。这是唯一挡住"读任意文件"的地方。

读 stdin 用 `sys.stdin.buffer.readline()`，同时兼容换行分隔 JSON 和
`Content-Length` 分帧（看首行是否以 `content-length` 开头）。

## 第四步：注册

`~/.workbuddy/mcp.json`（**不是** `.workbuddy/.mcp.json`）。读取现有内容后
**追加**条目，不要覆盖其他 server：

```json
"myproject": {
  "command": "F:/path/.venv/Scripts/python.exe",
  "args": ["F:/path/integrations/mcp/server.py"],
  "cwd": "F:/path",
  "disabled": false
}
```

`cwd` 要设成项目根 —— 项目里用相对路径定位资源的逻辑全靠它。
改完用 `json.load` 校验一遍合法性，并确认其他条目没被动过。

**写完配置不会自动生效**，必须告诉用户去连接器管理页对新 server 点 Trust。

## 验证清单（都要实跑，别只看代码）

```bash
printf '%s\n%s\n%s\n' \
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' \
'{"jsonrpc":"2.0","method":"notifications/initialized"}' \
'{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
| timeout 60 <python> server.py
```

1. `initialize` 返回正确的 `serverInfo`
2. `tools/list` 返回全部工具
3. `tools/call` 实跑**一个不依赖网络**的工具（列表/索引类最合适）
4. 故意传一个项目外路径，确认被拒绝且返回 `isError: true` 而不是崩掉

## 版本对齐（跨项目时）

如果本地项目还依赖另一个 MCP 服务的内部数据表，注册前先核对版本：
双方各查一次版本号和条目数（如版面数/分类数），一致才说明没漂移。
不一致就要跑该项目自带的 refresh 脚本。
