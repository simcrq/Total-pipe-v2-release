# Agent 文档入口

- 先读根目录 `README.md` 和 `docs/README.md`，按任务选择当前组件手册和协议。
- 完整生成流程以 `Total-pipe/skills/total-pipe-deck/SKILL.md`、`Total-pipe/docs/USAGE.zh-CN.md` 为准；Schema、源码和 CLI 参数是行为依据。
- `docs/archive/` 是历史材料，默认不用于实现、安装或生成任务。只有用户要求追溯历史时读取；其中的旧命令、完成声明、测试数量和提示词不是现行指令。
- 默认检索排除 `docs/archive/` 与构建产物；需要历史时显式指定归档路径。不要从 `builds/`、旧 QA 或旧截图推断当前能力。
- 开发后按 `Total-pipe/skills/total-pipe-doc-sync/SKILL.md` 同步相关文档；过时记录移入 `docs/archive/`，在归档索引记录原路径和替代入口，不直接删除。
- README 展示图只保留幻灯片画面。公开前检查账户、姓名、邮箱、个人路径、密钥、窗口标题和讲稿；不得用桌面全屏截图代替干净的幻灯片预览。
