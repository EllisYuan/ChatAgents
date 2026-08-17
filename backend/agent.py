import ast
import json
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_tavily import TavilyCrawl, TavilyExtract, TavilySearch
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_output_summarizer(summary_llm: BaseChatModel) -> Callable[[str, str], dict]:
    """
    创建输出摘要器

    Args:
        summary_llm: 用于生成摘要的语言模型

    Returns:
        摘要函数
    """

    def summarize_output(tool_output: str, user_message: str = "") -> dict:
        """
        对工具输出进行摘要处理

        Args:
            tool_output: 工具原始输出
            user_message: 用户消息（用于上下文）

        Returns:
            包含摘要、URL 和 favicon 的字典
        """
        if not tool_output or tool_output.strip() == "":
            return {"summary": tool_output, "urls": []}

        # 尝试解析 JSON 格式的工具输出
        try:
            parsed_output = json.loads(tool_output)
        except (json.JSONDecodeError, TypeError):
            try:
                parsed_output = ast.literal_eval(tool_output)
            except (ValueError, SyntaxError):
                return {"summary": tool_output, "urls": []}

        # 提取 URL、favicon 和内容
        urls = []
        favicons = []
        content = ""

        if isinstance(parsed_output, dict) and "results" in parsed_output:
            items = parsed_output["results"]
        elif isinstance(parsed_output, list):
            items = parsed_output
        else:
            return {"summary": tool_output, "urls": [], "favicons": []}

        # 从结果中提取信息
        for item in items:
            if isinstance(item, dict):
                if "url" in item:
                    urls.append(item["url"])
                if "favicon" in item:
                    favicons.append(item["favicon"])
                if "raw_content" in item:
                    content += item["raw_content"] + "\n\n"

        # 生成摘要
        if content:
            summary_prompt = f"""请将以下内容总结为相关格式，以帮助回答用户的问题。
            重点关注对回答以下问题最有用的关键信息：{user_message}
            删除冗余信息并突出最重要的发现。

            内容：
            {content[:3000]}  # 限制内容长度

            请提供一个清晰、有组织的摘要，捕捉与用户问题相关的基本信息：
            """
            try:
                summary = summary_llm.invoke(summary_prompt).content
            except Exception as e:
                logger.error(f"摘要生成失败: {e}")
                summary = content[:500]  # 回退到截断内容
        else:
            summary = tool_output

        return {"summary": summary, "urls": urls, "favicons": favicons}

    return summarize_output


class WebAgent:
    """
    Web智能体 类，集成 Tavily 搜索、提取和爬取功能
    """

    def __init__(self, checkpointer: MemorySaver | None = None) -> None:
        """
        初始化 Web 智能体

        Args:
            checkpointer: LangGraph 检查点存储器（用于对话记忆）
        """
        self.checkpointer = checkpointer

    def build_graph(
        self,
        api_key: str,
        llm: BaseChatModel,
        prompt: str,
        summary_llm: BaseChatModel,
        user_message: str = "",
        mode: str = "fast",
        topic: str = "general",
        time_range: str | None = None,
    ) -> Any:
        """
        构建并编译 LangGraph 工作流

        Args:
            api_key: Tavily API 密钥
            llm: 主要语言模型（用于智能体推理）
            prompt: 系统提示词
            summary_llm: 用于摘要的语言模型
            user_message: 用户原始消息（用于摘要上下文）
            mode: 搜索模式，"fast"（快速模式）或 "deep"（深度思考模式），默认为 "fast"
            topic: 搜索主题，"general"（通用）、"news"（新闻）或 "finance"（财经），默认为 "general"
            time_range: 时间范围过滤，可选 "day"、"week"、"month"、"year"，默认不限制

        Returns:
            编译后的 LangGraph 智能体
        """
        if not api_key:
            raise ValueError("错误：未提供 Tavily API 密钥")

        # 根据模式设置搜索参数
        # fast: 快速模式，使用 basic 深度，3 条结果，速度快、成本低
        # deep: 深度思考模式，使用 advanced 深度，5 条结果，包含图片，结果更全面但成本更高
        depth = "basic" if mode == "fast" else "advanced"
        max_results = 3 if mode == "fast" else 5
        include_images = mode != "fast"
        crawl_limit = 5 if mode == "fast" else 15

        # 构建 TavilySearch 参数
        search_params = {
            "max_results": max_results,
            "tavily_api_key": api_key,
            "include_favicon": True,
            "search_depth": depth,
            "include_answer": False,
            "topic": topic,
            "include_images": include_images,
        }

        # 添加时间范围参数（如果指定）
        if time_range:
            search_params["time_range"] = time_range

        # 创建 Tavily 工具
        search = TavilySearch(**search_params)

        extract = TavilyExtract(
            extract_depth=depth,
            tavily_api_key=api_key,
            include_favicon=True,
            include_images=include_images,
        )

        crawl = TavilyCrawl(tavily_api_key=api_key, include_favicon=True, limit=crawl_limit)

        # 创建输出摘要器
        output_summarizer = create_output_summarizer(summary_llm)

        # 为 Extract 工具添加摘要功能
        class SummarizingTavilyExtract(TavilyExtract):
            def _run(self, *args, **kwargs):
                kwargs.pop("run_manager", None)
                result = super()._run(*args, **kwargs)
                return output_summarizer(str(result), user_message)

            async def _arun(self, *args, **kwargs):
                kwargs.pop("run_manager", None)
                result = await super()._arun(*args, **kwargs)
                return output_summarizer(str(result), user_message)

        # 为 Crawl 工具添加摘要功能
        class SummarizingTavilyCrawl(TavilyCrawl):
            def _run(self, *args, **kwargs):
                kwargs.pop("run_manager", None)
                result = super()._run(*args, **kwargs)
                return output_summarizer(str(result), user_message)

            async def _arun(self, *args, **kwargs):
                kwargs.pop("run_manager", None)
                result = await super()._arun(*args, **kwargs)
                return output_summarizer(str(result), user_message)

        # 创建带摘要的工具实例
        extract_with_summary = SummarizingTavilyExtract(
            extract_depth=extract.extract_depth,
            tavily_api_key=api_key,
            include_favicon=extract.include_favicon,
            description=extract.description,
        )

        crawl_with_summary = SummarizingTavilyCrawl(
            tavily_api_key=api_key,
            include_favicon=crawl.include_favicon,
            limit=crawl.limit,
            description=crawl.description,
        )

        # 创建 ReAct 智能体
        return create_react_agent(
            prompt=prompt,
            model=llm,
            tools=[search, extract_with_summary, crawl_with_summary],
            checkpointer=self.checkpointer,
        )
