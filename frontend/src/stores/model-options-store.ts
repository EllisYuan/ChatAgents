import { create } from "zustand";

import type { components } from "../generated/api";

type Protocol = components["schemas"]["ModelRefreshRequest"]["protocol"];
type ModelItem = components["schemas"]["ModelItemView"];

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
}

export const useModelOptionsStore = create<ModelOptionsState>((set) => ({
  profileChoice: null,
  setProfileChoice: (choice) => set({ profileChoice: choice }),

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
  // 跟随态下 auxiliary 与 main 同步落值，而不是留空后在读取处再兜底——
  // 界面上那个框显示的就是真正会用的标识，不需要读者去脑补「空 = 跟随」。
  setMainModel: (value) =>
    set((state) =>
      state.auxiliaryFollowsMain
        ? { mainModel: value, auxiliaryModel: value }
        : { mainModel: value },
    ),
  auxiliaryModel: "",
  setAuxiliaryModel: (value) => set({ auxiliaryModel: value, auxiliaryFollowsMain: false }),
  auxiliaryFollowsMain: true,
}));
