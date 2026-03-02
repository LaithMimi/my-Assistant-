# AI CEO Startup Assistant

A fully functional AI Chief of Staff that lives in Telegram. Powered by **GPT-4o**, **LangGraph**, and the full **Google Workspace** ecosystem.

---

## Features

| Command | Action |
|---|---|
| `/start` | Connect Google account via OAuth |
| `/triage` | Fetch + classify unread emails by priority |
| `/brief` | Pre-meeting briefing for next calendar event |
| `/schedule` | Book a meeting (agent asks follow-up questions) |
| `/tasks` | View open Google Tasks |
| `/addtask` | Add a new task |
| `/research` | Search & summarise any topic (Tavily) |
| `/protect` | Block focus time on Google Calendar |
| `/remember` | Save a note/preference/decision to memory |
| `/recall` | Semantic search over your memory |
| Free text | Full ReAct agent — uses any tool needed |

---

## Tech Stack

- **Bot**: `python-telegram-bot` v21 + FastAPI webhook  
- **Agent**: LangGraph `StateGraph` + GPT-4o via OpenAI  
- **Memory**: Google Docs (write) + FAISS (vector search)  
- **Integrations**: Gmail, Google Calendar, Google Tasks  
- **Search**: Tavily API  
- **Tracing**: LangSmith  
- **Deploy**: Railway

---

## Setup

### 1. Clone & install

```bash
git clone <your-repo>
cd myAssistant
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 2. Create your `.env`

```bash
copy .env.example .env
```

Fill in all values:

| Variable | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| `TAVILY_API_KEY` | [tavily.com](https://tavily.com) |
| `GOOGLE_CLIENT_ID` | Google Cloud Console (see below) |
| `GOOGLE_CLIENT_SECRET` | Google Cloud Console (see below) |
| `GOOGLE_REDIRECT_URI` | `https://yourdomain.com/auth/callback` |
| `BASE_URL` | Your public domain (e.g. `https://my-app.up.railway.app`) | required |
| `WEBHOOK_URL` | Your public webhook URL (e.g. `https://my-app.up.railway.app/webhook`) | required |
| `LANGSMITH_API_KEY` | LangSmith API key for tracing / agent observability | optional |
| `SUPABASE_URL` | Supabase project URL for agent evaluation logging (`agent_logs` table) | optional |
| `SUPABASE_KEY` | Supabase anon or service-role key | optional |
| `STARTUP_CONTEXT_DOC_ID` | Optional Google Doc ID containing permanent background context. Fetched and indexed alongside memory. | optional |

### 3. Google Cloud Console Setup

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (e.g. `ceo-assistant`)
3. **Enable APIs** → search and enable each:
   - Gmail API
   - Google Calendar API
   - Google Tasks API
   - Google Docs API
   - Google Drive API
   - Google People API (for name lookup)
4. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Web application**
   - Authorised redirect URIs: `https://yourdomain.com/auth/callback`
   - Download and save `Client ID` + `Client Secret` → paste into `.env`
5. **OAuth consent screen** → set to External → add your email as a test user

---

### 4. Run locally

```bash
# If testing locally, use ngrok to get a public HTTPS URL
ngrok http 8000
# Copy the ngrok URL into BASE_URL, WEBHOOK_URL, GOOGLE_REDIRECT_URI in .env

uvicorn ceo_assistant.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` to verify all endpoints.

---

### 5. Deploy to Railway

1. Push your repo to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Set all environment variables in the Railway dashboard
4. Railway auto-detects `railway.json` and runs:
   ```
   uvicorn ceo_assistant.main:app --host 0.0.0.0 --port $PORT
   ```
5. Copy your Railway public URL → update `.env` variables:
   - `BASE_URL=https://your-app.railway.app`
   - `WEBHOOK_URL=https://your-app.railway.app/webhook`
   - `GOOGLE_REDIRECT_URI=https://your-app.railway.app/auth/callback`

---

## Project Structure

```
myAssistant/
├── ceo_assistant/
│   ├── main.py              ← FastAPI app + webhook + OAuth endpoints
│   ├── bot.py               ← Telegram command handlers
│   ├── agent.py             ← LangGraph StateGraph + ReAct loop
│   ├── memory.py            ← Google Docs loader + FAISS indexer
│   ├── google/
│   │   ├── auth.py          ← OAuth 2.0 flow + token management
│   │   └── client.py        ← Authenticated Google API clients
│   ├── prompts/
│   │   └── system.py        ← Dynamic system prompt with memory injection
│   ├── tools/
│   │   ├── gmail.py         ← gmail_triage, gmail_draft
│   │   ├── calendar.py      ← calendar_view, calendar_schedule, calendar_protect
│   │   ├── tasks.py         ← tasks_list, tasks_create, tasks_complete
│   │   ├── research.py      ← web_research (Tavily)
│   │   ├── memory_tools.py  ← memory_save, memory_search
│   │   └── meeting_brief.py ← meeting_brief
│   └── utils/
│       ├── formatter.py     ← Telegram HTML formatting helpers
│       └── splitter.py      ← Split long messages into ≤4096 char chunks
├── faiss_index/             ← Local FAISS indexes per chat_id (gitignored)
├── credentials/             ← OAuth tokens per chat_id (gitignored)
├── requirements.txt
├── railway.json
├── .env.example
└── README.md
```

---

## How the Agent Works

```
User message
    ↓
memory_node   ← FAISS search on user message → injects context into system prompt
    ↓
agent_node    ← GPT-4o with 12 tools bound
    ↓
(if tool call)
    ↓
tool_node     ← Executes Gmail / Calendar / Tasks / Tavily / Memory tool
    ↓
agent_node    ← Re-reasons with tool results
    ↓
Final response → Telegram (split if >4096 chars)
```

---

## Memory System

The assistant maintains a **Google Doc** called `"CEO Memory — {Your Name}"` with sections:

- `## Preferences` — e.g. "Prefers async communication"
- `## Decisions` — e.g. "Decided to delay Series A to Q4"
- `## Stakeholders` — e.g. "Investor John: responds best to concise emails"
- `## Notes & Learnings` — general notes

After every `/remember` call (or `memory_save` tool use), a new timestamped entry is appended and the local FAISS index is rebuilt automatically.

---

## BotFather Setup

After creating your bot with `/newbot`, set the command list:

```
start - Connect Google account and get started
triage - Classify unread emails by priority
brief - Pre-meeting briefing for next event
schedule - Book a meeting
tasks - View open tasks
addtask - Add a new task
research - Search and summarize a topic
protect - Block focus time on calendar
remember - Save a note or preference to memory
recall - Search your memory
```

---

## License

MIT
