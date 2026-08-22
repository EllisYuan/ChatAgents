import { DomainBadge, domainOf } from "./DomainBadge";
import { formatSeconds } from "./format";
import type { TraceSpanNode } from "./types";

interface SearchHit {
  title?: unknown;
  url?: unknown;
  content?: unknown;
  score?: unknown;
}

function isSearchHit(value: unknown): value is SearchHit {
  return typeof value === "object" && value !== null;
}

/** `web_search` 的结构化结果——按 `structured.results[]` 逐条渲染标题/域名/相关性分。 */
function SearchResultsCard({ structured }: { structured: Record<string, unknown> }) {
  const results = Array.isArray(structured.results) ? structured.results : [];
  return (
    <ul className="tool-card-hits">
      {results.filter(isSearchHit).map((hit, index) => {
        const url = typeof hit.url === "string" ? hit.url : null;
        const domain = url ? domainOf(url) : null;
        const score = typeof hit.score === "number" ? hit.score : null;
        return (
          <li className="tool-card-hit" key={url ?? index}>
            {domain && <DomainBadge domain={domain} />}
            <div className="tool-card-hit-body">
              <p className="tool-card-hit-title">{typeof hit.title === "string" ? hit.title : url}</p>
              {domain && <span className="tool-card-hit-domain">{domain}</span>}
              {score !== null && (
                <div className="tool-card-score" aria-label={`相关性 ${(score * 100).toFixed(0)}%`}>
                  <span className="tool-card-score-fill" style={{ width: `${Math.round(score * 100)}%` }} />
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** `web_reader` 的结构化结果——展示读取模式与 token 规模，不是搜索结果列表。 */
function ReaderResultCard({ structured }: { structured: Record<string, unknown> }) {
  const url = typeof structured.url === "string" ? structured.url : null;
  const domain = url ? domainOf(url) : null;
  const mode = typeof structured.mode === "string" ? structured.mode : null;
  const tokenCount = typeof structured.token_count === "number" ? structured.token_count : null;
  const truncated = structured.truncated === true;
  return (
    <div className="tool-card-reader">
      {domain && <DomainBadge domain={domain} />}
      <div className="tool-card-hit-body">
        <p className="tool-card-hit-title">{url}</p>
        <span className="tool-card-hit-domain">
          {mode ?? "read"} · 约 {tokenCount ?? "—"} token{truncated ? " · 已截断" : ""}
        </span>
      </div>
    </div>
  );
}

function StructuredCard({ name, structured }: { name: string; structured: Record<string, unknown> }) {
  if (name === "web_search") {
    return <SearchResultsCard structured={structured} />;
  }
  if (name === "web_reader") {
    return <ReaderResultCard structured={structured} />;
  }
  return <pre className="tool-card-raw">{JSON.stringify(structured, null, 2)}</pre>;
}

interface ToolResultCardProps {
  span: TraceSpanNode;
}

/**
 * 工具结果卡片（ADR-0028）——失败不折叠：红色描边 + 上游原文，紧邻保留
 * （ADR-0015 原文透传）。字段来自 `chatagents.tool_result` / `SpanView.tool_result`
 * 的 `structured`，不是 `TOOL_CALL_RESULT`（后者只装渲染文本）。
 */
export function ToolResultCard({ span }: ToolResultCardProps) {
  const card = span.toolCard;
  if (card === null) {
    return null;
  }

  if (span.status === "pending") {
    return (
      <div className="tool-card tool-card--pending">
        <span className="eyebrow">{span.name}</span>
        <p>调用中…</p>
      </div>
    );
  }

  if (span.status === "error") {
    return (
      <div className="tool-card tool-card--error" role="alert">
        <span className="eyebrow">{span.name}</span>
        <p className="tool-card-upstream">{card.result}</p>
        <span className="tool-card-duration">{formatSeconds(card.durationMs)}</span>
      </div>
    );
  }

  return (
    <div className="tool-card">
      <div className="tool-card-head">
        <span className="eyebrow">{span.name}</span>
        <span className="tool-card-duration">{formatSeconds(card.durationMs)}</span>
      </div>
      {card.structured !== null && <StructuredCard name={span.name} structured={card.structured} />}
    </div>
  );
}
