import { useState } from "react";

import { ReasoningLine } from "./ReasoningLine";
import { SpanDetail } from "./SpanDetail";
import { ToolResultCard } from "./ToolResultCard";
import type { TraceSpanNode, TraceTree } from "./types";

function formatSeconds(durationMs: number | null): string {
  if (durationMs === null) {
    return "…";
  }
  return `${(durationMs / 1000).toFixed(1)}s`;
}

interface SpanChipProps {
  span: TraceSpanNode;
  expanded: boolean;
  onToggle: () => void;
}

/** Layer 1 里单个跨度的可点行——点开进 Layer 2 明细。 */
function SpanChip({ span, expanded, onToggle }: SpanChipProps) {
  return (
    <button
      className={`span-chip span-chip--${span.status}`}
      type="button"
      onClick={onToggle}
      aria-expanded={expanded}
    >
      <span className="span-chip-name">{span.name}</span>
      <span className="span-chip-duration">{formatSeconds(span.durationMs)}</span>
    </button>
  );
}

interface SpanTimelineProps {
  tree: TraceTree;
}

/**
 * Layer 1 跨度时间轴——按迭代分组渲染，左侧竖线归组，并发工具在同一迭代
 * 内并排呈现为兄弟跨度（ADR-0028：并发默认开启在界面上就是这个样子）。
 */
export function SpanTimeline({ tree }: SpanTimelineProps) {
  const [expandedSpanId, setExpandedSpanId] = useState<string | null>(null);
  const toggle = (id: string) => setExpandedSpanId((prev) => (prev === id ? null : id));

  return (
    <div className="span-timeline">
      {tree.iterations.map((iteration) => (
        <div className="span-iteration" key={iteration.key}>
          <div className="span-iteration-bar" aria-hidden="true" />
          <div className="span-iteration-body">
            <ReasoningLine reasoning={iteration.modelSpan.reasoning} />
            <SpanChip
              span={iteration.modelSpan}
              expanded={expandedSpanId === iteration.modelSpan.id}
              onToggle={() => toggle(iteration.modelSpan.id)}
            />
            {expandedSpanId === iteration.modelSpan.id && <SpanDetail span={iteration.modelSpan} />}
            {iteration.toolSpans.length > 0 && (
              <div className="span-row span-row--tools">
                {iteration.toolSpans.map((tool) => (
                  <div className="span-tool-column" key={tool.id}>
                    <SpanChip
                      span={tool}
                      expanded={expandedSpanId === tool.id}
                      onToggle={() => toggle(tool.id)}
                    />
                    <ToolResultCard span={tool} />
                    {expandedSpanId === tool.id && <SpanDetail span={tool} />}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
      {tree.auxiliary && (
        <div className="span-iteration span-iteration--auxiliary">
          <div className="span-iteration-bar" aria-hidden="true" />
          <div className="span-iteration-body">
            <span className="eyebrow">标题生成</span>
            <SpanChip
              span={tree.auxiliary}
              expanded={expandedSpanId === tree.auxiliary.id}
              onToggle={() => toggle(tree.auxiliary!.id)}
            />
            {expandedSpanId === tree.auxiliary.id && <SpanDetail span={tree.auxiliary} />}
          </div>
        </div>
      )}
    </div>
  );
}
