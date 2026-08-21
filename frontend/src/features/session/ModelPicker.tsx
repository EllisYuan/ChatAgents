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
  emptyLabel?: string;
  disabled?: boolean;
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
  emptyLabel,
  disabled,
}: ModelPickerProps) {
  const trimmed = value.trim();
  const knownIds = models ? new Set(models.map((model) => model.id)) : null;
  const isOffList = knownIds !== null && trimmed !== "" && !knownIds.has(trimmed);
  const groups = models && models.length > 0 ? groupByOwner(models) : [];

  return (
    <div className="model-picker">
      <label className="advanced-slot-label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="advanced-input"
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete="off"
        spellCheck={false}
      />
      {trimmed === "" && emptyLabel && <p className="advanced-hint">{emptyLabel}</p>}
      {isOffList && <p className="advanced-hint advanced-hint--offlist">不在清单中，仍可发送</p>}
      {groups.length > 0 && (
        <div className="model-picker-groups" role="list" aria-label={`${label}建议清单`}>
          {groups.map(([owner, items]) => (
            <div className="model-picker-group" key={owner}>
              <span className="model-picker-owner">{owner}</span>
              <div className="model-picker-items">
                {items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`model-picker-item${item.id === trimmed ? " model-picker-item--active" : ""}`}
                    onClick={() => onChange(item.id)}
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
