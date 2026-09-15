import { create } from "zustand";

import type { components } from "../generated/api";

type Protocol = components["schemas"]["ModelRefreshRequest"]["protocol"];
type ModelItem = components["schemas"]["ModelItemView"];
type ModelOverride = components["schemas"]["ModelOverride"];
export type EffortTier = components["schemas"]["RunRequest"]["effort"];

/** 选中「自定义端点」时的哨兵值——不是一个真实的服务端档案名。 */
export const CUSTOM_PROFILE = "__custom__";
/** 配置只写浏览器 localStorage，不写共享后端；apiKey 也不进入日志或共享状态。 */
const STORAGE_KEY = "chatagents:model-options:v1";
const PROTOCOLS: Protocol[] = ["openai_responses", "openai_chat_completions", "anthropic_messages"];
const EFFORTS: EffortTier[] = ["low", "medium", "high", "xhigh"];

export interface CustomEndpointFields {
  protocol: Protocol;
  baseUrl: string;
  authField: string;
  apiKey: string;
  /** false：地址是服务前缀，根地址自动补 `/v1`；true：地址就是最终生成 URL。 */
  fullUrl: boolean;
}

interface CustomCatalog {
  models: ModelItem[];
  source: "discovered" | "fallback";
  error: string | null;
}

export interface SessionModelConfig {
  profileChoice: string | null;
  custom: CustomEndpointFields;
  mainModel: string;
  auxiliaryModel: string;
  auxiliaryFollowsMain: boolean;
  mainModelTouched: boolean;
  customMainModel: string;
  customAuxiliaryModel: string;
  customAuxiliaryFollowsMain: boolean;
  customMainModelTouched: boolean;
  effort: EffortTier;
}

interface PersistedState {
  latest: SessionModelConfig | null;
  sessions: Record<string, SessionModelConfig>;
}

interface ModelOptionsState {
  profileChoice: string | null;
  setProfileChoice: (choice: string) => void;
  /** 服务端的 `default_profile`——判断「档案是否偏离默认」的参照物（issue #82）。 */
  defaultProfile: string | null;
  setDefaultProfile: (name: string) => void;
  setSystemDefault: () => void;

  custom: CustomEndpointFields;
  setCustomField: <K extends keyof CustomEndpointFields>(field: K, value: CustomEndpointFields[K]) => void;

  customCatalog: CustomCatalog | null;
  customStatus: "idle" | "loading" | "error";
  customErrorMessage: string | null;
  /** 发现、接入字段修改与 Session 恢复共用一个序号；不持久化。 */
  customConnectionRevision: number;
  startCustomRefresh: () => number;
  finishCustomRefresh: (revision: number, result: CustomCatalog | string) => void;
  setCustomCatalog: (catalog: CustomCatalog | null) => void;
  setCustomStatus: (status: "idle" | "loading" | "error", errorMessage?: string | null) => void;

  mainModel: string;
  setMainModel: (value: string) => void;
  auxiliaryModel: string;
  setAuxiliaryModel: (value: string) => void;
  auxiliaryFollowsMain: boolean;
  mainModelTouched: boolean;
  customMainModel: string;
  customAuxiliaryModel: string;
  customAuxiliaryFollowsMain: boolean;
  customMainModelTouched: boolean;
  prefillFromProfile: (mainModel: string | null, auxiliaryModel: string | null) => void;
}

const DEFAULT_CUSTOM: CustomEndpointFields = {
  protocol: "openai_responses",
  baseUrl: "",
  authField: "Authorization",
  apiKey: "",
  fullUrl: false,
};

