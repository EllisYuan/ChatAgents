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
