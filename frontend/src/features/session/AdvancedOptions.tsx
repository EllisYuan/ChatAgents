import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { getModelProfiles, getModels, refreshModels } from "../../api/client";
import type { components } from "../../generated/api";
import { CUSTOM_PROFILE, useModelOptionsStore } from "../../stores/model-options-store";
import { InfoTooltip } from "./InfoTooltip";
import {
  DISCOVERY_UNAVAILABLE_HINT,
  type AddressMode,
  describeEndpoint,
  validateEndpointUrl,
} from "./model-endpoint";
import { ModelPicker } from "./ModelPicker";
import { SecretInput } from "./SecretInput";

type Protocol = components["schemas"]["ModelRefreshRequest"]["protocol"];

const PROTOCOLS: Protocol[] = ["openai_responses", "openai_chat_completions", "anthropic_messages"];

/**
 * 鉴权字段的常见取值——中转站几乎只用这两个头名，第三个选项把自由输入
 * 留在原地。后端 `validate_auth_field` 接受任何合法 HTTP header 名，选项卡
 * 只是把两个高频值提到手边，不缩小可填集合。
 */
const AUTH_FIELD_PRESETS = ["Authorization", "x-api-key"] as const;

/**
 * 高级选项——正好四个槽位（issue #70）：端点档案、密钥输入、main 标识、
 * auxiliary 标识。选中的值随 `POST /api/runs` 的 `model_override` 发出，且
 * **只在偏离服务端预设时才传**（issue #82，构造逻辑在 `buildModelOverride`）。
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
  const startCustomRefresh = useModelOptionsStore((state) => state.startCustomRefresh);
  const finishCustomRefresh = useModelOptionsStore((state) => state.finishCustomRefresh);
  const setCustomStatus = useModelOptionsStore((state) => state.setCustomStatus);
  const mainModel = useModelOptionsStore((state) => state.mainModel);
  const setMainModel = useModelOptionsStore((state) => state.setMainModel);
  const auxiliaryModel = useModelOptionsStore((state) => state.auxiliaryModel);
  const setAuxiliaryModel = useModelOptionsStore((state) => state.setAuxiliaryModel);
  const auxiliaryFollowsMain = useModelOptionsStore((state) => state.auxiliaryFollowsMain);
  const setDefaultProfile = useModelOptionsStore((state) => state.setDefaultProfile);
  const prefillFromProfile = useModelOptionsStore((state) => state.prefillFromProfile);

  const profilesQuery = useQuery({ queryKey: ["model-profiles"], queryFn: getModelProfiles });
  // unavailable 的档案压根不进选单，也不解释原因——站长没配 key 是内部信息（issue #70）。
  const availableProfiles = (profilesQuery.data?.profiles ?? []).filter(
    (profile) => profile.status === "available",
  );

  useEffect(() => {
    const data = profilesQuery.data;
    if (!data) return;
    setDefaultProfile(data.default_profile);
    if (profileChoice === null) {
      // 默认档案优先，而不是「列表第一个」——后者与服务端的 default_profile 无关。
      const initial = availableProfiles.some((profile) => profile.name === data.default_profile)
        ? data.default_profile
        : (availableProfiles[0]?.name ?? CUSTOM_PROFILE);
      setProfileChoice(initial);
    }
  }, [profileChoice, profilesQuery.data, availableProfiles, setProfileChoice, setDefaultProfile]);

  // 预填「服务端真正会用的那个模型」（issue #82）——用户手改过 main 之后就不再落值。
  const selectedProfile = availableProfiles.find((profile) => profile.name === profileChoice);
  useEffect(() => {
    if (selectedProfile) {
      prefillFromProfile(
        selectedProfile.main_model ?? null,
        selectedProfile.auxiliary_model ?? null,
      );
    }
  }, [selectedProfile, prefillFromProfile]);

  // 空串 = 用户点了「自定义」还没填；两个预设之外的任何值也归自定义态。
  const authFieldIsCustom = !AUTH_FIELD_PRESETS.some((preset) => preset === custom.authField);

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
    const baseUrl = custom.baseUrl.trim();
    if (!baseUrl || !custom.apiKey.trim()) {
      setCustomStatus("error", "base URL 与密钥都要填");
      return;
    }
    const endpointError = validateEndpointUrl(baseUrl);
    if (endpointError) {
      setCustomStatus("error", endpointError);
      return;
    }

    const revision = startCustomRefresh();
    try {
      const response = await refreshModels({
        endpoint_profile: null,
        protocol: custom.protocol,
        base_url: baseUrl,
        full_url: custom.fullUrl,
        auth_field: custom.authField.trim() || "Authorization",
        api_key: custom.apiKey,
      });
      finishCustomRefresh(revision, {
        models: response.models ?? [],
        source: response.source,
        error: response.error ?? null,
      });
    } catch (error) {
      finishCustomRefresh(revision, error instanceof Error ? error.message : "下载模型清单失败");
    }
  }

  const addressMode: AddressMode = custom.fullUrl ? "full" : "auto";
  const endpointDescription = custom.baseUrl.trim()
    ? describeEndpoint(custom.protocol, custom.baseUrl, addressMode)
    : null;
  const customUrlError = custom.baseUrl.trim() ? validateEndpointUrl(custom.baseUrl) : null;
  const endpointExample = custom.fullUrl
    ? `例如 https://api.example.com/v1/${custom.protocol === "anthropic_messages" ? "messages" : custom.protocol === "openai_responses" ? "responses" : "chat/completions"}`
    : "例如 https://api.example.com";

  const activeModels = isCustom ? (customCatalog?.models ?? null) : presetProfile ? presetModels : null;

  return (
    <div className="advanced-options">
      <div className="advanced-slot">
        <span className="advanced-slot-label">端点档案</span>
        <select
          className="advanced-input advanced-select"
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
        <span className="advanced-slot-label-row">
          <span className="advanced-slot-label">密钥输入</span>
          {isCustom && (
            <InfoTooltip label="请求地址填写说明">
              <p className="advanced-hint">{endpointExample}</p>
              <p className="advanced-hint">
                {custom.fullUrl
                  ? "按填写的地址发送生成请求，不追加任何路径。"
                  : "填服务根地址即可，自动补 /v1；已有路径则作为 API 前缀原样使用。"}
              </p>
              {endpointDescription && (
                <>
                  <p className="advanced-hint">生成 <code>{endpointDescription.generationPath}</code></p>
                  {endpointDescription.discoveryPath ? (
                    <p className="advanced-hint">发现 <code>{endpointDescription.discoveryPath}</code></p>
                  ) : (
                    <p className="advanced-hint advanced-hint--warning">{DISCOVERY_UNAVAILABLE_HINT}。</p>
                  )}
                  <p className="advanced-hint">模型清单获取成功不保证生成调用可用。</p>
                </>
              )}
            </InfoTooltip>
          )}
        </span>
        {isCustom ? (
          <div className="custom-endpoint-fields">
            <select
              className="advanced-input advanced-select"
              value={custom.protocol}
              onChange={(event) => setCustomField("protocol", event.target.value as Protocol)}
              disabled={disabled}
              aria-label="上游协议"
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
              placeholder={custom.fullUrl ? "完整请求地址" : "请求地址"}
              aria-label="请求地址"
              aria-describedby="custom-endpoint-help"
              aria-invalid={Boolean(customUrlError)}
              value={custom.baseUrl}
              onChange={(event) => setCustomField("baseUrl", event.target.value)}
              autoComplete="off"
              disabled={disabled}
            />
            {/*
              开关只改变「这串地址是什么」，不替用户改写输入框里的文本——自动改写
              会让人看不出应用到底把地址理解成了什么（issue #83 的老毛病）。
            */}
            <button
              type="button"
              role="switch"
              aria-checked={custom.fullUrl}
              className={`full-url-switch${custom.fullUrl ? " full-url-switch--on" : ""}`}
              onClick={() => setCustomField("fullUrl", !custom.fullUrl)}
              disabled={disabled}
            >
              <span className="full-url-switch-track" aria-hidden="true" />
              完整 URL
            </button>
            {customUrlError && (
              <p id="custom-endpoint-help" className="advanced-hint advanced-hint--error" role="alert">
                {customUrlError}
              </p>
            )}
            {/*
              鉴权字段做成选项卡而不是裸输入框：两个高频头名直接可选，选「自定义」
              才落回自由输入。后端仍按合法 header 名校验，选项卡不缩小可填集合。
            */}
            <div className="auth-field-tabs" role="group" aria-label="鉴权模式">
              {AUTH_FIELD_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  className={`auth-field-tab${custom.authField === preset ? " auth-field-tab--active" : ""}`}
                  onClick={() => setCustomField("authField", preset)}
                  disabled={disabled}
                  aria-pressed={custom.authField === preset}
                >
                  {preset}
                </button>
              ))}
              <button
                type="button"
                className={`auth-field-tab${authFieldIsCustom ? " auth-field-tab--active" : ""}`}
                onClick={() => setCustomField("authField", "")}
                disabled={disabled}
                aria-pressed={authFieldIsCustom}
              >
                自定义
              </button>
            </div>
            {authFieldIsCustom && (
              <input
                className="advanced-input"
                type="text"
                placeholder="鉴权头字段名"
                value={custom.authField}
                onChange={(event) => setCustomField("authField", event.target.value)}
                autoComplete="off"
                disabled={disabled}
                aria-label="自定义鉴权头字段名"
              />
            )}
            <SecretInput
              value={custom.apiKey}
              onChange={(value) => setCustomField("apiKey", value)}
              placeholder="API key"
              disabled={disabled}
            />
            <button
              type="button"
              className="text-button"
              onClick={() => void handleDownloadCustomModels()}
              disabled={disabled || customStatus === "loading" || Boolean(customUrlError)}
            >
              {customStatus === "loading"
                ? "下载中…"
                : customCatalog?.source === "fallback"
                  ? "重新获取"
                  : "下载模型"}
            </button>
            {customStatus === "error" && !customUrlError && (
              <p className="advanced-hint advanced-hint--error" role="alert">
                {customErrorMessage}
              </p>
            )}
            {customCatalog && customCatalog.source === "fallback" && (
              <p className="advanced-hint advanced-hint--fallback">
                <span className="fallback-badge">fallback</span>
                {customCatalog.error ? `清单获取失败：${customCatalog.error}` : "清单获取失败"}
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
            模型清单为空
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
      {/*
        auxiliary 默认跟随 main（ADR-0012：它绝大多数时候只做标题生成，与主模型
        同源是常态）——选完主模型这里同步落上同一个标识，看得见、也仍然可改。
        用户一旦手改过就不再跟随，此后换主模型不会冲掉他的选择。
      */}
      <ModelPicker
        id="advanced-auxiliary-model"
        label="auxiliary 模型标识"
        value={auxiliaryModel}
        onChange={setAuxiliaryModel}
        models={activeModels}
        placeholder="跟随主模型"
        followBadge={auxiliaryFollowsMain ? "跟随主模型" : undefined}
        disabled={disabled}
      />
    </div>
  );
}
