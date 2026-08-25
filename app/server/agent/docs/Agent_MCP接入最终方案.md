# Agent MCP 接入说明

本目录原有文档描述的是 Agent 模块自行管理 MCP 工具的旧方案，该方案已经停止继续演进。

当前统一方案请查看项目级文档：

```text
docs/MCP接入AI-backend方案.md
```

当前关键结论：

- MCP Platform 已建立为 AI-backend 内与 Knowledge 平级的 `app/server/fastmcp` 大模块。
- Agent 内部 MCP 只负责发现 MCP Tool、转换为 LangChain Tool 并在运行时调用。
- MCP 管理代码已迁移到 FastMCP 模块；HTTP API 转换、发布和审计能力将在该模块继续建设。
- 第一阶段直接使用 MCP 工具 `name` 作为全局唯一标识。
- MCP 数据统一使用 PostgreSQL `mcp` Schema。
- 当前工具表为 `mcp.mcp_tools`。
