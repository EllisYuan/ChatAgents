import { useId, useState, type ReactNode } from "react";

interface InfoTooltipProps {
  label: string;
  children: ReactNode;
}

/**
 * 悬浮/聚焦展开的说明气泡——参考类文档但不影响布局的静态提示，用它收纳，
 * 不再常驻占位。触发器可点击（触屏没有 hover）、可聚焦（键盘可达），失焦
 * 或再次点击收起。
 */
export function InfoTooltip({ label, children }: InfoTooltipProps) {
  const [open, setOpen] = useState(false);
  const tooltipId = useId();

  return (
    <span
      className="info-tooltip"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        className="info-tooltip-trigger"
        aria-label={label}
        aria-describedby={tooltipId}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        i
      </button>
      <div id={tooltipId} role="tooltip" className="info-tooltip-panel" hidden={!open}>
        {children}
      </div>
    </span>
  );
}
