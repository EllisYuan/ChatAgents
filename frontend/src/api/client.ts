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
