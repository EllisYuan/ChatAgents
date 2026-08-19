import type { paths } from "../generated/api";

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
