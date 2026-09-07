import type { RunSummary } from "./chat-types";

function formatTokens(tokens: number): string {
  if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(1)}k tok`;
  }
  return `${tokens} tok`;
}

function formatDuration(durationMs: number): string {
  return `${(durationMs / 1000).toFixed(1)}s`;
}

interface SummaryLineProps {
  pending: boolean;
  summary?: RunSummary;
}

/**
 * 第 0 层的摘要行——骨架实时，数字收尾（ADR-0028）。
 *
 * 流式期间用量是半截的，让它随流跳动等于把不准的数做成最抢眼的动效，所以
 * 流式期间只画骨架，`RUN_FINISHED`/`RUN_ERROR`/断连之后才落定成具体数字。
 */
export function SummaryLine({ pending, summary }: SummaryLineProps) {
  if (pending) {
    return (
      <p className="run-summary run-summary--pending" aria-live="polite">
        <span className="run-summary-marker">▸</span> 运行中…
      </p>
    );
  }
  if (!summary) {
    return null;
  }
  const tokensText =
    summary.usageStatus === "complete" && summary.tokens !== null
      ? formatTokens(summary.tokens)
      : "用量不完整";
  return (
    <p className="run-summary" aria-live="polite">
      <span className="run-summary-marker">▸</span> {summary.steps} 步 · {tokensText} ·{" "}
      {formatDuration(summary.durationMs)}
    </p>
  );
}