export const useModelOptionsStore = create<ModelOptionsState>((set, get) => ({
  profileChoice: null,
  setProfileChoice: (choice) =>
    set((state) => {
      if (choice === CUSTOM_PROFILE && state.profileChoice !== CUSTOM_PROFILE) {
        return {
          profileChoice: choice,
          mainModel: state.customMainModel,
          auxiliaryModel: state.customAuxiliaryModel,
          auxiliaryFollowsMain: state.customAuxiliaryFollowsMain,
          mainModelTouched: state.customMainModelTouched,
        };
      }
      if (state.profileChoice === CUSTOM_PROFILE && choice !== CUSTOM_PROFILE) {
        return {
          profileChoice: choice,
          customMainModel: state.mainModel,
          customAuxiliaryModel: state.auxiliaryModel,
          customAuxiliaryFollowsMain: state.auxiliaryFollowsMain,
          customMainModelTouched: state.mainModelTouched,
          mainModel: choice === state.defaultProfile ? "" : state.mainModel,
          auxiliaryModel: choice === state.defaultProfile ? "" : state.auxiliaryModel,
          auxiliaryFollowsMain: choice === state.defaultProfile ? true : state.auxiliaryFollowsMain,
          mainModelTouched: choice === state.defaultProfile ? false : state.mainModelTouched,
        };
      }
      if (choice === state.defaultProfile) {
        return {
          profileChoice: choice,
          mainModel: "",
          auxiliaryModel: "",
          auxiliaryFollowsMain: true,
          mainModelTouched: false,
        };
      }
      return { profileChoice: choice };
    }),
  defaultProfile: null,
  setDefaultProfile: (name) =>
    set((state) => {
      if (name === state.defaultProfile) return state;
      const wasSystemDefault = state.profileChoice === null || state.profileChoice === state.defaultProfile;
      return wasSystemDefault
        ? {
            defaultProfile: name,
            profileChoice: null,
            mainModel: "",
            auxiliaryModel: "",
            auxiliaryFollowsMain: true,
            mainModelTouched: false,
          }
        : { defaultProfile: name };
    }),
  setSystemDefault: () =>
    set((state) => ({
      profileChoice: state.defaultProfile,
      customMainModel: state.profileChoice === CUSTOM_PROFILE ? state.mainModel : state.customMainModel,
      customAuxiliaryModel: state.profileChoice === CUSTOM_PROFILE ? state.auxiliaryModel : state.customAuxiliaryModel,
      customAuxiliaryFollowsMain: state.profileChoice === CUSTOM_PROFILE ? state.auxiliaryFollowsMain : state.customAuxiliaryFollowsMain,
      customMainModelTouched: state.profileChoice === CUSTOM_PROFILE ? state.mainModelTouched : state.customMainModelTouched,
      mainModel: "",
      auxiliaryModel: "",
      auxiliaryFollowsMain: true,
      mainModelTouched: false,
    })),

  custom: DEFAULT_CUSTOM,
  setCustomField: (field, value) =>
    set((state) => {
      if (state.custom[field] === value) return state;
      return {
        custom: { ...state.custom, [field]: value },
        customCatalog: null,
        customStatus: "idle",
        customErrorMessage: null,
        customConnectionRevision: state.customConnectionRevision + 1,
      };
    }),
  customCatalog: null,
  customStatus: "idle",
  customErrorMessage: null,
  customConnectionRevision: 0,
  startCustomRefresh: () => {
    const revision = get().customConnectionRevision + 1;
    set({ customConnectionRevision: revision, customCatalog: null, customStatus: "loading", customErrorMessage: null });
    return revision;
  },
  finishCustomRefresh: (revision, result) =>
    set((state) => {
      if (revision !== state.customConnectionRevision || state.customStatus !== "loading") return state;
      return typeof result === "string"
        ? { customStatus: "error", customErrorMessage: result }
        : { customCatalog: result, customStatus: "idle", customErrorMessage: null };
    }),
  setCustomCatalog: (catalog) => set({ customCatalog: catalog }),
  setCustomStatus: (status, errorMessage = null) => set({ customStatus: status, customErrorMessage: errorMessage }),

  mainModel: "",
  mainModelTouched: false,
  customMainModel: "",
  customAuxiliaryModel: "",
  customAuxiliaryFollowsMain: true,
  customMainModelTouched: false,
  setMainModel: (value) =>
    set((state) =>
      state.auxiliaryFollowsMain
        ? {
            mainModel: value,
            auxiliaryModel: value,
            mainModelTouched: true,
            ...(state.profileChoice === CUSTOM_PROFILE
              ? { customMainModel: value, customAuxiliaryModel: value, customMainModelTouched: true }
              : {}),
          }
        : {
            mainModel: value,
            mainModelTouched: true,
            ...(state.profileChoice === CUSTOM_PROFILE ? { customMainModel: value, customMainModelTouched: true } : {}),
          },
    ),
  auxiliaryModel: "",
  setAuxiliaryModel: (value) =>
    set((state) => ({
      auxiliaryModel: value,
      auxiliaryFollowsMain: false,
      ...(state.profileChoice === CUSTOM_PROFILE
        ? { customAuxiliaryModel: value, customAuxiliaryFollowsMain: false }
        : {}),
    })),
  auxiliaryFollowsMain: true,
  prefillFromProfile: (mainModel, auxiliaryModel) =>
    set((state) => {
      if (state.profileChoice === CUSTOM_PROFILE || state.mainModelTouched || !mainModel) return {};
      return {
        mainModel,
        auxiliaryModel: state.auxiliaryFollowsMain ? (auxiliaryModel ?? mainModel) : state.auxiliaryModel,
      };
    }),
}));

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * 补齐 v1 存量配置里没有的 `fullUrl`（issue #83 的地址模式）。
 *
 * 判据是「这份配置以前实际会打到哪个 URL」，不是「哪种写法更好看」：
 * 旧的 Anthropic 非根地址，SDK 当时会在它后面拼 `/v1/messages`，而新的自动模式
 * 只拼 `/messages`——直接留在自动模式会悄悄改掉一个本来能用的地址。把它转成完整
 * URL 才是等价的。旧的根地址与 OpenAI 前缀两种模式下目标一致，留在自动模式即可，
 * 根地址还顺带拿到用户要的自动补全。
 */
