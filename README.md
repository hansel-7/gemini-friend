# 🤖 Personal Assistant Telegram Bot

> A secure, AI-powered personal assistant that lives in your Telegram. Features an autonomous agent brain with persistent memory, adaptive scheduling, and proactive research capabilities. Powered by Gemini CLI with MCP integrations.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔒 **Secure** | Only responds to authorized user IDs |
| 🤖 **AI-Powered** | Connects to Gemini CLI for intelligent responses |
| 📷 **Vision** | Analyze images sent via Telegram |
| 📁 **File Access** | Manages files in designated directories via MCP |
| 🌐 **Web Browsing** | Controls browsers via Playwright MCP (screenshots sent to Telegram on request) |
| ☁️ **Cloud Storage** | Accesses Google Drive via MCP |
| 📅 **Calendar & Email** | Google Calendar and Gmail integration |
| ✅ **Task Management** | Checklist with automatic reminders |
| ⏰ **Cron Jobs** | Dynamic scheduled jobs via natural language or cron expressions |
| 🧠 **Autonomous Agent** | Goal-driven brain with persistent backlog, adaptive scheduling (30min–4h), two-phase triage→work cycles, and self-improving prompt memory |
| 📰 **News Digest** | Daily gaming industry news summaries |
| 🕷️ **Web Scraping** | Scrape any URL with anti-bot bypass, powered by [Scrapling](https://github.com/D4Vinci/Scrapling) |
| 💰 **Expense Tracking** | Auto-detect credit card transactions via Gmail + manual input |
| 🏋️ **Exercise Tracker** | Conversational workout logger — tracks areas, exercises, sets, reps & weights to JSON |
| 🎤 **Voice Messages** | Voice-to-text via Groq Whisper — works with all features |
| 💡 **Capabilities Manifest** | Bot self-awareness — proactively suggests relevant features |
| 🔌 **Modular Automations** | Easy to add/remove features |

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Node.js 20+ (for Gemini CLI)
- Gemini CLI authenticated (`npx @google/gemini-cli` and follow setup)

### Installation

1. Install Python dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

2. Install Node.js dependencies (Gemini CLI):
   ```powershell
   npm install
   ```

3. Install Playwright browser (for web browsing features):
   ```powershell
   npx playwright install chromium
   ```

4. Run the bot:
   ```powershell
   python src/main.py
   ```

### Configuration

1. Copy the example files:
   ```powershell
   cp .env.example .env
   cp config/gemini_settings.example.json config/gemini_settings.json
   ```

2. Edit `.env` to customize:
   - `TELEGRAM_BOT_TOKEN` - Your bot token from @BotFather
   - `ALLOWED_USER_IDS` - Comma-separated list of authorized Telegram user IDs
   - `GEMINI_TIMEOUT` - Timeout for Gemini CLI responses (default: 300s)

### MCP Servers

Edit `config/gemini_settings.json` to configure MCP servers:
- **filesystem** - Read/write files in your chosen directory
- **playwright** - Control web browsers
  > **Note:** Requires `@google/gemini-cli` v0.29.5+ (included in `package.json`).

> **Note:** Google Workspace (Calendar, Gmail, Drive) integration is built into Gemini CLI - no additional MCP server needed.

### Capabilities Manifest

Edit `config/capabilities.json` to teach the bot about its own features. Each capability has:
- **triggers** — contextual cues for when to suggest the feature
- **examples** — sample suggestions the AI can use

This allows the bot to proactively suggest actions (e.g., *"Want me to set a reminder for that?"*) instead of waiting for explicit commands.

## Usage

### General Commands
- `/start` - Welcome message
- `/help` - Show available commands
- `/status` - Check Gemini CLI status
- `/security` - View security configuration
- `/persona` - Reload persona configuration
- Any text - Chat with Gemini CLI

### Task Commands
- `/task <description>` - Add a new task
- `/task Buy groceries due:tomorrow` - Add task with due date
- `/tasks` - List all pending tasks
- `/done <id>` - Mark a task as complete
- `/deltask <id>` - Delete a task
- `/cleartasks` - Remove completed tasks

### Cron Commands
- `/cron` - Show cron help
- `/cron list` - List all scheduled jobs
- `/cron add "<cron>" <prompt>` - Add job with explicit cron expression
- `/cron delete <id>` - Delete a scheduled job
- `/cron pause <id>` - Pause a job
- `/cron resume <id>` - Resume a paused job
- Natural language: "Every Monday at 9am, review my deal pipeline" auto-creates a job

### News Commands
- `/news` - Manually trigger the daily digest

### Web Scraping Commands
- `/scrape <url>` - Scrape a page and get an AI summary
- `/scrape <url> <question>` - Scrape a page and ask a specific question about it
- Tries fast HTTP first, falls back to stealth browser for anti-bot protected sites

### Expense Commands
- `/expense <amount> <description>` - Add a manual expense (e.g., `/expense 250k coffee`)
- `/expense` - Show today's expenses
- `/expenses` - Monthly spending summary
- `/expenses week` - Weekly spending summary
- `/describe <id> <text>` - Add description to an auto-detected transaction
- `/delexpense <id>` - Delete an expense
- Credit card transactions from UOB are auto-detected hourly via Gmail scanning

### Exercise Commands
- `/exercise` - Start a workout session
- `/next` - Finish current exercise, start next one (shows summary)
- `/finish` - End workout and save to JSON
- `/workouts` - View recent workout history
- During a session, text messages bypass Gemini and go directly to the exercise handler

### Context Commands
- `/context` - Check context window usage
- `/summarize` - Summarize conversation history
- `/clear` - Clear conversation history
- `/clearall` - Clear history AND summary

## Automations

Automations are modular features that can be enabled/disabled in `config/automations.json`:

```json
{
  "tasks": {
    "enabled": true,
    "reminder_check_interval": 60
  },
  "brain": {
    "enabled": true,
    "min_cycle_minutes": 30,
    "max_cycle_minutes": 240,
    "quiet_hours_start": 23.5,
    "quiet_hours_end": 7
  },
  "cron": {
    "enabled": true,
    "check_interval_seconds": 60,
    "quiet_hours_start": 23.5,
    "quiet_hours_end": 7
  },
  "expenses": {
    "enabled": true,
    "scan_interval_minutes": 60,
    "alert_sender_email": "unialerts@uobgroup.com"
  },
  "exercise": {
    "enabled": true,
    "data_file": "workouts.json"
  }
}
```

### Available Automations
- **tasks** - Task/checklist management with reminders
- **brain** - Autonomous AI agent with persistent backlog, adaptive scheduling, and event-driven triggers
- **cron** - Dynamic scheduled jobs (natural language or cron expressions, fires via Gemini CLI with MCP)
- **news** - Daily gaming news digest with AI summarization
- **expenses** - Expense tracking with auto Gmail scanning for credit card alerts
- **exercise** - Workout/exercise tracker with conversational set logging

### Autonomous Agent (Brain v3)

The brain automation is an autonomous goal-driven agent that:
- **Triage phase** — Reviews its backlog, user tasks, observations, and conversation history to decide what to work on
- **Work phase** — Executes one step of research/analysis using MCP tools, saves notes, and reports findings
- **Event-driven** — User messages are recorded as observations and bump the next cycle
- **Task-aware** — Reads pending tasks from `/task` and proactively helps with deadlines
- **Adaptive scheduling** — 30min cycles when busy, 4h when idle (configurable)
- **Persistent state** — Backlog, observations, and cycle info saved to `agent_state.json`
- **Self-improving memory** — Agent accumulates lessons from work cycles into `agent_learnings.json`, injected into future prompts. Auto-consolidates when >15 lessons via Gemini
- **Safety guardrails** — Cannot modify its own codebase, only create standalone scripts

### Adding New Automations
1. Create folder: `src/automations/my_feature/`
2. Implement class extending `BaseAutomation`
3. Add to `config/automations.json`
4. Restart bot

## 🐧 Deploying on Ubuntu Server (Headless)

### Initial Setup

```bash
# Install dependencies
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl

# Install Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Install Gemini CLI globally
sudo npm install -g @google/gemini-cli

# Clone and set up the bot
git clone https://github.com/hansel-7/gemini-friend.git personal_assistant
cd personal_assistant
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install Playwright system dependencies
playwright install chromium
playwright install-deps

# Configure environment
cp .env.example .env
nano .env  # Set GEMINI_CLI_COMMAND=gemini, DATA_DIR, etc.
```

### Google Workspace Extension (Headless Auth)

On a headless server, the Google Workspace extension can't open a browser for OAuth. Use the **headless login script** instead:

```bash
# Clone the extension source (includes headless login tool)
cd ~
git clone https://github.com/gemini-cli-extensions/workspace.git workspace-src
cd workspace-src
npm install

# Run headless auth
cd workspace-server
node dist/headless-login.js
```

This prints a **Google OAuth URL**. Open it in any browser (laptop, phone), sign in, and the browser shows a JSON block. Paste that JSON back into the terminal.

Then copy credentials to the installed extension:

```bash
cp ~/workspace-src/gemini-cli-workspace-token.json ~/.gemini/extensions/google-workspace/
```

> **Note:** If the extension isn't installed yet, run `gemini` once first, then install it with:
> `gemini extensions install https://github.com/gemini-cli-extensions/workspace`

### Running as a systemd Service (24/7)

1. Create the service file:
   ```bash
   sudo nano /etc/systemd/system/personal-assistant.service
   ```

   ```ini
   [Unit]
   Description=Personal Assistant Telegram Bot
   After=network-online.target
   Wants=network-online.target

   [Service]
   Type=simple
   User=<your-username>
   WorkingDirectory=/home/<your-username>/personal_assistant
   ExecStart=/home/<your-username>/personal_assistant/venv/bin/python3 src/main.py
   Restart=always
   RestartSec=10
   Environment=PATH=/usr/local/bin:/usr/bin:/home/<your-username>/.npm-global/bin

   [Install]
   WantedBy=multi-user.target
   ```

2. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable personal-assistant
   sudo systemctl start personal-assistant
   ```

3. Useful commands:
   ```bash
   sudo systemctl status personal-assistant       # Check status
   sudo journalctl -u personal-assistant -f        # Stream live logs
   sudo systemctl restart personal-assistant       # Restart after code updates
   ```

4. Update workflow:
   ```bash
   cd ~/personal_assistant && git pull
   sudo systemctl restart personal-assistant
   ```

## Security

- All handlers use the `@authorized_only` decorator
- Unauthorized users are silently rejected
- MCP servers restricted via `--allowed-mcp-server-names`
- Filesystem access limited to `D:\Gemini CLI`
- All access attempts logged to `logs/security.log`

## 🏗️ Project Structure

```
personal_assistant/
├── .env                    # Your credentials (git-ignored)
├── .env.example            # Template for .env
├── requirements.txt        # Python dependencies
├── package.json            # Node.js dependencies (Gemini CLI)
├── config/
│   ├── settings.py         # Configuration loader
│   ├── automations.json    # Automation settings
│   ├── capabilities.json   # Bot capabilities manifest
│   └── gemini_settings.json # MCP server config
└── src/
    ├── main.py             # Entry point
    ├── bot/
    │   ├── handlers.py     # Telegram handlers
    │   └── security.py     # Authorization
    ├── gemini/
    │   └── cli_wrapper.py  # Gemini CLI integration
    ├── automations/        # Modular automations
    │   ├── base.py         # Base automation class
    │   ├── tasks/          # Task management
    │   │   ├── manager.py  # Task CRUD
    │   │   ├── scheduler.py # Reminders
    │   │   └── handlers.py # Commands
    │   ├── cron/           # Dynamic scheduled jobs
    │   │   ├── manager.py  # Job CRUD + JSON persistence
    │   │   ├── scheduler.py # Background job runner
    │   │   └── handlers.py # /cron commands + NL detection
    │   ├── news/           # News scraper & summarizer
    │   │   ├── scraper.py
    │   │   ├── scheduler.py
    │   │   └── summarizer.py
    │   ├── expenses/        # Expense tracking
    │   │   ├── manager.py   # Expense CRUD + JSON storage
    │   │   ├── scanner.py   # Gmail scanner for CC alerts
    │   │   └── handlers.py  # Commands + automation class
    │   ├── exercise/        # Workout tracker
    │   │   ├── manager.py   # Workout JSON persistence
    │   │   └── handlers.py  # Session state + commands
    │   └── brain/           # Autonomous AI Agent
    │       ├── agent_state.py # Persistent state (backlog, observations)
    │       ├── learnings.py  # Self-improving prompt memory
    │       ├── thinker.py   # Two-phase triage + work prompts
    │       ├── scheduler.py # Adaptive scheduling (30min–4h)
    │       └── handlers.py  # Event triggers + TaskManager integration
    ├── scraper.py           # Web scraping (Scrapling)
    └── utils/
        ├── logger.py        # Logging
        └── conversation.py  # Context management
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Gemini CLI](https://github.com/google/gemini-cli) - The AI backbone powering this bot
- [python-telegram-bot](https://python-telegram-bot.org/) - Telegram Bot API wrapper
- [Scrapling](https://github.com/D4Vinci/Scrapling) - Adaptive web scraping framework with anti-bot bypass
- [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) - For tool integrations
- [Groq](https://groq.com/) - Lightning-fast Whisper voice transcription

