import type { components } from "../../generated/api";

export type EffortTier = components["schemas"]["RunRequest"]["effort"];

const TIERS: EffortTier[] = ["low", "medium", "high", "xhigh"];

interface EffortSwitcherProps {
  value: EffortTier;
  onChange: (tier: EffortTier) => void;
  disabled?: boolean;
}

/**
 * 四档努力档位切换器——「下一轮用什么」，紧挨输入框。
 *
 * 与 trace 面板运行配置区里的档位回显（「这一轮用了什么」）是两个独立的值，
 * 不同步、可以不一致（issue #70，见 issue #69 的 RunConfigTable）。
 */
export function EffortSwitcher({ value, onChange, disabled }: EffortSwitcherProps) {
  return (
    <div className="effort-switcher" role="radiogroup" aria-label="努力档位（下一轮）">
      {TIERS.map((tier) => (
        <button
          key={tier}
          type="button"
          role="radio"
          aria-checked={tier === value}
          className={`effort-tier${tier === value ? " effort-tier--active" : ""}`}
          onClick={() => onChange(tier)}
          disabled={disabled}
        >
          {tier}
        </button>
      ))}
    </div>
  );
}