function migrateAddressMode(custom: Record<string, unknown>): boolean {
  if (typeof custom.fullUrl === "boolean") return custom.fullUrl;
  const baseUrl = typeof custom.baseUrl === "string" ? custom.baseUrl.trim() : "";
  if (custom.protocol !== "anthropic_messages" || !baseUrl) return false;
  try {
    const path = new URL(baseUrl).pathname;
    return path !== "" && path !== "/";
  } catch {
    return false;
  }
}

function migrateBaseUrl(custom: Record<string, unknown>, fullUrl: boolean): string {
  const baseUrl = typeof custom.baseUrl === "string" ? custom.baseUrl : "";
  if (typeof custom.fullUrl === "boolean" || !fullUrl) return baseUrl;
  // 只有上面那条 Anthropic 分支会走到这里：补上 SDK 当时真正会追加的资源路径。
  const trimmed = baseUrl.trim();
  return trimmed.endsWith("/") ? `${trimmed}v1/messages` : `${trimmed}/v1/messages`;
}

function parseConfig(value: unknown): SessionModelConfig | null {
  if (!isRecord(value) || (typeof value.profileChoice !== "string" && value.profileChoice !== null)) return null;
  if (!isRecord(value.custom)) return null;
  const custom = value.custom;
  const fullUrl = migrateAddressMode(custom);
  if (
    !PROTOCOLS.includes(custom.protocol as Protocol) ||
    typeof custom.baseUrl !== "string" ||
    typeof custom.authField !== "string" ||
    typeof custom.apiKey !== "string" ||
    typeof value.mainModel !== "string" ||
    typeof value.auxiliaryModel !== "string" ||
    typeof value.auxiliaryFollowsMain !== "boolean" ||
    typeof value.mainModelTouched !== "boolean" ||
    typeof value.customMainModel !== "string" ||
    typeof value.customAuxiliaryModel !== "string" ||
    typeof value.customAuxiliaryFollowsMain !== "boolean" ||
    typeof value.customMainModelTouched !== "boolean" ||
    !EFFORTS.includes(value.effort as EffortTier)
  ) return null;
  return {
    profileChoice: value.profileChoice,
    custom: {
      protocol: custom.protocol as Protocol,
      baseUrl: migrateBaseUrl(custom, fullUrl),
      authField: custom.authField,
      apiKey: custom.apiKey,
      fullUrl,
    },
    mainModel: value.mainModel,
    auxiliaryModel: value.auxiliaryModel,
    auxiliaryFollowsMain: value.auxiliaryFollowsMain,
    mainModelTouched: value.mainModelTouched,
    customMainModel: value.customMainModel,
    customAuxiliaryModel: value.customAuxiliaryModel,
    customAuxiliaryFollowsMain: value.customAuxiliaryFollowsMain,
    customMainModelTouched: value.customMainModelTouched,
    effort: value.effort as EffortTier,
  };
}

function readPersisted(): PersistedState {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { latest: null, sessions: {} };
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed) || !isRecord(parsed.sessions)) return { latest: null, sessions: {} };
    const sessions: Record<string, SessionModelConfig> = {};
    for (const [id, config] of Object.entries(parsed.sessions)) {
      const valid = parseConfig(config);
      if (valid) sessions[id] = valid;
    }
    return { latest: parseConfig(parsed.latest), sessions };
  } catch {
    return { latest: null, sessions: {} };
  }
}

