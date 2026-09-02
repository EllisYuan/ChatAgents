import { memo } from "react";
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
