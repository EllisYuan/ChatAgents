export function TraceSkeleton() {
  return (
    <div className="trace-skeleton" aria-label="Trace 区域占位">
      <span className="eyebrow">TRACE / WAITING FOR RUN</span>
      <p>运行开始后，模型与工具跨度会出现在这里。</p>
    </div>
  );
}
