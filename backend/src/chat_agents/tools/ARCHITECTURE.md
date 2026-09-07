# Tools 工具能力层

## 职责

`tools/` 定义 Agent 可调用的能力、工具契约和供应商 Port。工具实现是干净的异步函数；超时、重试、跨度和错误呈现由 `agent.ToolExecutor` 统一提供。

## 入口与边界

- `registry.py::TOOL_SPECS`：工具唯一注册表和模型工具定义来源。
- `types.py::ToolSpec` / `ToolResult` / `ToolExecutionContext`：零供应商依赖的共享契约。
- `web_search/`：Tavily 搜索 Port 与结果编排。
- `web_reader/`：Jina Reader Port、Markdown 结构化和渐进式披露。

## 依赖方向

`tools/` 是共享叶子，不得依赖 `agent/`、`llm/`、`conversation/` 或 `observability/`。它通过 `ToolExecutionContext` 的结构接口使用运行内 HTTP 客户端和记忆化，不认识具体实现。

## 不变量

1. 工具定义只在 `TOOL_SPECS` 写一次，协议序列化归 `llm/`。
2. 工具返回同时提供模型文本与结构化结果，二者用途不混用。
3. 外部失败交回模型，程序错误向上抛；工具自身不实现重试。
4. 长文档先返回结构，再由 Agent 按章节索取；不得静默硬截断或用二级模型摘要。

## 决策来源

[ADR-0004](../../../../docs/adr/0004-tools-are-capabilities-providers-are-implementations.md) · [ADR-0005](../../../../docs/adr/0005-long-documents-use-progressive-disclosure.md) · [ADR-0006](../../../../docs/adr/0006-tool-failures-split-into-external-and-programmatic.md)
