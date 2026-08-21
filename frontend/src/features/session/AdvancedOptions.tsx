import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { getModelProfiles, getModels, refreshModels } from "../../api/client";
import type { components } from "../../generated/api";
import { CUSTOM_PROFILE, useModelOptionsStore } from "../../stores/model-options-store";
import { ModelPicker } from "./ModelPicker";

type Protocol = components["schemas"]["ModelRefreshRequest"]["protocol"];

const PROTOCOLS: Protocol[] = ["openai_responses", "openai_chat_completions", "anthropic_messages"];

/**
 * 高级选项——正好四个槽位（issue #70）：端点档案、密钥输入、main 标识、
 * auxiliary 标识。选择结果目前只落成前端状态：``POST /api/runs`` 的
 * ``RunRequest`` 还没有模型覆盖字段（issue #59 明确把 BYOK 划出范围），
 * 打通那条链路是后续票的范围，这里先把交互面做完整。
 */
interface AdvancedOptionsProps {
  /** 运行中禁用编辑——改选择不影响正在跑的这一轮（issue #70）。 */
  disabled?: boolean;
}

export function AdvancedOptions({ disabled = false }: AdvancedOptionsProps) {
  const queryClient = useQueryClient();
  const profileChoice = useModelOptionsStore((state) => state.profileChoice);
  const setProfileChoice = useModelOptionsStore((state) => state.setProfileChoice);
  const custom = useModelOptionsStore((state) => state.custom);
  const setCustomField = useModelOptionsStore((state) => state.setCustomField);
  const customCatalog = useModelOptionsStore((state) => state.customCatalog);
  const customStatus = useModelOptionsStore((state) => state.customStatus);
  const customErrorMessage = useModelOptionsStore((state) => state.customErrorMessage);
  const setCustomCatalog = useModelOptionsStore((state) => state.setCustomCatalog);
  const setCustomStatus = useModelOptionsStore((state) => state.setCustomStatus);
  const mainModel = useModelOptionsStore((state) => state.mainModel);
  const setMainModel = useModelOptionsStore((state) => state.setMainModel);
  const auxiliaryModel = useModelOptionsStore((state) => state.auxiliaryModel);
  const setAuxiliaryModel = useModelOptionsStore((state) => state.setAuxiliaryModel);

  const profilesQuery = useQuery({ queryKey: ["model-profiles"], queryFn: getModelProfiles });
  // unavailable 的档案压根不进选单，也不解释原因——站长没配 key 是内部信息（issue #70）。
  const availableProfiles = (profilesQuery.data ?? []).filter(
    (profile) => profile.status === "available",
  );

  useEffect(() => {
    if (profileChoice === null && profilesQuery.data) {
      setProfileChoice(availableProfiles[0]?.name ?? CUSTOM_PROFILE);
    }
  }, [profileChoice, profilesQuery.data, availableProfiles, setProfileChoice]);

  const isCustom = profileChoice === CUSTOM_PROFILE;
  const presetProfile = isCustom ? null : profileChoice;

  const modelsQuery = useQuery({
    queryKey: ["models", presetProfile],
    queryFn: () => getModels(presetProfile ?? undefined),
    enabled: presetProfile !== null,
  });

  const presetModels = modelsQuery.data?.models ?? [];
  const presetIsEmpty = modelsQuery.data !== undefined && presetModels.length === 0;

  async function handleRefreshPreset() {
    if (!presetProfile) return;
    await refreshModels({
      endpoint_profile: presetProfile,
      protocol: "openai_responses",
      auth_field: "Authorization",
    });
    await queryClient.invalidateQueries({ queryKey: ["models", presetProfile] });
  }

  async function handleDownloadCustomModels() {
    if (!custom.baseUrl.trim() || !custom.apiKey.trim()) {
      setCustomStatus("error", "base URL 与密钥都要填");
      return;
    }
    setCustomStatus("loading");
    try {
      const response = await refreshModels({
        endpoint_profile: null,
        protocol: custom.protocol,
        base_url: custom.baseUrl.trim(),
        auth_field: custom.authField.trim() || "Authorization",
        api_key: custom.apiKey,
      });
      setCustomCatalog({
        models: response.models ?? [],
        source: response.source,
        error: response.error ?? null,
      });
      setCustomStatus("idle");
    } catch (error) {
      setCustomStatus("error", error instanceof Error ? error.message : "下载模型清单失败");
    }
  }

  const activeModels = isCustom ? (customCatalog?.models ?? null) : presetProfile ? presetModels : null;

  return (
    <div className="advanced-options">
      <div className="advanced-slot">
        <span className="advanced-slot-label">端点档案</span>
        <select
          className="advanced-input"
          value={profileChoice ?? ""}
          onChange={(event) => setProfileChoice(event.target.value)}
          disabled={disabled}
        >
          {availableProfiles.map((profile) => (
            <option key={profile.name} value={profile.name}>
              {profile.name}
            </option>
          ))}
          <option value={CUSTOM_PROFILE}>自定义端点</option>
        </select>
      </div>

      <div className="advanced-slot">
        <span className="advanced-slot-label">密钥输入</span>
        {isCustom ? (
          <div className="custom-endpoint-fields">
            <select
              className="advanced-input"
              value={custom.protocol}
              onChange={(event) => setCustomField("protocol", event.target.value as Protocol)}
              disabled={disabled}
            >
              {PROTOCOLS.map((protocol) => (
                <option key={protocol} value={protocol}>
                  {protocol}
                </option>
              ))}
            </select>
            <input
              className="advanced-input"
              type="text"
              placeholder="base URL"
              value={custom.baseUrl}
              onChange={(event) => setCustomField("baseUrl", event.target.value)}
              autoComplete="off"
              disabled={disabled}
            />
            <input
              className="advanced-input"
              type="text"
              placeholder="鉴权字段（默认 Authorization）"
              value={custom.authField}
              onChange={(event) => setCustomField("authField", event.target.value)}
              autoComplete="off"
              disabled={disabled}
            />
            <input
              className="advanced-input"
              type="password"
              placeholder="API key"
              value={custom.apiKey}
              onChange={(event) => setCustomField("apiKey", event.target.value)}
              autoComplete="off"
              disabled={disabled}
            />
            <button
              type="button"
              className="text-button"
              onClick={() => void handleDownloadCustomModels()}
              disabled={disabled || customStatus === "loading"}
            >
              {customStatus === "loading"
                ? "下载中…"
                : customCatalog?.source === "fallback"
                  ? "重新获取"
                  : "下载模型"}
            </button>
            {customStatus === "error" && (
              <p className="advanced-hint advanced-hint--error" role="alert">
                {customErrorMessage}
              </p>
            )}
            {customCatalog && customCatalog.source === "fallback" && (
              <p className="advanced-hint advanced-hint--fallback">
                <span className="fallback-badge">fallback</span>
                清单获取失败，可手填标识，或点击「重新获取」
              </p>
            )}
          </div>
        ) : null}
      </div>

      {/*
        清单为空是 main 标识槽位的降级态，不是第五个槽位——只在 DOM 里挂在
        main ModelPicker 前面，不套 .advanced-slot（issue #70：槽位数不增）。
      */}
      {!isCustom && presetIsEmpty && (
        <div className="advanced-degraded-notice">
          <p className="advanced-hint advanced-hint--fallback">
            <span className="fallback-badge">fallback</span>
            模型清单为空，可手填标识
          </p>
          <button
            type="button"
            className="text-button"
            onClick={() => void handleRefreshPreset()}
            disabled={disabled}
          >
            重新获取
          </button>
        </div>
      )}

      <ModelPicker
        id="advanced-main-model"
        label="main 模型标识"
        value={mainModel}
        onChange={setMainModel}
        models={activeModels}
        placeholder="模型标识"
        disabled={disabled}
      />
      <ModelPicker
        id="advanced-auxiliary-model"
        label="auxiliary 模型标识"
        value={auxiliaryModel}
        onChange={setAuxiliaryModel}
        models={activeModels}
        placeholder="留空跟随主模型"
        emptyLabel="跟随主模型"
        disabled={disabled}
      />
    </div>
  );
}
