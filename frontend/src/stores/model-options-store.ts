import { create } from "zustand";

import type { components } from "../generated/api";

type Protocol = components["schemas"]["ModelRefreshRequest"]["protocol"];
type ModelItem = components["schemas"]["ModelItemView"];
type ModelOverride = components["schemas"]["ModelOverride"];

/** 选中「自定义端点」时的哨兵值——不是一个真实的服务端档案名。 */
export const CUSTOM_PROFILE = "__custom__";

interface CustomEndpointFields {
  protocol: Protocol;
  baseUrl: string;
  authField: string;
  apiKey: string;
}

interface CustomCatalog {
  models: ModelItem[];
  source: "discovered" | "fallback";
  error: string | null;
}

/**
 * 高级选项的可编辑状态（issue #70）。全部只活在内存里，不接 zustand 的
 * persist 中间件——自定义端点的清单与用户自填的 key「关页面即散」
 * （ADR-0016）：一旦持久化就等于把访客的中转站地址摊给所有人。
 */
interface ModelOptionsState {
  profileChoice: string | null;
  setProfileChoice: (choice: string) => void;
  /** 服务端的 `default_profile`——判断「档案是否偏离默认」的参照物（issue #82）。 */
  defaultProfile: string | null;
  setDefaultProfile: (name: string) => void;

  custom: CustomEndpointFields;
  setCustomField: <K extends keyof CustomEndpointFields>(
    field: K,
    value: CustomEndpointFields[K],
  ) => void;

  customCatalog: CustomCatalog | null;
  customStatus: "idle" | "loading" | "error";
  customErrorMessage: string | null;
  setCustomCatalog: (catalog: CustomCatalog | null) => void;
  setCustomStatus: (status: "idle" | "loading" | "error", errorMessage?: string | null) => void;

  mainModel: string;
  setMainModel: (value: string) => void;
  auxiliaryModel: string;
  setAuxiliaryModel: (value: string) => void;
  /**
   * auxiliary 是否还在跟随 main（ADR-0012：辅助模型绝大多数时候只做标题生成，
   * 与主模型同源是常态）。用户一旦手动改过 auxiliary 就永久置 false——此后
   * 再选主模型不会把他的选择冲掉。
   */
  auxiliaryFollowsMain: boolean;
  /** 用户是否手改过 main——决定预填还能不能落上去。 */
  mainModelTouched: boolean;
  /**
   * 用档案枚举返回的模型标识预填两个输入框（issue #82）——让用户看到「服务端
   * 默认到底是什么」，而不是在 trace 里第一次见到它。只在用户还没动过的槽位上
   * 落值：他手填过的东西不该被一次档案切换冲掉。
   */
  prefillFromProfile: (mainModel: string | null, auxiliaryModel: string | null) => void;
}

export const useModelOptionsStore = create<ModelOptionsState>((set) => ({
  profileChoice: null,
  setProfileChoice: (choice) => set({ profileChoice: choice }),
  defaultProfile: null,
  setDefaultProfile: (name) => set({ defaultProfile: name }),

  custom: { protocol: "openai_responses", baseUrl: "", authField: "Authorization", apiKey: "" },
  setCustomField: (field, value) =>
    set((state) => ({ custom: { ...state.custom, [field]: value } })),

  customCatalog: null,
  customStatus: "idle",
  customErrorMessage: null,
  setCustomCatalog: (catalog) => set({ customCatalog: catalog }),
  setCustomStatus: (status, errorMessage = null) =>
    set({ customStatus: status, customErrorMessage: errorMessage }),

  mainModel: "",
  mainModelTouched: false,
  // 跟随态下 auxiliary 与 main 同步落值，而不是留空后在读取处再兜底——
  // 界面上那个框显示的就是真正会用的标识，不需要读者去脑补「空 = 跟随」。
  setMainModel: (value) =>
    set((state) =>
      state.auxiliaryFollowsMain
        ? { mainModel: value, auxiliaryModel: value, mainModelTouched: true }
        : { mainModel: value, mainModelTouched: true },
    ),
  auxiliaryModel: "",
  setAuxiliaryModel: (value) => set({ auxiliaryModel: value, auxiliaryFollowsMain: false }),
  auxiliaryFollowsMain: true,

  prefillFromProfile: (mainModel, auxiliaryModel) =>
    set((state) => {
      if (state.mainModelTouched || !mainModel) {
        return {};
      }
      return {
        mainModel,
        // 档案没配 auxiliary 就让它跟随 main——与后端的回落规则一致，框里显示的
        // 就是真正会用的那个。
        auxiliaryModel: state.auxiliaryFollowsMain
          ? (auxiliaryModel ?? mainModel)
          : state.auxiliaryModel,
      };
    }),
}));

/**
 * 「这一轮该发什么覆盖」的三种结局。
 *
 * `incomplete` 与 `none` 必须分开：两者都没有可发的覆盖对象，但前者是**用户想
 * 偏离却还没填完**，后者是**用户本来就没想偏离**。混成一个 `null` 会让前者被当
 * 成后者，那一轮就静默改用服务端预设跑掉了——正是 ADR-0014「系统永不代选」要
 * 禁的事，也正是 issue #82 报告的那个失效的形状。
 */
export type ModelOverrideDecision =
  | { kind: "none" }
  | { kind: "override"; override: ModelOverride }
  | { kind: "incomplete"; missing: string };

/**
 * 把当前选择压成 `POST /api/runs` 的 `model_override`——**只在偏离默认时**产出
 * （issue #82）。
 *
 * 不「总是传一份」的理由是前端并不可靠地知道服务端默认是什么：它拿到的预填值是
 * 请求档案枚举那一刻的快照，站长改完 `endpoints.yaml` 重启后就旧了。不传该字段
 * 表示「用你的预设」，服务端读到的就永远是它自己当下那份配置。
 */
export function buildModelOverride(state: ModelOptionsState): ModelOverrideDecision {
  const main = state.mainModel.trim();
  const auxiliary = state.auxiliaryModel.trim();

  if (state.profileChoice === CUSTOM_PROFILE) {
    const baseUrl = state.custom.baseUrl.trim();
    // 自定义端点四件套缺一不可。这里不能回落成「不传覆盖」——用户明确选了自定义
    // 端点，静默改用服务端的档案与密钥跑一轮，他会以为自己的中转站正在工作。
    const missing = [
      baseUrl ? null : "base URL",
      state.custom.apiKey.trim() ? null : "密钥",
      main ? null : "main 模型标识",
    ].filter((field): field is string => field !== null);
    if (missing.length > 0) {
      return { kind: "incomplete", missing: missing.join("、") };
    }
    return {
      kind: "override",
      override: {
        protocol: state.custom.protocol,
        base_url: baseUrl,
        auth_field: state.custom.authField.trim() || "Authorization",
        api_key: state.custom.apiKey,
        main_model: main,
        auxiliary_model: auxiliary && auxiliary !== main ? auxiliary : null,
      },
    };
  }

  const override: ModelOverride = {};
  if (state.profileChoice !== null && state.profileChoice !== state.defaultProfile) {
    override.endpoint_profile = state.profileChoice;
  }
  if (main && state.mainModelTouched) {
    override.main_model = main;
  }
  // auxiliary 只在用户手改过、且真的与 main 不同才传——跟随态下它与 main 同值，
  // 传了等于把「跟随」写死成一次显式指定，回落留痕会因此少记一笔。
  if (auxiliary && !state.auxiliaryFollowsMain && auxiliary !== main) {
    override.auxiliary_model = auxiliary;
  }
  return Object.keys(override).length > 0 ? { kind: "override", override } : { kind: "none" };
}
