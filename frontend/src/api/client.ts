import type { components, paths } from "../generated/api";

type ModelsResponse =
  paths["/api/models"]["get"]["responses"][200]["content"]["application/json"];

export async function getModels(): Promise<ModelsResponse> {
  const response = await fetch("/api/models");
  if (!response.ok) {
    throw new Error(`获取模型清单失败：${response.status}`);
  }
  return (await response.json()) as ModelsResponse;
}

export type EvalSummary =
  paths["/api/evals/summary"]["get"]["responses"][200]["content"]["application/json"];

/** 站点级只读评测展示面——数据来自评测产出，不进聊天界面（ADR-0028）。 */
export async function getEvalSummary(): Promise<EvalSummary> {
  const response = await fetch("/api/evals/summary");
  if (!response.ok) {
    throw new Error(`获取评测展示数据失败：${response.status}`);
  }
  return (await response.json()) as EvalSummary;
}

export type SessionDetail = components["schemas"]["SessionDetail"];

/** 会话随第一条用户消息诞生——尚未产生消息的会话在后端不存在，404 按空历史处理。 */
export async function getSessionDetail(sessionId: string): Promise<SessionDetail | null> {
  const response = await fetch(`/api/sessions/${sessionId}`);
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`获取会话历史失败：${response.status}`);
  }
  return (await response.json()) as SessionDetail;
}

export type SessionSummary = components["schemas"]["SessionSummary"];
export type SessionView = components["schemas"]["SessionView"];

interface ListSessionsParams {
  limit?: number;
  beforeUpdatedAt?: string | null;
  beforeId?: string | null;
}

/** 会话列表侧边栏（issue #68）——按更新时间倒序、游标分页（ADR-0013）。 */
export async function listSessions(params: ListSessionsParams = {}): Promise<SessionSummary[]> {
  const query = new URLSearchParams();
  if (params.limit) {
    query.set("limit", String(params.limit));
  }
  if (params.beforeUpdatedAt) {
    query.set("before_updated_at", params.beforeUpdatedAt);
  }
  if (params.beforeId) {
    query.set("before_id", params.beforeId);
  }
  const queryString = query.toString();
  const response = await fetch(`/api/sessions${queryString ? `?${queryString}` : ""}`);
  if (!response.ok) {
    throw new Error(`获取会话列表失败：${response.status}`);
  }
  return (await response.json()) as SessionSummary[];
}

/** 鉴权整块不做（issue #68）：任何访客都能删除任何会话。 */
export async function deleteSession(sessionId: string): Promise<void> {
  const response = await fetch(`/api/sessions/${sessionId}`, { method: "DELETE" });
  if (!response.ok && response.status !== 404) {
    throw new Error(`删除会话失败：${response.status}`);
  }
}

/** 鉴权整块不做（issue #68）：任何访客都能重命名任何会话。 */
export async function renameSession(sessionId: string, title: string | null): Promise<SessionView> {
  const response = await fetch(`/api/sessions/${sessionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!response.ok) {
    throw new Error(`重命名会话失败：${response.status}`);
  }
  return (await response.json()) as SessionView;
}

export type RunSummary = components["schemas"]["RunSummary"];
export type RunDetail = components["schemas"]["RunDetail"];

/** 观测侧运行骨架（ADR-0022：观测面与业务面分开），供前端按 `last_message_seq` 与消息 `seq` 客户端合并。 */
export async function getSessionRuns(sessionId: string): Promise<RunSummary[]> {
  const response = await fetch(`/api/sessions/${sessionId}/runs`);
  if (!response.ok) {
    throw new Error(`获取运行列表失败：${response.status}`);
  }
  return (await response.json()) as RunSummary[];
}

/** 单次运行的完整跨度树——trace 面板 Layer 1 历史视图懒加载的数据源（issue #69）。 */
export async function getRunDetail(runId: string): Promise<RunDetail> {
  const response = await fetch(`/api/runs/${runId}`);
  if (!response.ok) {
    throw new Error(`获取运行详情失败：${response.status}`);
  }
  return (await response.json()) as RunDetail;
}
