import { useEffect, useRef, useState } from "react";
import type { CSSProperties, PointerEvent, ReactNode } from "react";

interface ResizableColumnsProps {
  className: string;
  storageKey: string;
  label: string;
  fixedSide: "start" | "end";
  defaultWidth: number;
  minWidth: number;
  maxWidth: number;
  contentMinWidth: number;
  start: ReactNode;
  end: ReactNode;
  collapsed?: boolean;
}

export function ResizableColumns({
  className, storageKey, label, fixedSide, defaultWidth, minWidth, maxWidth,
  contentMinWidth, start, end, collapsed = false,
}: ResizableColumnsProps) {
  const container = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; width: number; pointerId: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [available, setAvailable] = useState(0);
  const [preferred, setPreferred] = useState(() => {
    try {
      const stored = Number(localStorage.getItem(storageKey));
      if (Number.isFinite(stored) && stored >= minWidth && stored <= maxWidth) return stored;
    } catch { /* Storage may be unavailable in private browsing. */ }
    return defaultWidth;
  });

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setAvailable(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    try { localStorage.setItem(storageKey, String(preferred)); } catch { /* Layout works without storage. */ }
  }, [preferred, storageKey]);

  const upper = Math.max(minWidth, Math.min(maxWidth, available - contentMinWidth - 16));
  const width = Math.max(minWidth, Math.min(preferred, upper));
  const resize = (value: number) => setPreferred(Math.round(Math.max(minWidth, Math.min(upper, value))));
  const finishDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };

  return (
    <div
      ref={container}
      className={`${className} resizable-columns${collapsed ? " resizable-columns--single" : ""}`}
      data-fixed-side={fixedSide}
      data-resizing={dragging || undefined}
      style={{ "--panel-size": `${width}px` } as CSSProperties}
    >
      {start}
      {!collapsed && (
        <>
          <div
            className="column-resizer"
            role="separator"
            aria-label={label}
            aria-orientation="vertical"
            aria-valuemin={minWidth}
            aria-valuemax={upper}
            aria-valuenow={width}
            aria-valuetext={`${width} 像素`}
            tabIndex={0}
            title={`${label}：拖动或使用左右方向键；双击恢复默认宽度`}
            onPointerDown={(event) => {
              if (event.button !== 0) return;
              event.preventDefault();
              drag.current = { x: event.clientX, width, pointerId: event.pointerId };
              event.currentTarget.setPointerCapture(event.pointerId);
              event.currentTarget.focus();
              setDragging(true);
            }}
            onPointerMove={(event) => {
              if (drag.current?.pointerId !== event.pointerId) return;
              const delta = (event.clientX - drag.current.x) * (fixedSide === "start" ? 1 : -1);
              resize(drag.current.width + delta);
            }}
            onPointerUp={finishDrag}
            onPointerCancel={finishDrag}
            onLostPointerCapture={() => { drag.current = null; setDragging(false); }}
            onDoubleClick={() => setPreferred(defaultWidth)}
            onKeyDown={(event) => {
              const direction = fixedSide === "start" ? 1 : -1;
              if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                event.preventDefault();
                resize(width + (event.key === "ArrowRight" ? 1 : -1) * direction * (event.shiftKey ? 40 : 16));
              } else if (event.key === "Home" || event.key === "End") {
                event.preventDefault();
                resize(event.key === "Home" ? minWidth : upper);
              } else if (event.key === "Enter") {
                event.preventDefault();
                setPreferred(defaultWidth);
              }
            }}
          />
          {end}
        </>
      )}
    </div>
  );
}
