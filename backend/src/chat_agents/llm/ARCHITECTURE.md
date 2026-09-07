# LLM 模型访问层

## 职责

`llm/` 把三类供应商协议收敛为稳定的 `ModelPort`、`ModelMessage` 与 `ModelEvent`。端点档案决定协议与鉴权，模型名称由用户选择并通过运行时发现获得，不在代码中维护静态清单。

## 入口与边界

- `port.py::ModelPort`：项目其余部分调用模型的唯一接口；`model_port_scope` 绑定它的 HTTP 客户端生命周期。
- `adapters/`：Anthropic Messages、OpenAI Chat Completions、OpenAI Responses 三套独立适配器。
- `message.py` / `events.py`：供应商无关的输入块与流式事件。
- `profile.py::EndpointProfile`：一次调用的完整接入配置。
- `override.py::ModelOverride` / `resolve.py::resolve_profiles`：服务端预设打底、用户逐字段覆盖，产出一份 `EndpointProfile` 加两个模型标识。
- `model_discovery.py`：端点模型清单的运行时发现。
- `replay.py`：在 `ModelPort` 边界录制和确定性回放。

## 依赖方向

`llm/` 是共享叶子：不得依赖 `agent/`、`conversation/`、`observability/`、`transport/` 或 `tools/`。三协议契约测试必须能在零数据库、零 FastAPI 条件下运行。

## 不变量

1. 上层只消费统一消息和事件，不读取供应商 SDK chunk。
2. 协议属于端点档案，不从模型名猜测。
3. 模型由用户选定：`resolve_profiles` 的覆盖逐字段生效，未覆盖的字段才落回预设；用户自带端点时服务端密钥一个字段都不参与。
4. 访客自带的端点不进进程级客户端缓存，客户端随运行创建与关闭。
5. 上游错误原样透传，不映射为项目错误码。
6. 用量只有 `complete` / `partial` / `unavailable` 三态，缺失不以 0 表示。
7. 回放录制 `ModelEvent`，不录 HTTP 帧和鉴权信息。

## 决策来源

[ADR-0014](../../../../docs/adr/0014-the-model-is-chosen-by-the-user-never-by-the-system.md) · [ADR-0015](../../../../docs/adr/0015-upstream-errors-pass-through-unclassified.md) · [ADR-0016](../../../../docs/adr/0016-the-model-list-is-discovered-and-persisted.md) · [ADR-0020](../../../../docs/adr/0020-there-is-one-token-yardstick.md) · [ADR-0025](../../../../docs/adr/0025-replay-happens-at-the-model-port-not-the-http-transport.md)
