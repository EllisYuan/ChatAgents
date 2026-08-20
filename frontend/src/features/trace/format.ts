/** trace 面板共用的耗时格式化——`null` 代表尚无这个数（进行中/结构性不存在）。 */
export function formatSeconds(durationMs: number | null): string {
  if (durationMs === null) {
    return "—";
  }
  return `${(durationMs / 1000).toFixed(1)}s`;
}
