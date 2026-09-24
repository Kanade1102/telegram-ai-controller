# Telegram AI Controller

A powerful, secure, and privacy-respecting local controller for both **Browser-based AI sessions** (ChatGPT, Gemini, Claude, DeepSeek) and **Direct API sessions** (OpenAI, Gemini API, OpenRouter, 9Router, Anthropic, DeepSeek, and custom OpenAI-compatible endpoints) controllable via Telegram.

Everything runs locally on your machine. No SaaS middlemen, no cloud databases, no remote command servers.

---

## 🌟 Key Architecture & Capabilities

```
                       Telegram Bot
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
  Browser Session Manager              API Manager
            │                               │
  ┌─────────┼─────────┐                     ├── OpenAI
  │         │         │                     ├── Google Gemini API
ChatGPT  Gemini    Claude                   ├── OpenRouter
  Web      Web      Web                     ├── 9Router
  │         │         │                     ├── Anthropic Claude
DeepSeek Web  (Active User Chrome)          ├── DeepSeek API
                                            └── Generic OpenAI-Compatible
                                                (LM Studio, vLLM, LiteLLM)
```

### 1. Two Distinct Modes: Account Mode vs API Mode
- **ChatGPT Web (`chatgpt_web`)**: Automates your already logged-in session on [chatgpt.com](https://chatgpt.com) using your persistent Chrome/Chromium profile.
- **OpenAI API (`openai`)**: Uses standard OpenAI API keys and models (`gpt-4o`, etc.) independently.
- **Gemini Web (`gemini_web`)**: Automates your existing Google account session on [gemini.google.com](https://gemini.google.com).
- **Gemini API (`gemini_api`)**: Uses official Google Gemini API keys directly via REST/SSE streaming.

### 2. Privacy & Security First
- **DENY-BY-DEFAULT Access Control**: Only Telegram user IDs listed in `TELEGRAM_ALLOWED_USERS` can execute commands or receive output. Unauthorized users are blocked immediately.
- **Zero Password Sharing**: NEVER send Google or OpenAI passwords via Telegram. Login is done safely and directly in your browser.
- **Browser-Native Screenshots**: Uses `page.screenshot(...)` to capture only the active AI tab rather than your full desktop.
- **Wayland & X11 Desktop Fallback**: If full window capture is requested, automatically detects Wayland (`grim`) and X11 (`gnome-screenshot`, `scrot`, `import`, or Pillow).
- **Secret Masking**: API keys are always masked in logs (`sk-12...cdef`). API keys cannot be set via Telegram commands to prevent leaking credentials in chat logs.
- **Local Management Only**: Embedded web manager listens strictly on `127.0.0.1:8765`.

---

## 📋 Requirements

- **Linux** (Debian/Ubuntu, Arch, Fedora, openSUSE, etc.)
- **Python 3.11+** (Tested on Python 3.11, 3.12, 3.13, 3.14)
- **Chromium / Google Chrome**
- **Wayland or X11** display server

---

## 🚀 Quick Start Guide

### 1. Create a Telegram Bot
1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow instructions to name your bot.
3. Copy the **HTTP API Token** provided by BotFather.
4. Get your Telegram numeric user ID using [@userinfobot](https://t.me/userinfobot) or [@raw_data_bot](https://t.me/raw_data_bot).

### 2. Clone and Setup Environment

```bash
cd ~/telegram-ai-controller

# Create Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` with your preferred editor:
```ini
# Required: Telegram Token & Allowed Users (Comma-separated user IDs)
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_ALLOWED_USERS=123456789

# Browser Remote Debugging Port (localhost only!)
BROWSER_CDP_URL=http://127.0.0.1:9222

# Mode and Default Provider
DEFAULT_MODE=browser
DEFAULT_PROVIDER=chatgpt_web

# Screenshots
SCREENSHOT_MODE=browser
SCREENSHOT_DIR=./screenshots

# API Providers (configure any you wish to use)
OPENAI_API_KEY=
GEMINI_API_KEY=
OPENROUTER_API_KEY=
ROUTER9_API_KEY=
ANTHROPIC_API_KEY=
DEEPSEEK_API_KEY=
```

---

## 🌐 Launching Chromium with Remote Debugging (CDP)

To allow the controller to manage your browser AI sessions safely without creating disposable or temporary guest sessions, launch Chromium/Chrome with remote debugging bound **strictly to localhost**:

### Option A: Using your Default Profile (Recommended)
Close all existing Chrome/Chromium windows and restart with:
```bash
chromium --remote-debugging-port=9222
```
or for Google Chrome:
```bash
google-chrome-stable --remote-debugging-port=9222
```

### Option B: Using a Dedicated AI Controller Profile
If you want to keep your main browser separate, create a dedicated profile directory:
```bash
chromium --remote-debugging-port=9222 --user-data-dir="$HOME/.config/chromium-ai-controller"
```

> [!IMPORTANT]
> Never pass `--remote-debugging-address=0.0.0.0`. Remote debugging should **always** remain bound strictly to `127.0.0.1` (localhost).

---

## 🤖 Starting the Controller

Run the main process:
```bash
source .venv/bin/activate
python main.py
```

You will see the startup self-test output:
```text
2026-09-24 10:36:07 [INFO] Running provider self-test...
2026-09-24 10:36:07 [INFO] Telegram access control configured for 1 authorized user(s).
2026-09-24 10:36:08 [INFO] Browser CDP connection established.
2026-09-24 10:36:08 [INFO] Local management web interface started on http://127.0.0.1:8765
2026-09-24 10:36:08 [INFO] Telegram Bot started and polling for authorized commands.
```

---

## 📱 Telegram Commands Reference

### General
| Command | Description |
|---|---|
| `/start` | Check bot status and active backend |
| `/help` | Complete categorized guide of all commands |
| `/status` | View connection, mode, active provider, model, and task state |
| `/health` | Live latency & availability ping of all configured providers |
| `/usage` | View token usage, request counts, and costs |

### Browser Automation
| Command | Description |
|---|---|
| `/sessions` | List open AI tabs in Chromium (ChatGPT, Gemini, Claude, DeepSeek) |
| `/use <id\|name>` | Select active AI tab (e.g. `/use 1` or `/use chatgpt`) |
| `/login chatgpt` | Opens ChatGPT in Chromium for manual login, then verifies readiness |
| `/login gemini` | Opens Gemini in Chromium for manual Google sign-in, then verifies readiness |

### Direct API & Conversations
| Command | Description |
|---|---|
| `/conversations` | List saved API conversation threads |
| `/newchat <name>` | Create a new API conversation thread (e.g. `/newchat Debugging ROM`) |
| `/usechat <id>` | Switch to conversation thread by ID |
| `/renamechat <id> <name>` | Rename an existing conversation |
| `/deletechat <id>` | Delete a conversation thread and its message history |

### Providers, Modes & Models
| Command | Description |
|---|---|
| `/providers` | Show all available browser and API backends with live availability |
| `/mode [browser\|api\|auto]` | Switch mode between browser automation, API, or auto-fallback |
| `/api` | Shortcut for `/mode api` |
| `/web` | Shortcut for `/mode browser` |
| `/provider <name>` | Set active provider (`chatgpt_web`, `gemini_web`, `openai`, `openrouter`, `9router`, etc.) |
| `/models [provider] [refresh]` | Query available models from the provider |
| `/model <model-id\|alias>` | Set model for active provider; `/model <provider>/<model-id>` sets both (e.g. `/model openrouter/meta-llama/...`) |

### Prompts, Progress & Control
| Command | Description |
|---|---|
| `/prompt <text>` (or `/promt`) | Send prompt preserving newlines, Unicode, Vietnamese, code blocks, and quotes |
| `/progress` | Browser screenshot + DOM status OR API elapsed time + received characters + tokens |
| `/last` | Show the latest response from the active AI session |
| `/stop` | Click browser "Stop generating" button or cancel active API stream |
| `/watch [seconds]` | Automatically send progress updates while generating (minimum 10s) |
| `/unwatch` | Stop automatic progress updates |

### Routing & Fallback
| Command | Description |
|---|---|
| `/fallback <chain>` | Set active fallback chain (e.g. `/fallback coding`) |
| `/fallback off` | Disable automatic provider fallback |

---

## ⚙️ Adding Custom OpenAI-Compatible Providers

You can add any OpenAI-compatible API (such as LM Studio, vLLM, LiteLLM, Ollama, or third-party routers) without modifying any Python code.

Edit `config/providers.yaml`:
```yaml
fallback_chains:
  coding:
    - openai
    - openrouter
    - 9router
  browser:
    - chatgpt_web
    - gemini_web
  general:
    - gemini_api
    - openrouter

aliases:
  coding:
    provider: openrouter
    model: meta-llama/llama-3.3-70b-instruct
  fast:
    provider: gemini_api
    model: gemini-1.5-flash

providers:
  local_lmstudio:
    type: openai_compatible
    base_url: http://127.0.0.1:1234/v1
    api_key_env: LOCAL_LMSTUDIO_API_KEY
    default_model: qwen-2.5-coder-32b
    timeout: 60.0
```

When you start the controller, `local_lmstudio` will automatically appear in `/providers`!

---

## 🖥️ Local Management Dashboard

When the controller is running, access the local management dashboard from your browser:
```
http://127.0.0.1:8765
```
It shows real-time status of:
- Active controller mode and selected provider
- Browser CDP connection
- Browser sessions & API provider statuses
- Configured fallback chains & models

---

## 🔒 Security & Privacy Notes

1. **Deny-By-Default**: If `TELEGRAM_ALLOWED_USERS` is empty, no one can interact with the bot.
2. **Localhost Only**: Browser CDP and the Web UI bind strictly to `127.0.0.1`.
3. **No Credential Phishing**: The bot will never ask for your Google or OpenAI password. All browser authentications take place inside your local browser.
4. **No Clipboard Tampering**: Prompts are inserted using Playwright DOM inputs (`fill` and `insert_text`), preserving your system clipboard.

---

## 🐧 Optional Systemd User Service

To automatically start the Telegram AI Controller when your user logs in:

1. Create the systemd user service directory:
   ```bash
   mkdir -p ~/.config/systemd/user
   ```

2. Copy the service unit:
   ```bash
   cp systemd/telegram-ai-controller.service ~/.config/systemd/user/
   ```

3. Enable and start the service:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable telegram-ai-controller
   systemctl --user start telegram-ai-controller
   ```

4. Check service status and logs:
   ```bash
   systemctl --user status telegram-ai-controller
   journalctl --user -u telegram-ai-controller -f
   ```

---

## 🧪 Running Tests

The test suite covers security, command parsing, multiline preservation, fallback routing, database operations, and browser adapters:

```bash
source .venv/bin/activate
pytest -v tests/
```
