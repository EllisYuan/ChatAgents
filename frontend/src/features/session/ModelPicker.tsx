import { useEffect, useRef, useState } from "react";

import type { components } from "../../generated/api";

type ModelItem = components["schemas"]["ModelItemView"];

function groupByOwner(models: ModelItem[]): [string, ModelItem[]][] {
  const groups = new Map<string, ModelItem[]>();
  for (const model of models) {
    const bucket = groups.get(model.owned_by);
    if (bucket) {
      bucket.push(model);
    } else {
      groups.set(model.owned_by, [model]);
    }
  }
  return [...groups.entries()];
}

interface ModelPickerProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** `null` = 清单还没加载；`[]` = 发现失败落到手填态（ADR-0016）。 */
  models: ModelItem[] | null;
  placeholder?: string;
  disabled?: boolean;
  /** 显示在标签右侧的跟随状态徽标（auxiliary 跟随 main 时用，issue #70）。 */
  followBadge?: string;
}

/**
 * main / auxiliary 模型标识输入——自由文本，不是受限下拉（issue #70）。
 *
 * 清单只用来给分组建议，从不阻断发送：标识不在清单里也照样能填，
 * 只在输入框下方标一行提示（不在清单里的标识当场标出、不等运行时）。
 */
export function ModelPicker({
  id,
  label,
  value,
  onChange,
  models,
  placeholder,
  disabled,
  followBadge,
}: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const trimmed = value.trim();
  const knownIds = models ? new Set(models.map((model) => model.id)) : null;
  const isOffList = knownIds !== null && trimmed !== "" && !knownIds.has(trimmed);
  const groups = models && models.length > 0 ? groupByOwner(models) : [];

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
    <div
      className="model-picker"
      ref={root}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
          input.current?.focus();
        }
      }}
    >
      <label className="advanced-slot-label" htmlFor={id}>
        {label}
        {followBadge && <span className="follow-badge">{followBadge}</span>}
      </label>
      <div className="model-picker-field">
        <input
          ref={input}
          id={id}
          className="advanced-input"
          type="text"
          value={value}
          onClick={() => setOpen((current) => !current)}
          onChange={(event) => {
            onChange(event.target.value);
            setOpen(true);
          }}
          aria-expanded={open && groups.length > 0}
          aria-controls={open && groups.length > 0 ? `${id}-suggestions` : undefined}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" && groups.length > 0) {
              event.preventDefault();
              setOpen(true);
              requestAnimationFrame(() => root.current?.querySelector<HTMLButtonElement>(".model-picker-item")?.focus());
            }
          }}
          placeholder={placeholder}
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
        />
        {groups.length > 0 && <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>}
      </div>
      {isOffList && <p className="advanced-hint advanced-hint--offlist">不在清单中，仍可发送</p>}
      {open && groups.length > 0 && (
        <div id={`${id}-suggestions`} className="model-picker-groups" role="group" aria-label={`${label}建议清单`}>
          {groups.map(([owner, items]) => (
            <div className="model-picker-group" key={owner}>
              <span className="model-picker-owner">{owner}</span>
              <div className="model-picker-items">
                {items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`model-picker-item${item.id === trimmed ? " model-picker-item--active" : ""}`}
                    onClick={() => {
                      onChange(item.id);
                      setOpen(false);
                      input.current?.focus();
                    }}
                    aria-pressed={item.id === trimmed}
                    disabled={disabled}
                  >
                    {item.id}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
