import { isValidElement, memo, type ReactNode, useEffect, useRef, useState } from "react";
import { CheckIcon, CopyIcon } from "./icons";

function CodeBlock({ children }: { children?: ReactNode }) {
  const code = isValidElement<{ children?: ReactNode; className?: string }>(children) ? children : null;
  const text = typeof code?.props.children === "string" ? code.props.children.replace(/\n$/, "") : "";
  const language = code?.props.className?.match(/(?:^|\s)language-([\w+-]+)/)?.[1];
  const [status, setStatus] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setStatus("copied");
    } catch {
      setStatus("failed");
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setStatus("idle"), 1800);
  };

  return (
    <div className="chat-code-block">
      <div className="chat-code-toolbar">
        <span className="chat-code-language">{language ?? "代码"}</span>
        <button type="button" className="chat-code-copy" onClick={() => void copy()} disabled={!text} aria-label={status === "failed" ? "复制失败，请重试" : status === "copied" ? "已复制代码" : "复制代码"}>
          {status === "copied" ? <CheckIcon size={14} /> : <CopyIcon size={14} />}
          <span aria-live="polite">{status === "copied" ? "已复制" : status === "failed" ? "复制失败" : "复制"}</span>
        </button>
      </div>
      <pre>{children}</pre>
    </div>
  );
}

import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * 外链一律新标签打开，并带 `noopener noreferrer`——回答正文里的链接来自模型
 * 输出与工具抓回的第三方内容，不是本站路由，不能让它顶掉当前会话（ADR-0028：
 * 聊天界面是唯一的控制台，离开这一页就等于丢掉正在读的运行）。
 */
const components: Components = {
  a: ({ href, children, ...rest }) => (
    <a {...rest} href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
};

interface MessageMarkdownProps {
  text: string;
}

/**
 * Agent 回答正文的 Markdown 渲染。
 *
 * 原始 HTML 不解析——react-markdown 默认转义，且本项目不引入 `rehype-raw`：
 * 正文是模型输出加工具抓回的第三方内容，放开 HTML 等于把注入面开给上游。
 * 流式增量每来一个 delta 就重渲染一次，`memo` 让同一条消息在其他 state
 * 变化（activeTool、trace 事件）时不做无谓的重新解析。
 */
export const MessageMarkdown = memo(function MessageMarkdown({ text }: MessageMarkdownProps) {
  return (
    <div className="chat-markdown">
      <Markdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </Markdown>
    </div>
  );
});
