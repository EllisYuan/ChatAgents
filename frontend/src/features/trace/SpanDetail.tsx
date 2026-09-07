import { formatSeconds } from "./format";
import type { TraceSpanNode } from "./types";

function formatTokens(tokens: number | null): string {
  return tokens === null ? "—" : String(tokens);
}

interface SpanDetailProps {
  span: TraceSpanNode;
}

/** Layer 2——点单个跨度展开的明细：模型、角色、双向 token、耗时、错误原文。 */
export function SpanDetail({ span }: SpanDetailProps) {
  return (
    <dl className="span-detail">
      {span.model !== null && (
        <div className="span-detail-row">
          <dt>模型</dt>
          <dd>{span.model}</dd>
        </div>
      )}
      {span.role !== null && (
        <div className="span-detail-row">
          <dt>角色</dt>
          <dd>{span.role}</dd>
        </div>
      )}
      <div className="span-detail-row">
        <dt>输入 token</dt>
        <dd>{span.usageStatus === "unavailable" ? "不可用" : formatTokens(span.inputTokens)}</dd>
      </div>
      <div className="span-detail-row">
        <dt>输出 token</dt>
        <dd>{span.usageStatus === "unavailable" ? "不可用" : formatTokens(span.outputTokens)}</dd>
      </div>
      {span.reasoningTokens !== null && (
        <div className="span-detail-row">
          <dt>推理 token</dt>
          <dd>{formatTokens(span.reasoningTokens)}</dd>
        </div>
      )}
      <div className="span-detail-row">
        <dt>耗时</dt>
        <dd>{formatSeconds(span.durationMs)}</dd>
      </div>
      {span.kind === "tool" && span.toolCard?.argumentsRaw && (
        <div className="span-detail-row">
          <dt>入参</dt>
          <dd className="span-detail-raw">{span.toolCard.argumentsRaw}</dd>
        </div>
      )}
      {span.status === "error" && span.toolCard?.result && (
        <div className="span-detail-row">
          <dt>上游原文</dt>
          <dd className="span-detail-raw span-detail-error">{span.toolCard.result}</dd>
        </div>
      )}
    </dl>
  );
}
