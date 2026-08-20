import { useState } from "react";

import { formatSeconds } from "./format";
import type { ReasoningState } from "./types";

interface ReasoningLineProps {
  reasoning: ReasoningState | null;
}

/**
 * 原生推理的收起态一行 + 展开正文（ADR-0028）。
 *
 * 三态视觉语言不读文字也能分辨：结构性不存在（`reasoning === null`）→ 整个
 * 不渲染；`aged_out` → 灰度注释 + 时钟图标，无边框无色块；`available` →
 * 正常展示，点开看正文。默认收起——老会话重开时一大片「已过期」不该占住
 * 主位。
 */
export function ReasoningLine({ reasoning }: ReasoningLineProps) {
  const [open, setOpen] = useState(false);

  if (reasoning === null) {
    return null;
  }

  if (reasoning.status === "aged_out") {
    return (
      <p className="reasoning-line reasoning-line--aged">
        <span aria-hidden="true">🕓</span> 思考内容已过期
      </p>
    );
  }

  const label = reasoning.durationMs !== null ? `思考 ${formatSeconds(reasoning.durationMs)}` : "思考";

  return (
    <div className="reasoning-line">
      <button className="reasoning-toggle" type="button" onClick={() => setOpen((prev) => !prev)}>
        <span className="run-summary-marker">{open ? "▾" : "▸"}</span> {label}
      </button>
      {open && <p className="reasoning-text">{reasoning.text}</p>}
    </div>
  );
}
