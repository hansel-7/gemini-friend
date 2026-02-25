# 🤖 Personal Assistant Telegram Bot

> A secure, AI-powered personal assistant that lives in your Telegram. Powered by Gemini CLI with MCP integrations for file management, web browsing, and Google Workspace.

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
| 🧠 **AI Brain** | Proactive engagement and idea generation |
| 📰 **News Digest** | Daily gaming industry news summaries |
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
  "news": {
    "enabled": true,
    "digest_hour": 7,
    "digest_minute": 0
  },
  "cron": {
    "enabled": true,
    "check_interval_seconds": 60,
    "quiet_hours_start": 23.5,
    "quiet_hours_end": 7
  }
}
```

### Available Automations
- **tasks** - Task/checklist management with reminders
- **cron** - Dynamic scheduled jobs (natural language or cron expressions, fires via Gemini CLI with MCP)
- **news** - Daily gaming news digest with AI summarization
- **brain** - Proactive AI engagement

### Adding New Automations
1. Create folder: `src/automations/my_feature/`
2. Implement class extending `BaseAutomation`
3. Add to `config/automations.json`
4. Restart bot

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
    │   └── brain/          # AI Brain (proactive engagement)
    │       ├── thinker.py  # Thought generation
    │       └── scheduler.py # Scheduling logic
    └── utils/
        ├── logger.py       # Logging
        └── conversation.py # Context management
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Gemini CLI](https://github.com/google/gemini-cli) - The AI backbone powering this bot
- [python-telegram-bot](https://python-telegram-bot.org/) - Telegram Bot API wrapper
- [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) - For tool integrations

