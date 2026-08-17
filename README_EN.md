# 🤖 Yuan's ChatAgents

<div align="center">

**An intelligent agent assistant integrated with Web search, content extraction, and deep thinking capabilities**

![Python](https://img.shields.io/badge/Python-3.11--3.12-blue.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.32+-red.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

**English** | [简体中文](./README.md)

</div>

---

## 📖 Project Overview

This is an intelligent chatbot with web search capabilities featuring:

1. **Simple Chatbot** (based on Streamlit + Claude)
2. **Tavily Web Agent** (based on LangGraph + Tavily)

Through a hybrid architecture (Streamlit frontend + FastAPI backend), it provides powerful web search, content extraction, and deep thinking capabilities.

## ✨ Features

### 🎯 Core Features
- **💬 Interactive Chat Interface**: Clean and intuitive UI based on Streamlit
- **🔍 Real-time Web Search**: Search for latest information via Tavily
- **📄 Web Content Extraction**: Precise extraction of key content from web pages
- **🕷️ Deep Website Crawling**: Deep crawling of nested website links
- **🧠 Deep Thinking Mode**: Supports deep reasoning for complex queries
- **⚡ Fast Response Mode**: Quick answers for simple questions
- **💭 Conversation Memory**: Conversation history management based on LangGraph
- **🔄 Streaming Response**: Real-time streaming output for better interaction experience

### 🛠️ Advanced Features
- **🔑 Flexible API Key Management**: Supports multiple APIs including Claude, Tavily, etc.
- **🎨 Multi-model Support**: Supports Claude Haiku/Sonnet/Opus, with OpenAI/Groq interfaces reserved
- **📊 Tool Call Visualization**: Real-time display of search/extract/crawl processes
- **🎯 Agent Type Switching**: Fast mode vs. deep thinking mode
- **💾 Session Management**: Supports multiple sessions with conversation history
- **🐳 Docker Support**: One-click containerized deployment

## 🏗️ Architecture Design

![Untitled-2025-12-21-00381](https://img.geekie.site/i/adImg/2025/12/21/023202.png)


### Tech Stack

| Layer | Technology | Description |
|------|------|------|
| **Frontend** | Streamlit | Simple Python web framework |
| **Backend** | FastAPI | High-performance async API framework |
| **Agent** | LangGraph | Agent orchestration framework |
| **LLM** | Claude OpenAI | Primary language model |
| **Tools** | Tavily | Web search/extract/crawl |
| **Others** | Docker, python-dotenv | Containerization and configuration management |

## 🚀 Quick Start

### Prerequisites

- **Python**: 3.11–3.12
- **API Keys**:
  - [Anthropic Claude API](https://console.anthropic.com/)
  - [Tavily API](https://tavily.com/)

### Installation Steps

#### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd intelligent-chatbot
```

#### 2. Install Dependencies

After installing [uv](https://docs.astral.sh/uv/), run this from the repository root:

```bash
uv sync --project backend
```

#### 3. Configure Environment Variables

```bash
# Copy sample configuration file
cp .env.sample .env

# Edit .env file and fill in your API keys
# ANTHROPIC_API_KEY=sk-ant-api-your-key-here
# TAVILY_API_KEY=tvly-your-key-here
```

#### 4. Start the Application

**Method A: Start Separately (Recommended for Development)**

```bash
# Terminal 1: Start backend
uv run --project backend python app.py

# Terminal 2: Start frontend
uv run --project backend streamlit run streamlit_app.py
```

**Method B: Use Docker Compose**

```bash
docker-compose up --build
```

#### 5. Access the Application

- **Frontend**: http://localhost:8501
- **Backend API**: http://localhost:8080
- **API Docs**: http://localhost:8080/docs

## 📖 Usage Guide

### Basic Usage

1. **Configure API Keys**
   - Enter Claude and Tavily API keys in the sidebar
   - Or pre-configure in `.env` file

2. **Select Agent Mode**
   - **⚡ Fast Mode**: For simple questions, quick response
     - Uses `basic` search depth, faster and more cost-effective
     - Returns 3 search results (balanced configuration)
     - Crawl limit: 5 pages
     - No images (reduces response size)
     - Both TavilySearch and TavilyExtract use basic level
   - **🧠 Deep Thinking Mode**: For complex queries, in-depth research
     - Uses `advanced` search depth, more comprehensive but higher cost
     - Returns 5 search results
     - Crawl limit: 15 pages
     - Includes images (supports visual content)
     - Both TavilySearch and TavilyExtract use advanced level
   - **🎯 Advanced Parameters Support**:
     - `topic`: Search topic classification (general/news/finance)
     - `time_range`: Time range filtering (day/week/month/year)

3. **Choose Claude Model**
   - **Haiku**: Fast and economical
   - **Sonnet**: Balanced performance (Recommended)
   - **Opus**: Best performance

4. **Start Conversation**
   - Enter your question in the input box
   - View tool call processes in real-time
   - Get detailed answers with citations

### Advanced Features

#### Tool Call Display

The agent automatically selects appropriate tools based on the question:

- **🔍 TavilySearch**: Search relevant web pages
- **📄 TavilyExtract**: Extract web page content
- **🕷️ TavilyCrawl**: Deep crawl websites

Each tool call is displayed in real-time in the UI:
- Tool name and type
- Input parameters
- Output summary and source links

#### Session Management

- Each session has a unique ID
- Supports conversation history memory
- Click "New Session" to start a new conversation

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required | Default |
|--------|------|------|--------|
| `ANTHROPIC_API_KEY` | Claude API key | ✅ | - |
| `TAVILY_API_KEY` | Tavily API key | ✅ | - |
| `OPENAI_API_KEY` | OpenAI API key | ✅ | - |
| `GROQ_API_KEY` | Groq API key (future) | ❌ | - |
| `PORT` | Backend port | ✅ | 8080 |

### Agent Configuration

Customizable in `streamlit_app.py`:

```python
# Request rate limit
MIN_TIME_BETWEEN_REQUESTS = datetime.timedelta(seconds=1)

# Conversation history length
HISTORY_LENGTH = 10

# Backend URL
BACKEND_URL = "http://localhost:8080"
```

New LLM models can be added in `backend/llm_config.py`.

## 📁 Project Structure

```
intelligent-chatbot/
├── backend/                    # Backend module
│   ├── __init__.py
│   ├── agent.py               # Web agent (LangGraph)
│   ├── llm_config.py          # LLM configuration management
│   ├── prompts.py             # Prompt templates
│   ├── session_manager.py     # Session manager
│   └── utils.py               # Utility functions
├── docs/                       # Documentation directory
│   └── TAVILY_PARAMETERS.md   # Tavily parameters documentation
├── .streamlit/                 # Streamlit configuration
├── app.py                      # FastAPI backend server
├── streamlit_app.py            # Streamlit frontend application
├── backend/pyproject.toml      # Python project metadata
├── backend/uv.lock             # Locked dependencies
├── .env                        # Environment variables (local)
├── .env.sample                 # Environment variable example
├── .gitignore                  # Git ignore file
├── Dockerfile                  # Docker image
├── docker-compose.yml          # Docker Compose configuration
├── frontend/                   # Frontend assets
│   └── public/favicon.ico      # Website icon
├── setup.bat                   # Windows setup script
├── start.bat                   # Windows startup script
├── README.md                   # Project documentation (Chinese)
└── README_EN.md                # Project documentation (English)
```

## 🎯 Feature Demonstrations

### Example Conversation 1: Simple Q&A (Fast Mode)

**User**: What is artificial intelligence?

**Agent**:
- No tool calls needed
- Direct answer based on baseline knowledge
- Response time < 3 seconds

### Example Conversation 2: Real-time Search (Fast Mode)

**User**: What are the latest AI technology trends?

**Agent**:
1. 🔍 Call TavilySearch (topic=news, time_range=month)
2. 📊 Display search results
3. 💬 Generate answer with citations

### Example Conversation 3: In-depth Research (Deep Thinking Mode)

**User**: Analyze the differences between LangChain and LangGraph, and provide usage recommendations

**Agent**:
1. 🔍 Search LangChain official documentation
2. 📄 Extract key page content
3. 🔍 Search LangGraph documentation
4. 📄 Extract comparison information
5. 🧠 Deep analysis and generate detailed report

## 🐛 Troubleshooting

### 1. Backend Service Cannot Start

**Issue**: `ConnectionRefusedError` or backend status shows "Not Running"

**Solution**:
```bash
# Check port usage
netstat -ano | findstr :8080  # Windows
lsof -i :8080                 # macOS/Linux

# Ensure backend is started
python app.py
```

### 2. API Key Error

**Issue**: `401 Unauthorized` or "API key validation failed"

**Solution**:
- Check API key format:
  - Claude: `sk-ant-api-...`
  - Tavily: `tvly-...`
- Confirm key is not expired and has sufficient quota
- Check `.env` file or sidebar input

### 3. Tool Call Failure

**Issue**: Tool call timeout or returns error

**Solution**:
- Check network connection
- Confirm Tavily API quota is sufficient
- Reduce concurrent request count

### 4. Streaming Response Interruption

**Issue**: Response stops midway or is incomplete

**Solution**:
- Increase request timeout
- Check backend logs (`app.py` output)
- Confirm LLM quota is sufficient

## 🔮 Future Plans

- [ ] Support more LLM providers (OpenAI, Groq, etc.)
- [ ] Add file upload and analysis functionality
- [ ] Implement conversation export (Markdown/PDF)
- [ ] Add voice input/output
- [ ] Support multi-language interface
- [ ] Optimize streaming response performance
- [ ] Add conversation rating and feedback
- [ ] Integrate more tools (calculator, code executor, etc.)

## 🤝 Contributing

Contributions are welcome! Feel free to submit Issues or Pull Requests.

### Contribution Process

1. Fork this repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Create a Pull Request

## 📄 License

This project is open-sourced under the [MIT License](LICENSE).

## 👤 Author

**Yuan**

- 📝 Blog: [https://blog.geekie.site](https://blog.geekie.site)
- 📧 Email: [yuan.sn@outlook.com](mailto:yuan.sn@outlook.com)
- 🔗 GitHub: [EllisYuan](https://github.com/EllisYuan)

## 🙏 Acknowledgements

This project is built on the following open-source projects:

- [Streamlit](https://streamlit.io/) - Simple Python web framework
- [FastAPI](https://fastapi.tiangolo.com/) - High-performance API framework
- [LangChain](https://www.langchain.com/) - LLM application framework
- [LangGraph](https://langchain-ai.github.io/langgraph/) - Agent orchestration framework
- [Anthropic Claude](https://www.anthropic.com/) - Powerful language model
- [Tavily](https://tavily.com/) - AI-optimized search API

---

<div align="center">

**⭐ If this project helps you, please give it a star!**

Made with ❤️ by Yuan

</div>
