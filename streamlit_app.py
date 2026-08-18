"""
Streamlit 智能聊天机器人前端
集成 Tavily Web Agent 功能，支持深度思考模式
"""

import streamlit as st
import requests
import json
import datetime
import time
import uuid
import os
from typing import Dict, List, Optional
from dotenv import load_dotenv
import re

# 加载环境变量
load_dotenv()


# def fix_markdown_format(text: str) -> str:
#     """
#     修复 Markdown 格式问题，确保正确渲染

#     主要修复：
#     - 标题语法：确保 # 后有空格
#     - 列表语法：确保 - 或 * 后有空格
#     """
#     if not text:
#         return text

#     # 修复标题：# 后没有空格的情况
#     # 匹配行首的 1-6 个 # 后直接跟非空格字符
#     text = re.sub(r'^(#{1,6})([^\s#])', r'\1 \2', text, flags=re.MULTILINE)

#     # 修复无序列表：- 或 * 后没有空格
#     text = re.sub(r'^(\s*[-*])([^\s])', r'\1 \2', text, flags=re.MULTILINE)

#     # 修复有序列表：数字. 后没有空格
#     text = re.sub(r'^(\s*\d+\.)([^\s])', r'\1 \2', text, flags=re.MULTILINE)

#     return text

# ==================== 页面配置 ====================
st.set_page_config(
    page_title="Yuan's Chat Agents",
    page_icon="./frontend/public/favicon.ico",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== 配置常量 ====================
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8080")
MIN_TIME_BETWEEN_REQUESTS = datetime.timedelta(seconds=1)
HISTORY_LENGTH = 10  # 保留最近10条消息用于上下文

# ==================== 样式配置 ====================
st.markdown("""
<style>
    .stButton>button {
        width: 100%;
    }
    .tool-card {
        padding: 10px;
        border-radius: 5px;
        margin: 5px 0;
        background-color: #f0f2f6;
    }
    .tool-search {
        border-left: 3px solid #4CAF50;
    }
    .tool-extract {
        border-left: 3px solid #2196F3;
    }
    .tool-crawl {
        border-left: 3px solid #FF9800;
    }
</style>
""", unsafe_allow_html=True)


# ==================== 工具函数 ====================

def detect_api_key_type(api_key: str) -> str:
    """
    自动识别 API 密钥类型

    Returns:
        "claude" | "openai" | "unknown"
    """
    if not api_key:
        return "unknown"

    # Claude API 密钥格式: sk-ant-api03-...
    if api_key.startswith("sk-ant-"):
        return "claude"
    # OpenAI API 密钥格式: sk-... (但不是 sk-ant-)
    elif api_key.startswith("sk-"):
        return "openai"

    return "unknown"


def get_initial_model_id() -> str:
    """为尚未发现清单的端点返回空值，交给用户手填原始模型标识。"""
    return ""


def initialize_session():
    """初始化会话状态"""
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "last_request_time" not in st.session_state:
        st.session_state.last_request_time = None

    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid.uuid4())

    if "tool_calls" not in st.session_state:
        st.session_state.tool_calls = []

    # 会话管理相关状态
    if "current_session_id" not in st.session_state:
        st.session_state.current_session_id = None

    if "sessions_list" not in st.session_state:
        st.session_state.sessions_list = []

    if "show_rename_dialog" not in st.session_state:
        st.session_state.show_rename_dialog = False

    if "rename_session_id" not in st.session_state:
        st.session_state.rename_session_id = None

    # API 密钥 - 统一为 llm_api_key，从环境变量加载
    if "llm_api_key" not in st.session_state:
        # 优先 ANTHROPIC_API_KEY，其次 OPENAI_API_KEY
        st.session_state.llm_api_key = os.getenv("ANTHROPIC_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")

    if "tavily_api_key" not in st.session_state:
        st.session_state.tavily_api_key = os.getenv("TAVILY_API_KEY", "")

    # 智能体配置
    if "agent_type" not in st.session_state:
        st.session_state.agent_type = "fast"

    # 根据密钥类型自动设置提供商
    if "llm_provider" not in st.session_state:
        detected_type = detect_api_key_type(st.session_state.llm_api_key)
        st.session_state.llm_provider = detected_type if detected_type != "unknown" else "claude"

    if "llm_model" not in st.session_state:
        st.session_state.llm_model = get_initial_model_id()


def format_time(timestamp: datetime.datetime) -> str:
    """格式化时间戳"""
    return timestamp.strftime("%H:%M:%S")