function writePersisted(value: PersistedState): boolean {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function buildSessionModelConfig(state: ModelOptionsState, effort: EffortTier): SessionModelConfig {
  return {
    profileChoice: state.profileChoice,
    custom: { ...state.custom },
    mainModel: state.mainModel,
    auxiliaryModel: state.auxiliaryModel,
    auxiliaryFollowsMain: state.auxiliaryFollowsMain,
    mainModelTouched: state.mainModelTouched,
    customMainModel: state.customMainModel,
    customAuxiliaryModel: state.customAuxiliaryModel,
    customAuxiliaryFollowsMain: state.customAuxiliaryFollowsMain,
    customMainModelTouched: state.customMainModelTouched,
    effort,
  };
}

export function applySessionModelConfig(config: SessionModelConfig): void {
  useModelOptionsStore.setState({
    profileChoice: config.profileChoice,
    custom: { ...config.custom },
    mainModel: config.mainModel,
    auxiliaryModel: config.auxiliaryModel,
    auxiliaryFollowsMain: config.auxiliaryFollowsMain,
    mainModelTouched: config.mainModelTouched,
    customMainModel: config.customMainModel,
    customAuxiliaryModel: config.customAuxiliaryModel,
    customAuxiliaryFollowsMain: config.customAuxiliaryFollowsMain,
    customMainModelTouched: config.customMainModelTouched,
    customCatalog: null,
    customStatus: "idle",
    customErrorMessage: null,
    customConnectionRevision: useModelOptionsStore.getState().customConnectionRevision + 1,
  });
}

function resetSessionModelConfig(): void {
  useModelOptionsStore.setState({
    profileChoice: null,
    custom: { ...DEFAULT_CUSTOM },
    mainModel: "",
    auxiliaryModel: "",
    auxiliaryFollowsMain: true,
    mainModelTouched: false,
    customMainModel: "",
    customAuxiliaryModel: "",
    customAuxiliaryFollowsMain: true,
    customMainModelTouched: false,
    customCatalog: null,
    customStatus: "idle",
    customErrorMessage: null,
    customConnectionRevision: useModelOptionsStore.getState().customConnectionRevision + 1,
  });
}

/** 恢复当前会话；新草稿才允许继承最近一次有效发送的配置。 */
export function restoreSessionModelConfig(sessionId: string, existingSession: boolean): SessionModelConfig | null {
  const persisted = readPersisted();
  const config = persisted.sessions[sessionId] ?? (!existingSession ? persisted.latest : null);
  if (config) applySessionModelConfig(config);
  else resetSessionModelConfig();
  return config;
}

/** 仅在前端完整性校验通过后调用；写失败由调用方向用户如实提示。 */
export function persistSessionModelConfig(sessionId: string, config: SessionModelConfig): boolean {
  const persisted = readPersisted();
  persisted.sessions[sessionId] = config;
  persisted.latest = config;
  return writePersisted(persisted);
}

export type ModelOverrideDecision =
  | { kind: "none" }
  | { kind: "override"; override: ModelOverride }
  | { kind: "incomplete"; missing: string };

/** 只在偏离默认时产出覆盖；incomplete 与 none 必须保持可区分。 */
export function buildModelOverride(state: ModelOptionsState): ModelOverrideDecision {
  const main = state.mainModel.trim();
  const auxiliary = state.auxiliaryModel.trim();
  if (state.profileChoice === CUSTOM_PROFILE) {
    const baseUrl = state.custom.baseUrl.trim();
    const missing = [baseUrl ? null : "base URL", state.custom.apiKey.trim() ? null : "密钥", main ? null : "main 模型标识"].filter(
      (field): field is string => field !== null,
    );
    if (missing.length > 0) return { kind: "incomplete", missing: missing.join("、") };
    return {
      kind: "override",
      override: {
        protocol: state.custom.protocol,
        base_url: baseUrl,
        full_url: state.custom.fullUrl,
        auth_field: state.custom.authField.trim() || "Authorization",
        api_key: state.custom.apiKey,
        main_model: main,
        auxiliary_model: auxiliary && auxiliary !== main ? auxiliary : null,
      },
    };
  }
  const override: ModelOverride = {};
  if (state.profileChoice !== null && state.profileChoice !== state.defaultProfile) override.endpoint_profile = state.profileChoice;
  if (main && state.mainModelTouched) override.main_model = main;
  if (auxiliary && !state.auxiliaryFollowsMain && auxiliary !== main) override.auxiliary_model = auxiliary;
  return Object.keys(override).length > 0 ? { kind: "override", override } : { kind: "none" };
}
