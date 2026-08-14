# 一个 handler 只碰一个 schema

[ADR-0002](./0002-business-and-observability-share-a-database.md) 定了业务与观测同库分 `app` / `obs` 两 schema，外键只能 `obs → app` 单向，业务不得 import 观测。[ADR-0007](./0007-backend-is-split-by-capability-not-by-layer.md) 把它落成一条 CI 可强制的 import 规则。

**决定：这条边界在 API 层的形态是——没有任何一个端点同时返回两个 schema 的数据。观测面与业务面在 URL 上就是分开的，需要合并的地方由前端在客户端合并。**

## 为什么这不只是列表的事

[ADR-0013](./0013-the-session-list-shows-business-facts-only.md) 已经就会话列表说过一次：列表项不得混入观测派生量。当时的理由是「公共门面不能挂在可丢的数据上」。

同一条规则往下推，会得到一个更宽的结论：**会话详情同样不能挂 trace 信息**。否则那个 handler 就得同时读 `app` 与 `obs`——业务代码 import 观测代码，ADR-0007 那条 import 规则当场破。

把它写成端点层面的通则，比逐个接口讨论「这个字段能不能加」省事，也让违规变得可检测：**一个 handler 的依赖里出现两个 repository，就是错的**。

## 端点总表

现状 `/stream_agent` 是 RPC 式动词命名，与「工程架构标准化」正面冲突。而 [ADR-0009](./0009-the-wire-format-is-ag-ui-over-sse.md) 定的「一次运行一条流，就是那个 POST 的响应体」恰好说明**运行本身就是个资源**。

| 端点 | 面 | 说明 |
|---|---|---|
| `POST /api/runs` | — | 发起运行，响应体是 SSE 流。取代 `/stream_agent` |
| `GET /api/sessions` | app | 列表，游标分页、更新时间倒序 |
| `GET /api/sessions/{id}` | app | 详情（消息序列），**不含任何观测量** |
| `PATCH /api/sessions/{id}` | app | 重命名 |
| `DELETE /api/sessions/{id}` | app | 软删 |
| `GET /api/sessions/{id}/runs` | **obs** | 该会话的运行骨架 |
| `GET /api/runs/{run_id}` | obs | 单次运行的完整跨度树 |
| `GET /api/models` | app | 模型清单 |
| `POST /api/models/refresh` | app | 自定义端「下载模型」 |
| `GET /health` | — | 现状 `/` 与 `/health` 内容完全相同，删掉前者 |

重命名从 `PUT` 改 `PATCH`：它只改标题一个字段，不是整体替换。

## 前端自己合并两侧

trace 面板要把跨度树对齐到具体消息上，这个合并**发生在客户端**：前端拿 `GET /api/sessions/{id}` 的消息序列与 `GET /api/sessions/{id}/runs` 的运行骨架，靠 `trigger_message_id` 与 `last_message_seq` 关联（#9 已定的圈定方式）。

这不是给前端添麻烦，是 ADR-0002 在接口上的**可验证形态**。服务端合并意味着某个 handler 必须同时持有两侧数据，那条 import 规则就只能靠人自觉；客户端合并则让规则在目录结构上物理成立。

代价是前端多一次请求、多一段关联逻辑。观测数据老化或写入失败时，前端拿到的是空运行骨架而消息序列完好——**这正是 ADR-0002 想要的降级形态**，业务视图不受观测缺失影响。

## 后果

- `GET /api/sessions/{id}/runs` 与 `GET /api/runs/{run_id}` 落在 `observability/` 模块的 router 里，不是 `conversation/`。
- **软删与硬删在契约上不可区分**——`DELETE` 一律 204，不提供「查看已删除」的入口。ADR-0013 定软删的理由是硬删会打断 `obs → app` 外键，那是实现约束，不是给用户的功能，不该在契约里露头。
- **削减计数**（[#25](https://github.com/EllisYuan/ChatAgents/issues/25) 交办本票裁）**进会话详情，不进列表**。它确实在 `app` schema 内（不撞 ADR-0002），但 ADR-0013 已把列表钉死在三个字段，让它当第四个会把门面变成仪表盘。放进详情则 #18 无论怎么决定「用户看不看得见瘦身」，都不用回头改契约。
- **列表的时间字段是绝对时刻（ISO 8601），不是相对时间。** #22 那句「列表项返回标题 / 相对时间 / 消息数」在此就地纠正：那是在描述界面呈现，不是契约字段。服务端返回「3 小时前」意味着这个值在响应发出的瞬间就开始腐烂，且不可缓存、时区归服务器管。相对时间由前端算。
- 不做 URL 版本化，路径就是 `/api/...`，理由见 [ADR-0024](./0024-there-is-no-url-versioning.md)。
