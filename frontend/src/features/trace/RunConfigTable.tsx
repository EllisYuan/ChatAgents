import type { RunConfig } from "./types";

/** 版本标识两段排版——人读部分正常字重，`@hash` 部分降灰等宽（ADR-0028）。 */
function VersionId({ value }: { value: string }) {
  const separatorIndex = value.indexOf("@");
  const human = separatorIndex === -1 ? value : value.slice(0, separatorIndex);
  const machine = separatorIndex === -1 ? "" : value.slice(separatorIndex);
  return (
    <button
      className="version-id"
      type="button"
      onClick={() => void navigator.clipboard.writeText(value)}
      title="点击复制"
    >
      {human}
      {machine && <span className="version-id-hash">{machine}</span>}
    </button>
  );
}

function inputSequenceLabel(prunedRunCount: number | null): string {
  if (prunedRunCount === null || prunedRunCount === 0) {
    return "未削减";
  }
  return `已丢弃最旧 ${prunedRunCount} 轮（累计削减 ${prunedRunCount}）`;
}

interface RunConfigTableProps {
  runConfig: RunConfig;
}

/**
 * 本次运行配置——不可展开的平铺参数表（ADR-0028）。折叠块承诺「点我有
 * 内容」，表格单元格承诺的是「这是一个值」，这里全部是后者。
 */
export function RunConfigTable({ runConfig }: RunConfigTableProps) {
  return (
    <dl className="run-config-table">
      <div className="run-config-row">
        <dt>提示词</dt>
        <dd>{runConfig.promptVersionId ? <VersionId value={runConfig.promptVersionId} /> : "—"}</dd>
      </div>
      <div className="run-config-row">
        <dt>工具集</dt>
        <dd>{runConfig.toolSchemaVersionId ? <VersionId value={runConfig.toolSchemaVersionId} /> : "—"}</dd>
      </div>
      <div className="run-config-row">
        <dt>努力档位</dt>
        <dd>{runConfig.effort ?? "—"}</dd>
      </div>
      <div className="run-config-row">
        <dt>保留窗口</dt>
        <dd>{runConfig.retentionWindow !== null ? `最近 ${runConfig.retentionWindow} 对观察` : "—"}</dd>
      </div>
      <div className="run-config-row">
        <dt>输入序列</dt>
        <dd>{inputSequenceLabel(runConfig.prunedRunCount)}</dd>
      </div>
    </dl>
  );
}
