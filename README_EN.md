# 🤖 Yuan's ChatAgents

<div align="center">

**An intelligent agent assistant integrated with Web search, content extraction, and deep thinking capabilities**

![Python](https://img.shields.io/badge/Python-3.11--3.12-blue.svg)
![React](https://img.shields.io/badge/React-19+-61DAFB.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

**English** | [简体中文](./README.md)

</div>

---

## 📖 Project Overview

This is an intelligent chatbot with web search capabilities featuring:

1. **Intelligent Chatbot** (based on React + Claude)
2. **Tavily Web Agent** (based on AgentRunner + Tavily)

Through a React + FastAPI + AgentRunner + Tavily architecture, it provides powerful web search, content extraction, and deep thinking capabilities.

## ✨ Features

### 🎯 Core Features
- **💬 Interactive Chat Interface**: React UI with sessions, streaming replies, and model selection
- **🔍 Real-time Web Search**: Search for latest information via Tavily
- **📄 Web Content Extraction**: Precise extraction of key content from web pages
- **🕷️ Deep Website Crawling**: Deep crawling of nested website links
- **🧠 Deep Thinking Mode**: Supports deep reasoning for complex queries
- **⚡ Fast Response Mode**: Quick answers for simple questions
- **💭 Conversation Memory**: Conversation history management through FastAPI and PostgreSQL
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
| **Frontend** | React + Vite | Modern TypeScript single-page application |
| **Backend** | FastAPI | High-performance async API framework |
| **Agent** | AgentRunner | Custom async agent runtime |
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

Before running tests for the first time, start the local PostgreSQL service:

```bash
docker compose up -d postgresql
```

Local defaults are: service `postgresql`, container `chatagent-postgresql`, database `chat_agents`, user `root`, password `Agent@Dev_1`, address `127.0.0.1:5432`, and volume `chatagent_postgres-data`. Environment variables may override these values. Encode the password as `Agent%40Dev_1` inside a database URL:

```text
postgresql+psycopg://root:Agent%40Dev_1@127.0.0.1:5432/chat_agents
```

The backend waits for the `migrate` service automatically. To initialize the schema separately, run:

```bash
docker compose run --rm migrate
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
uv run --project backend python -m uvicorn chat_agents.main:app --app-dir backend/src --reload

# Terminal 2: Start React frontend
npm --prefix frontend run dev
```

**Method B: Start the database and backend with Docker Compose**

```bash
docker compose up -d --build

# In another terminal, start the React frontend
npm --prefix frontend run dev
```

#### 5. Access the Application

- **Frontend**: http://localhost:5173
- **Docker backend API**: http://localhost:19180
- **Docker API docs**: http://localhost:19180/docs
- **When running the backend directly**: http://localhost:8080

## 📖 Usage Guide

### Basic Usage

1. **Configure API Keys**
   - Configure Claude, OpenAI, and Tavily API keys in `.env`
   - The frontend uses these settings through the backend API and never stores keys in the browser

2. **Start a Conversation**
   - Create or select a session in the React frontend
   - Send a question and receive the reply as a stream
   - Adjust the model and advanced options for each request

3. **Inspect Execution**
   - Use the trace panel to inspect model calls, tool calls, and timings
   - Tavily tools support search, page extraction, and deep crawling
   - The session list keeps previous conversations available

### Advanced Features

#### Tool Call Display

The agent automatically selects appropriate tools based on the question:

- **🔍 web_search**: Search relevant web pages
- **📄 web_reader**: Read web pages and PDF content

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

Backend configuration is defined in `backend/config/endpoints.yaml` and environment variables. The backend API provides the model catalog and advanced options used by the React controls. Set `VITE_BACKEND_ORIGIN` to override the backend origin used by the frontend dev proxy.

## 📁 Project Structure

```
intelligent-chatbot/
├── backend/
│   ├── src/chat_agents/        # FastAPI, AgentRunner, and domain modules
│   ├── tests/                  # Backend tests
│   ├── config/endpoints.yaml   # Endpoint configuration
│   ├── pyproject.toml          # Python project metadata
│   └── uv.lock                 # Locked dependencies
├── frontend/                   # React + Vite single-page application
│   ├── src/                    # Pages, components, and API client
│   └── public/                 # Static assets
├── docs/                       # Documentation and ADRs
├── deploy/                     # Nginx and release configuration
├── compose.yaml                # Local Docker Compose configuration
├── .env                       # Environment variables (local)
├── .env.sample                # Environment variable example
├── .gitignore                 # Git ignore file
├── scripts/                   # Development and release scripts
├── README.md                  # Project documentation (Chinese)
└── README_EN.md               # Project documentation (English)
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
1. 🔍 Call `web_search` (topic=news, time_range=month)
2. 📊 Display search results
3. 💬 Generate answer with citations

### Example Conversation 3: In-depth Research (Deep Thinking Mode)

**User**: Analyze the differences between popular Agent frameworks, and provide usage recommendations

**Agent**:
1. 🔍 Search relevant official documentation
2. 📄 Extract key page content
3. 🔍 Cross-check additional sources
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
uv run --project backend python -m uvicorn chat_agents.main:app --app-dir backend/src
```

### 2. API Key Error

**Issue**: `401 Unauthorized` or "API key validation failed"

**Solution**:
- Check API key format:
  - Claude: `sk-ant-api-...`
  - Tavily: `tvly-...`
- Confirm key is not expired and has sufficient quota
- Check the `.env` file and restart the backend if configuration changed

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
- Check backend logs or the container logs
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

- [FastAPI](https://fastapi.tiangolo.com/) - High-performance API framework
- [LangChain](https://www.langchain.com/) - LLM application framework
- [Anthropic Claude](https://www.anthropic.com/) - Powerful language model
- [Tavily](https://tavily.com/) - AI-optimized search API

---

<div align="center">

**⭐ If this project helps you, please give it a star!**

Made with ❤️ by Yuan

</div>
