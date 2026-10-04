import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getModelProfiles, getModels } from "../../api/client";
import type { components } from "../../generated/api";

type ModelItemView = components["schemas"]["ModelItemView"];
import { CUSTOM_PROFILE, useModelOptionsStore } from "../../stores/model-options-store";
import { useUiStore } from "../../stores/ui-store";

function groupModels(models: ModelItemView[]): [string, ModelItemView[]][] {
  const groups = new Map<string, ModelItemView[]>();
  for (const item of models) groups.set(item.owned_by, [...(groups.get(item.owned_by) ?? []), item]);
  return [...groups.entries()];
}

export function QuickModelPicker({ disabled }: { disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const openSettings = useUiStore((state) => state.openSettings);
  const profile = useModelOptionsStore((state) => state.profileChoice);
  const model = useModelOptionsStore((state) => state.mainModel);
  const setModel = useModelOptionsStore((state) => state.setMainModel);
  const catalog = useModelOptionsStore((state) => state.customCatalog);
  const isCustom = profile === CUSTOM_PROFILE;
  const profiles = useQuery({ queryKey: ["model-profiles"], queryFn: getModelProfiles });
  const preset = isCustom ? null : (profile ?? profiles.data?.default_profile ?? null);
  const models = useQuery({
    queryKey: ["models", preset],
    queryFn: () => getModels(preset ?? undefined),
    enabled: preset !== null,
  });
  const choices = isCustom ? (catalog?.models ?? []) : (models.data?.models ?? []);
  const defaultModel = profiles.data?.profiles?.find((item) => item.name === preset)?.main_model;
  const selected = model || defaultModel || "选择模型";
  const groups = groupModels(choices);
  if (model && !choices.some((item) => item.id === model)) {
    groups.unshift(["当前模型", [{ id: model, owned_by: "当前模型", endpoint_profile: preset ?? "" }]]);
  }

  useEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutside);
    return () => document.removeEventListener("pointerdown", closeOnOutside);
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  return (
    <div className="quick-model-picker" ref={root}>
      <button
        ref={trigger}
        className="quick-model-trigger"
        type="button"
        aria-label={`选择模型，当前 ${selected}`}
        aria-expanded={open}
        aria-controls={open ? "quick-model-menu" : undefined}
        onClick={() => setOpen((value) => !value)}
        disabled={disabled}
        title={selected}
      >
        <span>{selected}</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
      </button>
      {open && (
        <div id="quick-model-menu" className="quick-model-menu" role="group" aria-label="模型清单" onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            setOpen(false);
            trigger.current?.focus();
          }
        }}>
          {groups.length === 0 ? (
            <p className="quick-model-empty">当前没有模型清单，请在设置中下载或填写模型标识。</p>
          ) : groups.map(([owner, items]) => (
            <div className="quick-model-group" key={owner}>
              <p className="quick-model-group-name">{owner}</p>
              {items.map((item) => (
                <button
                  type="button"
                  className="quick-model-option"
                  key={item.id}
                  aria-pressed={item.id === selected}
                  onClick={() => { setModel(item.id); setOpen(false); trigger.current?.focus(); }}
                >
                  <span>{item.id}</span>
                  {item.id === selected && <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m4 12 5 5L20 6" /></svg>}
                </button>
              ))}
            </div>
          ))}
          <button type="button" className="quick-model-settings" onClick={() => { setOpen(false); openSettings(); }}>更多模型与连接设置</button>
        </div>
      )}
    </div>
  );
}
