import type { components } from "../../generated/api";

type ModelProtocol = components["schemas"]["ModelRefreshRequest"]["protocol"];

/** 与后端 `endpoint_address.AddressMode` 同名同义，只是前端不需要 `sdk_native`。 */
export type AddressMode = "auto" | "full";

export interface EndpointDescription {
  discoveryPath: string | null;
  generationPath: string;
}

const INVALID_ENDPOINT_MESSAGE = "请求地址不是可接受的 HTTP(S) URL";
export const DISCOVERY_UNAVAILABLE_HINT =
  "完整 URL 未包含可识别的生成路径，无法推导模型清单地址；请手动填写模型标识";

const OPERATION_PATHS: Record<ModelProtocol, string> = {
  openai_responses: "responses",
  openai_chat_completions: "chat/completions",
  anthropic_messages: "messages",
};

/**
 * 只做本地形态校验；不把用户输入拼进错误，避免把 host、凭据或 query 回显到界面。
 */
export function validateEndpointUrl(value: string): string | null {
  const trimmed = value.trim();
  const hasControlCharacter = [...trimmed].some((character) => {
    const code = character.charCodeAt(0);
    return code < 0x20 || code === 0x7f;
  });
  if (!/^https?:\/\//i.test(trimmed) || hasControlCharacter || trimmed.includes("?") || trimmed.includes("#")) {
    return INVALID_ENDPOINT_MESSAGE;
  }

  try {
    const parsed = new URL(trimmed);
    if ((parsed.protocol !== "http:" && parsed.protocol !== "https:") || !parsed.hostname) {
      return INVALID_ENDPOINT_MESSAGE;
    }
    if (parsed.username || parsed.password) {
      return INVALID_ENDPOINT_MESSAGE;
    }
  } catch {
    return INVALID_ENDPOINT_MESSAGE;
  }

  return null;
}

function joinPath(path: string, suffix: string): string {
  return path.endsWith("/") ? `${path}${suffix}` : `${path}/${suffix}`;
}

/** 取出原始 path：WHATWG URL 会把 `%2e%2e` 折叠成 `..`，而 SDK 按字面发送。 */
function rawPathname(value: string): string {
  const rawPath = value.trim().replace(/^https?:\/\/[^/]+/i, "");
  if (!rawPath) return "";
  return new URL(`https://preview.invalid${rawPath.replaceAll("%", "%25")}`).pathname.replaceAll("%25", "%");
}

/**
 * 界面预览——只展示 path，不展示 origin、凭据或 query。
 *
 * 规则必须与后端 `endpoint_address.py` 逐条一致，两边共用
 * `backend/tests/fixtures/endpoint_address_cases.json` 校对；这里只负责显示，
 * 真正发出的地址仍由后端解析。
 */
export function describeEndpoint(
  protocol: ModelProtocol,
  value: string,
  mode: AddressMode = "auto",
): EndpointDescription | null {
  if (validateEndpointUrl(value)) return null;

  const path = rawPathname(value);
  const operation = OPERATION_PATHS[protocol];

  if (mode === "full") {
    const generationPath = path || "/";
    const candidate = generationPath.endsWith("/") ? generationPath.slice(0, -1) : generationPath;
    const suffix = `/${operation}`;
    const prefix = candidate.endsWith(suffix) ? candidate.slice(0, -operation.length) : null;
    return {
      generationPath,
      discoveryPath: prefix === null ? null : joinPath(prefix, "models"),
    };
  }

  // 只有根地址补版本段；已有 path 是用户写好的 API 前缀，原样保留。
  const prefix = path === "" || path === "/" ? "/v1" : path;
  return { generationPath: joinPath(prefix, operation), discoveryPath: joinPath(prefix, "models") };
}
