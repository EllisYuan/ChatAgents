import { useQuery } from "@tanstack/react-query";

import { getEvalSummary, type EvalSummary } from "../../api/client";

type MetricKey = "citation_faithfulness" | "tool_trigger_rate" | "trajectory_efficiency";

const METRIC_CARDS: { key: MetricKey; index: string; label: string; blurb: string }[] = [
  {
    key: "citation_faithfulness",
    index: "01",
    label: "引用忠实度",
    blurb: "回答引用 URL 与实际工具观察 URL 的交集占比。",
  },
  {
    key: "tool_trigger_rate",
    index: "02",
    label: "工具触发率",
    blurb: "需要联网时触发工具、不需要时保持不触发的比例。",
  },
  {
    key: "trajectory_efficiency",
    index: "03",
    label: "轨迹效率",
    blurb: "硬上限触达 / 重复读同 URL / 搜完不读三个子信号的均值。",
  },
];

function formatScore(score: number): string {
  return `${(score * 100).toFixed(1)}%`;
}

function formatGeneratedAt(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

function MetricCard({
  index,
  label,
  blurb,
  metric,
}: {
  index: string;
  label: string;
  blurb: string;
  metric: EvalSummary[MetricKey];
}) {
  return (
    <article className="eval-card" aria-labelledby={`eval-card-${index}`}>
      <div className="card-meta">
        <span className="eval-index">{index}</span>
        {metric && <span className="mono">n={metric.sample_size}</span>}
      </div>
      <h2 id={`eval-card-${index}`}>{label}</h2>
      <p className="eval-blurb">{blurb}</p>
      {metric ? (
        <>
          <p className="eval-score">{formatScore(metric.score)}</p>
          <p className="eval-generated-at">评测于 {formatGeneratedAt(metric.generated_at)}</p>
        </>
      ) : (
        <p className="eval-score eval-score--pending">暂无数据</p>
      )}
    </article>
  );
}

function CompressionCostCurveCard({ curve }: { curve: EvalSummary["compression_cost_curve"] }) {
  return (
    <article className="eval-card eval-card--wide" aria-labelledby="eval-card-04">
      <div className="card-meta">
        <span className="eval-index">04</span>
        {curve && <span className="mono">评测于 {formatGeneratedAt(curve.generated_at)}</span>}
      </div>
      <h2 id="eval-card-04">压缩强度 × 引用忠实度 × 成本曲线</h2>
      <p className="eval-blurb">
        release 档位保留窗口网格扫描产出；业界尚无公开可复现的这条曲线。
      </p>
      {curve ? (
        <div className="eval-curve-table" role="table">
          <div className="eval-curve-row eval-curve-row--head" role="row">
            <span role="columnheader">保留窗口</span>
            <span role="columnheader">引用忠实度</span>
            <span role="columnheader">成本（token）</span>
          </div>
          {curve.points.map((point) => (
            <div className="eval-curve-row" role="row" key={point.retention_window}>
              <span role="cell">{point.retention_window}</span>
              <span role="cell">{formatScore(point.citation_faithfulness)}</span>
              <span role="cell">{point.cost_tokens.toLocaleString("zh-CN")}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="eval-score eval-score--pending">网格扫描未落地，暂不显示</p>
      )}
    </article>
  );
}

export function EvalsPage() {
  const summaryQuery = useQuery({ queryKey: ["eval-summary"], queryFn: getEvalSummary });

  return (
    <section className="evals-page" aria-labelledby="evals-title">
      <p className="eyebrow">EVALS / SITE-LEVEL / READ-ONLY</p>
      <h1 id="evals-title">Numbers, not a console.</h1>
      <p className="evals-copy">
        跨运行的评测结果，来自离线数据集的批量跑分——与单次对话无关，因此不进聊天界面
        （ADR-0028）。正好四个数字，事实幻觉率、任务完成度等判官方差较大的指标只进评测报告。
      </p>

      {summaryQuery.isPending && <p className="eval-status">加载评测产出中…</p>}
      {summaryQuery.isError && <p className="eval-status eval-status--error">评测数据加载失败。</p>}

      {summaryQuery.data && (
        <div className="evals-grid">
          {METRIC_CARDS.map((card) => (
            <MetricCard
              key={card.key}
              index={card.index}
              label={card.label}
              blurb={card.blurb}
              metric={summaryQuery.data[card.key]}
            />
          ))}
          <CompressionCostCurveCard curve={summaryQuery.data.compression_cost_curve} />
        </div>
      )}
    </section>
  );
}
