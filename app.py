"""
FastAPI 后端服务器
提供智能体聊天流式接口
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain.schema import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

# 添加项目路径
sys.path.append(str(Path(__file__).parent))

# 导入后端模块
from backend.agent import WebAgent
from backend.prompts import get_reasoning_prompt, get_simple_prompt
from backend.utils import check_api_key
from backend.llm_config import LLMConfig, LLMProvider
from backend.session_manager import get_session_manager

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    logger.info("正在初始化 Web 智能体...")
    checkpointer = MemorySaver()
    agent = WebAgent(checkpointer=checkpointer)
    app.state.agent = agent
    logger.info("Web 智能体初始化完成")

    yield

    # 关闭时清理
    logger.info("正在关闭应用...")


# 创建 FastAPI 应用
app = FastAPI(
    title="智能聊天机器人 API",
    description="基于 LangGraph 和 Tavily 的智能体聊天接口",
    version="1.0.0",
    lifespan=lifespan
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AgentRequest(BaseModel):
    """智能体请求模型"""
    input: str  # 用户输入
    thread_id: str  # 会话 ID
    agent_type: str  # 智能体类型（fast/deep）
    llm_provider: str = LLMProvider.CLAUDE  # LLM 提供商（默认 Claude）
    llm_model: str  # 端点 /v1/models 发现的原始模型标识


@app.get("/")
async def root():
    """健康检查接口"""
    return {
        "message": "后端 API 正在运行",
        "status": "healthy"
    }

@app.get("/health")
async def health():
    """健康检查接口（前端使用）"""
    return {
        "message": "后端 API 正在运行",
        "status": "healthy"
    }

@app.post("/stream_agent")
async def stream_agent(body: AgentRequest, request: Request):
    """
    流式智能体接口

    Args:
        body: 请求体（包含用户输入、会话 ID、智能体类型等）
        request: FastAPI 请求对象

    Returns:
        StreamingResponse: 流式响应
    """
    # 获取 Tavily API 密钥
    tavily_api_key = request.headers.get("X-Tavily-Key") or os.getenv("TAVILY_API_KEY")

    # 获取 LLM API 密钥
    claude_api_key = request.headers.get("X-Claude-Key") or os.getenv("ANTHROPIC_API_KEY")
    openai_api_key = request.headers.get("X-OpenAI-Key") or os.getenv("OPENAI_API_KEY")
    groq_api_key = request.headers.get("X-Groq-Key") or os.getenv("GROQ_API_KEY")

    # 验证 Tavily API 密钥
    if not tavily_api_key:
        raise HTTPException(status_code=400, detail="缺少 Tavily API 密钥")

    try:
        check_api_key(api_key=tavily_api_key)
    except Exception as e:
        logger.error(f"Tavily API 密钥验证失败: {e}")
        raise HTTPException(status_code=401, detail=f"Tavily API 密钥验证失败: {str(e)}")

    # 创建主 LLM（用于智能体推理）
    try:
        if body.llm_provider == LLMProvider.CLAUDE:
            main_llm = LLMConfig.create_claude(
                model=body.llm_model,
                api_key=claude_api_key,
                temperature=0.7,
                max_tokens=4096,
                streaming=True
            )
        elif body.llm_provider == LLMProvider.OPENAI:
            main_llm = LLMConfig.create_openai(
                model=body.llm_model,
                api_key=openai_api_key,
                temperature=1,
                max_tokens=4096,
                streaming=True
            )
        elif body.llm_provider == LLMProvider.GROQ:
            main_llm = LLMConfig.create_groq(
                model=body.llm_model,
                api_key=groq_api_key,
                temperature=0.7,
                max_tokens=4096,
                streaming=True
            )
        else:
            raise ValueError(f"不支持的 LLM 提供商: {body.llm_provider}")
    except Exception as e:
        logger.error(f"创建主 LLM 失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建主 LLM 失败: {str(e)}")

    # 模型清单发现与 auxiliary 角色接入后，再由配置选择独立摘要模型。
    summary_llm = main_llm

    # 选择提示词（每次请求时动态获取，确保日期实时更新）
    if body.agent_type == "fast":
        prompt = get_simple_prompt()
        logger.info(f"使用快速模式，LLM: {body.llm_provider}/{body.llm_model}")
    elif body.agent_type == "deep":
        prompt = get_reasoning_prompt()
        logger.info(f"使用深度思考模式，LLM: {body.llm_provider}/{body.llm_model}")
    else:
        raise HTTPException(status_code=400, detail="无效的智能体类型，请选择 'fast' 或 'deep'")

    # 构建智能体
    try:
        agent_runnable = app.state.agent.build_graph(
            api_key=tavily_api_key,
            llm=main_llm,
            prompt=prompt,
            summary_llm=summary_llm,
            user_message=body.input,
            mode=body.agent_type  # 传递智能体模式（fast/deep）
        )
    except Exception as e:
        logger.error(f"构建智能体失败: {e}")
        raise HTTPException(status_code=500, detail=f"构建智能体失败: {str(e)}")

    # 流式事件生成器
    async def event_generator():
        import json

        config = {"configurable": {"thread_id": body.thread_id}}
        operation_counter = 0
        current_step = 0
        is_final_step = False
        buffer = ""  # 用于累积当前步骤的内容
        event_count = 0
        react_mode = None  # None=未检测, True=ReAct格式, False=直接格式
        buffer_threshold = 50  # 累积足够字符后再判断格式

        # 用于收集完整的响应以便保存
        full_response = ""
        tool_calls_list = []

        try:
            logger.info(f"开始流式处理，用户输入: {body.input[:50]}...")
            async for event in agent_runnable.astream_events(
                input={"messages": [HumanMessage(content=body.input)]},
                config=config,
                version="v2",
            ):
                event_count += 1
                event_type = event.get("event", "unknown")
                logger.info(f"收到事件 #{event_count}: {event_type}")

                # 收集聊天模型流式内容并实时输出
                if event["event"] == "on_chat_model_stream":
                    content = event["data"]["chunk"]
                    logger.info(f"on_chat_model_stream: content={content}, has content attr={hasattr(content, 'content')}")
                    if hasattr(content, "content"):
                        logger.info(f"content.content={content.content}, type={type(content.content)}")
                    if hasattr(content, "content") and content.content:
                        langgraph_step = event.get("metadata", {}).get("langgraph_step", 0)

                        # 检测是否进入新的步骤
                        if langgraph_step > current_step:
                            logger.info(f"进入新步骤: {langgraph_step}")
                            # 清空缓冲区，开始新步骤
                            buffer = ""
                            current_step = langgraph_step

                        # 提取文本内容（过滤tool_use等非文本内容）
                        text_content = ""
                        if isinstance(content.content, list):
                            for item in content.content:
                                if isinstance(item, dict):
                                    # 只提取 text 类型的内容，跳过 tool_use
                                    if item.get("type") == "text" and "text" in item:
                                        text_content += item["text"]
                                elif isinstance(item, str):
                                    text_content += item
                                # 跳过其他类型（如 tool_use）
                        else:
                            text_content = str(content.content)

                        if text_content:
                            buffer += text_content
                            full_response += text_content  # 收集完整响应
                            logger.info(f"收到文本内容 (长度 {len(text_content)}): {text_content[:50]}")

                            # 首次检测格式：累积足够字符后判断是否为 ReAct 格式
                            if react_mode is None and len(buffer) >= buffer_threshold:
                                react_markers = ["Question:", "Thought:", "Action:", "Action Input:", "Observation:"]
                                if any(marker in buffer for marker in react_markers):
                                    react_mode = True
                                    logger.info("检测到 ReAct 格式，等待 Final Answer")
                                else:
                                    react_mode = False
                                    logger.info("检测到直接格式，开始流式输出")
                                    # 输出已累积的内容
                                    yield (
                                        json.dumps({
                                            "type": "chatbot",
                                            "content": buffer,
                                        }, ensure_ascii=False)
                                        + "\n"
                                    )
                                    buffer = ""

                            # ReAct 格式处理
                            if react_mode == True:
                                # 检测 "Final Answer:"
                                if "Final Answer:" in buffer and not is_final_step:
                                    is_final_step = True
                                    logger.info("检测到 Final Answer，开始输出最终答案")
                                    # 提取 Final Answer 之后的内容
                                    parts = buffer.split("Final Answer:", 1)
                                    if len(parts) > 1:
                                        final_answer_text = parts[1].strip()
                                        if final_answer_text:
                                            yield (
                                                json.dumps({
                                                    "type": "chatbot",
                                                    "content": final_answer_text,
                                                }, ensure_ascii=False)
                                                + "\n"
                                            )
                                    buffer = ""
                                # 已进入 Final Answer 阶段，过滤 ReAct 标记
                                elif is_final_step:
                                    should_output = True
                                    for pattern in ["Question:", "Thought:", "Action:", "Action Input:", "Observation:"]:
                                        if pattern in text_content:
                                            should_output = False
                                            break
                                    if should_output and text_content.strip():
                                        logger.info(f"输出文本块: {text_content[:30]}")
                                        yield (
                                            json.dumps({
                                                "type": "chatbot",
                                                "content": text_content,
                                            }, ensure_ascii=False)
                                            + "\n"
                                        )
                            # 直接格式处理：实时流式输出
                            elif react_mode == False:
                                logger.info(f"直接输出: {text_content[:30]}")
                                yield (
                                    json.dumps({
                                        "type": "chatbot",
                                        "content": text_content,
                                    }, ensure_ascii=False)
                                    + "\n"
                                )

                # 工具开始调用
                elif event["event"] == "on_tool_start":
                    tool_name = event.get("name", "unknown_tool")
                    tool_input = event["data"].get("input", {})

                    # 安全序列化工具输入
                    try:
                        if isinstance(tool_input, dict):
                            serializable_input = {k: str(v) for k, v in tool_input.items()}
                        else:
                            serializable_input = str(tool_input)
                    except:
                        serializable_input = "无法序列化输入"

                    # 确定工具类型
                    tool_type = "search"
                    if tool_name and "extract" in tool_name.lower():
                        tool_type = "extract"
                    elif tool_name and "crawl" in tool_name.lower():
                        tool_type = "crawl"

                    yield (
                        json.dumps({
                            "type": "tool_start",
                            "tool_name": tool_name,
                            "tool_type": tool_type,
                            "operation_index": operation_counter,
                            "content": serializable_input,
                        }, ensure_ascii=False)
                        + "\n"
                    )
                    logger.info(f"工具开始: {tool_name} ({tool_type}) - 操作 {operation_counter}")

                # 工具调用结束
                elif event["event"] == "on_tool_end":
                    tool_name = event.get("name", "unknown_tool")
                    tool_output = event["data"].get("output")

                    # 安全序列化工具输出
                    try:
                        if hasattr(tool_output, "content"):
                            serializable_output = str(tool_output.content)
                        elif isinstance(tool_output, dict):
                            serializable_output = {k: str(v) for k, v in tool_output.items()}
                        elif isinstance(tool_output, list):
                            serializable_output = [str(item) for item in tool_output]
                        else:
                            serializable_output = str(tool_output)
                    except:
                        serializable_output = "无法序列化输出"

                    # 确定工具类型
                    tool_type = "search"
                    if tool_name and "extract" in tool_name.lower():
                        tool_type = "extract"
                    elif tool_name and "crawl" in tool_name.lower():
                        tool_type = "crawl"

                    yield (
                        json.dumps({
                            "type": "tool_end",
                            "tool_name": tool_name,
                            "tool_type": tool_type,
                            "operation_index": operation_counter,
                            "content": serializable_output,
                        }, ensure_ascii=False)
                        + "\n"
                    )
                    logger.info(f"工具结束: {tool_name} ({tool_type}) - 操作 {operation_counter}")
                    operation_counter += 1

        except Exception as e:
            logger.error(f"流式生成错误: {e}", exc_info=True)
            yield (
                json.dumps({
                    "type": "error",
                    "content": f"生成响应时出错: {str(e)}",
                }, ensure_ascii=False)
                + "\n"
            )

        # 流式传输结束后保存会话
        finally:
            try:
                session_manager = get_session_manager()

                # 尝试加载现有会话
                session_data = session_manager.get_session(body.thread_id)

                # 如果会话不存在，创建新会话
                if session_data is None:
                    # 使用第一条消息生成标题
                    title = session_manager.auto_generate_title(body.input)
                    session_data = {
                        "session_id": body.thread_id,
                        "title": title,
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                        "messages": []
                    }

                # 添加用户消息
                session_data["messages"].append({
                    "role": "user",
                    "content": body.input,
                    "timestamp": datetime.now().isoformat()
                })

                # 添加助手响应（如果有完整响应）
                if full_response:
                    assistant_message = {
                        "role": "assistant",
                        "content": full_response,
                        "timestamp": datetime.now().isoformat()
                    }

                    # 如果有工具调用，添加到消息中
                    if tool_calls_list:
                        assistant_message["tool_calls"] = tool_calls_list

                    session_data["messages"].append(assistant_message)

                # 保存会话
                session_manager.save_session(session_data)
                logger.info(f"会话已保存: {body.thread_id}, 标题: {session_data['title']}")
            except Exception as save_error:
                logger.error(f"保存会话失败: {save_error}", exc_info=True)
                # 保存失败不应该影响响应，只记录错误

    return StreamingResponse(event_generator(), media_type="application/json")


# ==================== 会话管理 API ====================

@app.get("/api/sessions")
async def get_sessions():
    """
    获取所有会话列表

    Returns:
        会话列表（仅元数据）
    """
    try:
        session_manager = get_session_manager()
        sessions = session_manager.get_sessions_list()
        return {"sessions": sessions}
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(e)}")


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """
    获取指定会话的详细信息

    Args:
        session_id: 会话ID

    Returns:
        会话详情（包含完整消息列表）
    """
    try:
        session_manager = get_session_manager()
        session_data = session_manager.get_session(session_id)

        if session_data is None:
            raise HTTPException(status_code=404, detail="会话不存在")

        return session_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取会话失败: {str(e)}")


class CreateSessionRequest(BaseModel):
    """创建会话请求模型"""
    session_id: str
    title: str = None


@app.post("/api/sessions")
async def create_session(body: CreateSessionRequest):
    """
    创建新会话

    Args:
        body: 包含 session_id 和可选的 title

    Returns:
        新创建的会话数据
    """
    try:
        session_manager = get_session_manager()
        session_data = session_manager.create_session(
            session_id=body.session_id,
            title=body.title
        )
        return session_data
    except Exception as e:
        logger.error(f"创建会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建会话失败: {str(e)}")


class RenameSessionRequest(BaseModel):
    """重命名会话请求模型"""
    title: str


@app.put("/api/sessions/{session_id}")
async def rename_session(session_id: str, body: RenameSessionRequest):
    """
    重命名会话

    Args:
        session_id: 会话ID
        body: 包含新标题

    Returns:
        操作结果
    """
    try:
        session_manager = get_session_manager()
        success = session_manager.rename_session(session_id, body.title)

        if not success:
            raise HTTPException(status_code=404, detail="会话不存在")

        return {"success": True, "message": "重命名成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重命名会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重命名会话失败: {str(e)}")


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    删除会话

    Args:
        session_id: 会话ID

    Returns:
        操作结果
    """
    try:
        session_manager = get_session_manager()
        success = session_manager.delete_session(session_id)
        return {"success": success, "message": "删除成功"}
    except Exception as e:
        logger.error(f"删除会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除会话失败: {str(e)}")


if __name__ == "__main__":
    # 启动服务器
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(
        app=app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
