"""
LLM 配置模块
支持多种语言模型的配置和初始化
"""

import os
from typing import ClassVar

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI


class LLMProvider:
    """LLM 提供商枚举"""

    CLAUDE = "claude"
    OPENAI = "openai"
    GROQ = "groq"


class LLMConfig:
    """
    LLM 配置类
    提供统一接口来初始化不同的语言模型
    """

    # 支持的 Claude 模型
    CLAUDE_MODELS: ClassVar[dict[str, str]] = {
        "haiku": "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-5-20250929",
        "opus": "claude-opus-4-1-202508059",
    }

    # 支持的 OpenAI 模型
    OPENAI_MODELS: ClassVar[dict[str, str]] = {
        "gpt-5.1": "gpt-5.1",
        "gpt-5-mini": "gpt-5-mini",
        "gpt-5-nano": "gpt-5-nano",
        "gpt-5": "gpt-5",
        "gpt-4.1-nano": "gpt-4.1-nano",
    }

    # 支持的 Groq 模型
    GROQ_MODELS: ClassVar[dict[str, str]] = {
        "llama-3.3-70b": "llama-3.3-70b-versatile",
        "mixtral-8x7b": "mixtral-8x7b-32768",
        "kimi-k2": "moonshotai/kimi-k2-instruct",
    }

    @staticmethod
    def create_claude(
        model: str = "sonnet",
        api_key: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        streaming: bool = True,
    ) -> BaseChatModel:
        """
        创建 Claude 语言模型实例

        Args:
            model: 模型名称（haiku/sonnet/opus）
            api_key: Anthropic API 密钥
            temperature: 温度参数（0-1）
            max_tokens: 最大 token 数
            streaming: 是否启用流式输出

        Returns:
            Claude 语言模型实例
        """
        model_name = LLMConfig.CLAUDE_MODELS.get(model, LLMConfig.CLAUDE_MODELS["sonnet"])

        llm = ChatAnthropic(
            model=model_name,
            anthropic_api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
        )

        if streaming:
            llm = llm.with_config({"tags": ["streaming"]})

        return llm

    @staticmethod
    def create_openai(
        model: str = "gpt-5.1-mini",
        api_key: str | None = None,
        temperature: float = 1,
        max_tokens: int = 4096,
        streaming: bool = True,
    ) -> BaseChatModel:
        """
        创建 OpenAI 语言模型实例

        Args:
            model: 模型名称
            api_key: OpenAI API 密钥
            temperature: 温度参数（0-1）
            max_tokens: 最大 token 数
            streaming: 是否启用流式输出

        Returns:
            OpenAI 语言模型实例
        """
        model_name = LLMConfig.OPENAI_MODELS.get(model, LLMConfig.OPENAI_MODELS["gpt-5.1"])

        llm = ChatOpenAI(
            model=model_name,
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
        )

        if streaming:
            llm = llm.with_config({"tags": ["streaming"]})

        return llm

    @staticmethod
    def create_groq(
        model: str = "llama-3.3-70b",
        api_key: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        streaming: bool = True,
    ) -> BaseChatModel:
        """
        创建 Groq 语言模型实例

        Args:
            model: 模型名称
            api_key: Groq API 密钥
            temperature: 温度参数（0-1）
            max_tokens: 最大 token 数
            streaming: 是否启用流式输出

        Returns:
            Groq 语言模型实例
        """
        model_name = LLMConfig.GROQ_MODELS.get(model, LLMConfig.GROQ_MODELS["llama-3.3-70b"])

        llm = ChatGroq(
            model=model_name,
            api_key=api_key or os.getenv("GROQ_API_KEY"),
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
        )

        if streaming:
            llm = llm.with_config({"tags": ["streaming"]})

        return llm

    @staticmethod
    def create_llm(
        provider: str = LLMProvider.CLAUDE,
        model: str | None = None,
        api_key: str | None = None,
        max_tokens: int = 4096,
        streaming: bool = True,
    ) -> BaseChatModel:
        """
        统一接口创建语言模型实例

        Args:
            provider: LLM 提供商（claude/openai/groq）
            model: 模型名称（可选，使用默认值）
            api_key: API 密钥（可选，从环境变量读取）
            max_tokens: 最大 token 数
            streaming: 是否启用流式输出

        Returns:
            语言模型实例

        Raises:
            ValueError: 如果提供商不支持
        """
        if provider == LLMProvider.CLAUDE:
            return LLMConfig.create_claude(
                model=model or "sonnet",
                api_key=api_key,
                max_tokens=max_tokens,
                streaming=streaming,
            )
        elif provider == LLMProvider.OPENAI:
            return LLMConfig.create_openai(
                model=model or "gpt-4o",
                api_key=api_key,
                max_tokens=max_tokens,
                streaming=streaming,
            )
        elif provider == LLMProvider.GROQ:
            return LLMConfig.create_groq(
                model=model or "llama-3.3-70b",
                api_key=api_key,
                max_tokens=max_tokens,
                streaming=streaming,
            )
        else:
            raise ValueError(f"不支持的 LLM 提供商: {provider}")