def check_backend_health() -> bool:
    """检查后端服务健康状态"""
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=3)
        return response.status_code == 200
    except:
        return False


# ==================== 会话管理功能 ====================

def load_sessions_list():
    """从后端加载会话列表"""
    try:
        response = requests.get(f"{BACKEND_URL}/api/sessions", timeout=5)
        if response.status_code == 200:
            data = response.json()
            st.session_state.sessions_list = data.get("sessions", [])
        else:
            st.error(f"加载会话列表失败: {response.status_code}")
    except Exception as e:
        st.error(f"加载会话列表失败: {e}")


def load_session(session_id: str):
    """加载指定会话的详细信息"""
    try:
        response = requests.get(f"{BACKEND_URL}/api/sessions/{session_id}", timeout=5)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            st.error("会话不存在")
            return None
        else:
            st.error(f"加载会话失败: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"加载会话失败: {e}")
        return None


def switch_session(session_id: str):
    """切换到指定会话"""
    session_data = load_session(session_id)

    if session_data:
        # 更新当前会话ID和thread_id
        st.session_state.current_session_id = session_id
        st.session_state.thread_id = session_id

        # 加载历史消息
        st.session_state.messages = session_data.get("messages", [])

        # 转换时间戳格式
        for msg in st.session_state.messages:
            if "timestamp" in msg and isinstance(msg["timestamp"], str):
                msg["timestamp"] = datetime.datetime.fromisoformat(msg["timestamp"])

        st.rerun()


def create_new_session():
    """创建新会话"""
    # 生成新的会话ID
    new_session_id = str(uuid.uuid4())

    try:
        response = requests.post(
            f"{BACKEND_URL}/api/sessions",
            json={"session_id": new_session_id, "title": new_session_id},  # 使用 session_id 作为默认标题
            timeout=5
        )

        if response.status_code == 200:
            # 切换到新会话
            st.session_state.current_session_id = new_session_id
            st.session_state.thread_id = new_session_id
            st.session_state.messages = []

            # 重新加载会话列表
            load_sessions_list()
            st.rerun()
        else:
            st.error(f"创建会话失败: {response.status_code}")
    except Exception as e:
        st.error(f"创建会话失败: {e}")


def delete_session_ui(session_id: str):
    """删除会话"""
    try:
        response = requests.delete(f"{BACKEND_URL}/api/sessions/{session_id}", timeout=5)

        if response.status_code == 200:
            # 如果删除的是当前会话，清空消息
            if st.session_state.current_session_id == session_id:
                st.session_state.current_session_id = None
                st.session_state.messages = []
                st.session_state.thread_id = str(uuid.uuid4())

            # 重新加载会话列表
            load_sessions_list()
            st.rerun()
        else:
            st.error(f"删除会话失败: {response.status_code}")
    except Exception as e:
        st.error(f"删除会话失败: {e}")


def rename_session_ui(session_id: str, new_title: str):
    """重命名会话"""
    try:
        response = requests.put(
            f"{BACKEND_URL}/api/sessions/{session_id}",
            json={"title": new_title},
            timeout=5
        )

        if response.status_code == 200:
            # 重新加载会话列表
            load_sessions_list()
            # 不在这里调用 st.rerun()，让调用者控制
        else:
            st.error(f"重命名会话失败: {response.status_code}")
    except Exception as e:
        st.error(f"重命名会话失败: {e}")


def stream_agent_response(user_input: str, config: Dict) -> tuple:
    """
    调用后端智能体并流式接收响应

    Args:
        user_input: 用户输入
        config: 配置字典（API 密钥、智能体类型等）

    Returns:
        (完整响应文本, 工具调用列表)
    """
    # 准备请求头
    headers = {
        "Content-Type": "application/json",
    }

    # 添加 API 密钥到请求头
    if config.get("tavily_api_key"):
        headers["X-Tavily-Key"] = config["tavily_api_key"]

    # 根据检测到的密钥类型传递到正确的请求头
    llm_api_key = config.get("llm_api_key", "")
    key_type = detect_api_key_type(llm_api_key)
    if key_type == "claude":
        headers["X-Claude-Key"] = llm_api_key
    elif key_type == "openai":
        headers["X-OpenAI-Key"] = llm_api_key

    # 准备请求体
    payload = {
        "input": user_input,
        "thread_id": config.get("thread_id", str(uuid.uuid4())),
        "agent_type": config.get("agent_type", "fast"),
        "llm_provider": config.get("llm_provider", "claude"),
        "llm_model": config.get("llm_model", ""),
    }

    # 发送流式请求
    try:
        response = requests.post(
            f"{BACKEND_URL}/stream_agent",
            headers=headers,
            json=payload,
            stream=True,
            timeout=120
        )
        response.raise_for_status()

        full_response = ""
        tool_calls = []

        # 处理流式响应
        for line in response.iter_lines():
            if line:
                try:
                    event = json.loads(line.decode('utf-8'))

                    if event["type"] == "chatbot":
                        # 聊天机器人响应
                        full_response += event["content"]
                        yield event["content"], None

                    elif event["type"] == "tool_start":
                        # 工具开始调用
                        tool_calls.append({
                            "type": "start",
                            "tool_name": event["tool_name"],
                            "tool_type": event["tool_type"],
                            "operation_index": event["operation_index"],
                            "content": event["content"]
                        })
                        yield None, tool_calls[-1]

                    elif event["type"] == "tool_end":
                        # 工具调用结束
                        tool_calls.append({
                            "type": "end",
                            "tool_name": event["tool_name"],
                            "tool_type": event["tool_type"],
                            "operation_index": event["operation_index"],
                            "content": event["content"]
                        })
                        yield None, tool_calls[-1]

                    elif event["type"] == "error":
                        # 错误事件
                        st.error(f"❌ {event['content']}")
                        return

                except json.JSONDecodeError:
                    continue

        return full_response, tool_calls

    except requests.exceptions.RequestException as e:
        st.error(f"❌ 请求失败: {str(e)}")
        return None, []


def render_tool_call(tool_event: Dict):
    """渲染工具调用卡片"""
    tool_type = tool_event.get("tool_type", "search")
    tool_name = tool_event.get("tool_name", "未知工具")
    operation_index = tool_event.get("operation_index", 0)

    # 工具友好名称映射
    tool_name_map = {
        "TavilySearch": "Tavily 搜索",
        "TavilyExtract": "Tavily 内容提取",
        "TavilyCrawl": "Tavily 网站爬取",
        "tavily_search_results_json": "Tavily 搜索",
        "tavily_extract": "Tavily 内容提取",
        "tavily_crawl": "Tavily 网站爬取"
    }

    # 工具图标和颜色
    tool_icons = {
        "search": "🔍",
        "extract": "📄",
        "crawl": "🕷️"
    }

    tool_colors = {
        "search": "#4CAF50",
        "extract": "#2196F3",
        "crawl": "#FF9800"
    }

    # 工具描述
    tool_descriptions = {
        "search": "在互联网上搜索相关信息",
        "extract": "从指定网页提取详细内容",
        "crawl": "深度爬取网站结构和内容"
    }

    icon = tool_icons.get(tool_type, "🔧")
    color = tool_colors.get(tool_type, "#757575")
    friendly_name = tool_name_map.get(tool_name, tool_name)
    description = tool_descriptions.get(tool_type, "执行工具操作")

    if tool_event["type"] == "start":
        # 工具开始调用
        with st.expander(f"{icon} 正在执行: {friendly_name} - 操作 #{operation_index + 1}", expanded=False):
            st.markdown(f"**🎯 任务**: {description}")
            st.markdown(f"**⏳ 状态**: 运行中...")

            # 显示输入参数
            content = tool_event.get('content', {})
            if content and content != 'N/A':
                st.markdown("**📥 输入参数**:")
                if isinstance(content, dict):
                    for key, value in content.items():
                        st.write(f"- **{key}**: {value}")
                else:
                    st.write(f"```\n{content}\n```")

    elif tool_event["type"] == "end":
        # 工具调用完成
        with st.expander(f"{icon} {friendly_name} - 操作 #{operation_index + 1} 已完成", expanded=False):
            st.markdown(f"**🎯 任务**: {description}")

            content = tool_event.get('content', {})

            # 尝试解析 JSON 字符串
            if isinstance(content, str):
                try:
                    import json
                    content = json.loads(content)
                except:
                    pass

            if isinstance(content, dict):
                # 显示摘要
                if 'summary' in content:
                    st.markdown("**📝 内容摘要**:")
                    summary_text = content.get('summary', '')
                    if len(summary_text) > 800:
                        st.write(summary_text[:800] + "...")
                        with st.expander("查看完整摘要"):
                            st.write(summary_text)
                    else:
                        st.write(summary_text)

                # 显示来源链接
                if 'urls' in content and content['urls']:
                    st.markdown("**🔗 来源链接**:")
                    for idx, url in enumerate(content['urls'][:10], 1):  # 最多显示10个链接
                        st.markdown(f"{idx}. [{url}]({url})")

                # 显示原始数据（如果有其他字段）
                other_fields = {k: v for k, v in content.items() if k not in ['summary', 'urls', 'favicons']}
                if other_fields:
                    with st.expander("📊 查看原始数据"):
                        st.json(other_fields)

            elif isinstance(content, list):
                st.markdown("**📊 结果列表**:")
                for idx, item in enumerate(content[:5], 1):
                    st.write(f"{idx}. {item}")
                if len(content) > 5:
                    with st.expander(f"查看全部 {len(content)} 条结果"):
                        for idx, item in enumerate(content, 1):
                            st.write(f"{idx}. {item}")

            else:
                st.markdown("**📤 输出结果**:")
                result_str = str(content)
                if len(result_str) > 500:
                    st.write(result_str[:500] + "...")
                    with st.expander("查看完整输出"):
                        st.write(result_str)
                else:
                    st.write(result_str)


# ==================== 侧边栏配置 ====================

def render_sidebar():
    """渲染侧边栏"""
    with st.sidebar:
        st.title("⚙️ 配置")

        # ===== API 密钥管理 =====
        with st.expander("🔑 API 密钥", expanded=True):
            # LLM API 密钥（自动识别 Claude 或 OpenAI）
            llm_key = st.text_input(
                "LLM API 密钥",
                type="password",
                value=st.session_state.llm_api_key,
                help="输入 Claude (sk-ant-...) 或 OpenAI (sk-...) API 密钥，系统自动识别"
            )
            if llm_key != st.session_state.llm_api_key:
                st.session_state.llm_api_key = llm_key
                # 自动更新提供商和模型
                new_type = detect_api_key_type(llm_key)
                if new_type != "unknown":
                    st.session_state.llm_provider = new_type
                    st.session_state.llm_model = get_initial_model_id()

            # Tavily API 密钥
            tavily_key = st.text_input(
                "Tavily API 密钥",
                type="password",
                value=st.session_state.tavily_api_key,
                help="输入您的 Tavily API 密钥（用于 Web 搜索）"
            )
            if tavily_key != st.session_state.tavily_api_key:
                st.session_state.tavily_api_key = tavily_key

            # 密钥状态指示
            col1, col2 = st.columns(2)
            with col1:
                key_type = detect_api_key_type(st.session_state.llm_api_key)
                if key_type == "claude":
                    st.success("✅ Claude")
                elif key_type == "openai":
                    st.success("✅ OpenAI")
                else:
                    st.error("❌ LLM 密钥")
            with col2:
                if st.session_state.tavily_api_key:
                    st.success("✅ Tavily")
                else:
                    st.error("❌ Tavily")

        # ===== 智能体配置 =====
        with st.expander("🤖 智能体设置", expanded=True):
            # 智能体模式
            agent_type = st.radio(
                "智能体模式",
                options=["fast", "deep"],
                format_func=lambda x: "⚡ 快速模式" if x == "fast" else "🧠 深度思考模式",
                index=0 if st.session_state.agent_type == "fast" else 1,
                help="快速模式：快速响应，适合简单问题\n深度思考模式：深度研究，适合复杂查询"
            )
            if agent_type != st.session_state.agent_type:
                st.session_state.agent_type = agent_type

            # LLM 提供商选择（根据密钥自动检测）
            current_provider = st.session_state.llm_provider
            provider_options = ["claude", "openai"]
            provider_labels = {
                "claude": "Claude",
                "openai": "OpenAI"
            }

            selected_provider = st.radio(
                "LLM 提供商",
                options=provider_options,
                format_func=lambda x: provider_labels[x],
                index=provider_options.index(current_provider) if current_provider in provider_options else 0,
                help="根据 API 密钥自动检测，也可手动选择"
            )
            if selected_provider != st.session_state.llm_provider:
                st.session_state.llm_provider = selected_provider
                st.session_state.llm_model = get_initial_model_id()

            # 模型清单由后端运行时发现；旧 Streamlit 路径在发现接口接入前只允许手填。
            model_label = f"{st.session_state.llm_provider.upper()} 模型标识"
            selected_model = st.text_input(
                model_label,
                value=st.session_state.llm_model,
                help="填写端点 /v1/models 返回的原始模型标识；发现失败时不会猜测或替换。",
            )
            if selected_model != st.session_state.llm_model:
                st.session_state.llm_model = selected_model

        # ===== 后端状态 =====
        st.divider()
        st.subheader("📊 系统状态")

        backend_healthy = check_backend_health()
        if backend_healthy:
            st.success("✅ 后端服务正常")
        else:
            st.error("❌ 后端服务未运行")
            st.info("请确保后端服务已启动：\n```bash\npython app.py\n```")

        # ===== 会话历史 =====
        st.divider()
        with st.expander("📝 会话历史", expanded=False):
            # 新建会话按钮
            if st.button("➕ 新建会话", use_container_width=True, key="new_session_btn"):
                create_new_session()

            # 加载会话列表（首次加载）
            if not st.session_state.sessions_list:
                load_sessions_list()

            # 显示会话列表
            if st.session_state.sessions_list:
                st.markdown("**历史会话**")
                for session in st.session_state.sessions_list:
                    session_id = session["session_id"]
                    title = session["title"]
                    updated_at = session.get("updated_at", "")

                    # 格式化时间显示
                    if updated_at:
                        try:
                            dt = datetime.datetime.fromisoformat(updated_at)
                            time_str = dt.strftime("%m-%d %H:%M")
                        except:
                            time_str = ""
                    else:
                        time_str = ""

                    # 判断是否为当前会话
                    is_current = st.session_state.current_session_id == session_id

                    # 会话卡片容器
                    with st.container():
                        # 检查是否正在重命名此会话
                        is_renaming = (st.session_state.show_rename_dialog and
                                      st.session_state.rename_session_id == session_id)

                        if is_renaming:
                            # 重命名模式：显示输入框
                            col1, col2 = st.columns([8, 2])

                            with col1:
                                new_title = st.text_input(
                                    "新标题",
                                    value=title,
                                    key=f"rename_input_{session_id}",
                                    label_visibility="collapsed",
                                    placeholder="输入新标题..."
                                )

                            with col2:
                                # 确认和取消按钮
                                col_ok, col_cancel = st.columns(2)
                                with col_ok:
                                    if st.button("✓", key=f"confirm_{session_id}", help="确认", use_container_width=True):
                                        if new_title and new_title.strip():
                                            rename_session_ui(session_id, new_title.strip())
                                        st.session_state.show_rename_dialog = False
                                        st.session_state.rename_session_id = None
                                        st.rerun()
                                with col_cancel:
                                    if st.button("✗", key=f"cancel_{session_id}", help="取消", use_container_width=True):
                                        st.session_state.show_rename_dialog = False
                                        st.session_state.rename_session_id = None
                                        st.rerun()
                        else:
                            # 正常显示模式
                            col1, col2, col3 = st.columns([1.8, 1, 1])

                            with col1:
                                # 会话标题按钮
                                button_label = f"{'' if is_current else ''}{title[:3]}{'...' if len(title) > 3 else ''}"
                                if st.button(
                                    button_label,
                                    key=f"session_{session_id}",
                                    help=f"{title}\n更新时间: {time_str}",
                                    use_container_width=True,
                                    type="primary" if is_current else "secondary"
                                ):
                                    if not is_current:
                                        switch_session(session_id)

                            with col2:
                                # 重命名按钮
                                if st.button("✏️", key=f"rename_{session_id}", help="重命名", use_container_width=True):
                                    st.session_state.show_rename_dialog = True
                                    st.session_state.rename_session_id = session_id
                                    st.rerun()

                            with col3:
                                # 删除按钮
                                if st.button("🗑️", key=f"delete_{session_id}", help="删除", use_container_width=True):
                                    delete_session_ui(session_id)

                        # 第二行：显示时间（仅在非重命名模式下显示）
                        if not is_renaming and time_str:
                            st.caption(f"🕒 {time_str}")

                        st.markdown("---")  # 使用markdown分隔线，更轻量

            else:
                st.info("暂无会话历史")

        # ===== 关于 =====
        st.divider()
        with st.expander("ℹ️ 关于"):
            st.markdown("""
            **Yuan's Chat Agents**

            一个集成了 Web 搜索、内容提取和深度思考能力的智能助手。

            **功能特点**:
            - 🔍 实时 Web 搜索
            - 📄 网页内容提取
            - 🕷️ 网站深度爬取
            - 🧠 深度思考推理
            - 💬 对话记忆

            **技术栈**:
            - Streamlit (前端)
            - FastAPI (后端)
            - LangGraph (智能体框架)
            - Tavily (Web 工具)
            - Claude / OpenAI (语言模型)

            **作者**: Yuan
            **博客**: [blog.geekie.site](https://blog.geekie.site)
            """)


# ==================== 主应用 ====================

def main():
    """主应用程序"""
    initialize_session()

    # 标题
    st.title("🤖 Yuan's Chat Agents")
    st.caption("集成 Web 搜索与深度思考能力的智能助手")

    # 渲染侧边栏
    render_sidebar()

    # 检查后端服务
    if not check_backend_health():
        st.error("❌ 后端服务未运行，请先启动后端服务")
        st.code("python app.py", language="bash")
        st.stop()

    # 显示历史消息
    for msg in st.session_state.messages:
        role = msg["role"]
        content = msg["content"]
        timestamp = msg.get("timestamp")

        with st.chat_message(role):
            if timestamp:
                st.caption(f"🕒 {format_time(timestamp)}")
            st.markdown(content)
            # st.markdown(fix_markdown_format(content))

            # 显示工具调用（如果有）
            if role == "assistant" and "tool_calls" in msg and msg["tool_calls"]:
                with st.expander(f"🔧 查看工具调用 ({len([t for t in msg['tool_calls'] if t['type'] == 'end'])} 次)", expanded=False):
                    for tool_call in msg["tool_calls"]:
                        if tool_call["type"] == "end":
                            render_tool_call(tool_call)

    # 聊天输入
    if prompt := st.chat_input("输入您的问题..."):
        # 检查请求频率限制
        current_time = datetime.datetime.now()
        if (st.session_state.last_request_time and
                current_time - st.session_state.last_request_time < MIN_TIME_BETWEEN_REQUESTS):

            remaining = MIN_TIME_BETWEEN_REQUESTS - (current_time - st.session_state.last_request_time)
            st.warning(f"请等待 {remaining.total_seconds():.1f} 秒后再发送消息")
            st.stop()

        # 添加用户消息
        user_msg = {
            "role": "user",
            "content": prompt,
            "timestamp": current_time
        }
        st.session_state.messages.append(user_msg)

        # 显示用户消息
        with st.chat_message("user"):
            st.caption(f"🕒 {format_time(current_time)}")
            st.markdown(prompt)

        # 生成助手回复
        with st.chat_message("assistant"):
            timestamp_placeholder = st.empty()
            message_placeholder = st.empty()
            tool_container = st.container()

            timestamp_placeholder.caption(f"🕒 {format_time(datetime.datetime.now())}")

            try:
                # 准备配置
                config = {
                    "tavily_api_key": st.session_state.tavily_api_key,
                    "llm_api_key": st.session_state.llm_api_key,
                    "thread_id": st.session_state.thread_id,
                    "agent_type": st.session_state.agent_type,
                    "llm_provider": st.session_state.llm_provider,
                    "llm_model": st.session_state.llm_model,
                }

                # 流式接收响应
                full_response = ""
                tool_calls = []

                with st.spinner("🤔 正在板砖..."):
                    for content, tool_event in stream_agent_response(prompt, config):
                        if content:
                            # 更新响应文本
                            full_response += content
                            #message_placeholder.markdown(fix_markdown_format(full_response) + "▌")
                            message_placeholder.markdown(full_response)

                        if tool_event:
                            # 记录工具调用
                            tool_calls.append(tool_event)

                            # 实时显示工具调用
                            with tool_container:
                                render_tool_call(tool_event)

                # 显示最终响应
                #message_placeholder.markdown(fix_markdown_format(full_response))
                message_placeholder.markdown(full_response)

                # 保存助手消息
                assistant_msg = {
                    "role": "assistant",
                    "content": full_response,
                    "timestamp": datetime.datetime.now(),
                    "tool_calls": tool_calls
                }
                st.session_state.messages.append(assistant_msg)

                # 更新请求时间
                st.session_state.last_request_time = current_time

            except Exception as e:
                error_msg = f"抱歉，发生了错误: {str(e)}"
                message_placeholder.error(error_msg)

                # 保存错误消息
                error_msg_obj = {
                    "role": "assistant",
                    "content": error_msg,
                    "timestamp": datetime.datetime.now()
                }
                st.session_state.messages.append(error_msg_obj)


if __name__ == "__main__":
    main()
