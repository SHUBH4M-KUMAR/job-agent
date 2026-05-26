# Job Application Bot

A local, privacy-first job application agent that searches LinkedIn, Naukri, and Wellfound, scores each listing using a local Ollama model, and auto-applies on your behalf — no cloud APIs, no data leaving your machine.

## How it works

1. Searches configured platforms using your target role queries
2. Scores each job (0–100) using a local LLM via Ollama based on your profile
3. Auto-applies to jobs above your score threshold via browser automation (Playwright)
4. Tracks every application and skip in a local SQLite database

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running locally with your chosen model pulled
- Chromium installed (`/usr/bin/chromium` or set `CHROMIUM_BIN` in `.env`)
- A LinkedIn, Naukri, and/or Wellfound account

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/your-username/job-agent
cd job-agent

# 2. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 3. Pull your Ollama model
ollama pull qwen3:8b

# 4. Configure your profile
cp .env.example .env          # edit salary thresholds, model, etc.
# Edit user_profile.py        # fill in your name, skills, experience, etc.

# 5. Drop your resume PDF into the resume/ folder
```

## Login (first time only)

```bash
# Sign into Google once — all platforms reuse this session
python main.py login-google

# Then log into each platform (one browser session)
python main.py login all
# or individually:
python main.py login linkedin
python main.py login naukri
python main.py login wellfound
```

## Usage

```bash
# Preview what would be applied to (no actual applications)
python main.py dry-run

# Run the full pipeline
python main.py run

# Limit to one platform
python main.py run -p linkedin

# Check application history
python main.py status

# Check session state
python main.py session-status

# Clear a saved session
python main.py clear-session linkedin
```

## Configuration

| File | What to edit |
|---|---|
| `user_profile.py` | Your name, contact info, skills, experience, target roles |
| `config.py` | Search queries, salary filters, blacklisted companies |
| `.env` | Ollama model, score threshold, Chromium path, headless mode |

## Notes

- Press `s + Enter` during a run to skip the current application
- The bot uses `--disable-blink-features=AutomationControlled` to reduce detection
- Sessions are stored in `cookies/` — never commit this folder
- All data stays local: SQLite DB in `data/`, logs in `logs/`

## Supported platforms

| Platform | Search | Apply |
|---|---|---|
| LinkedIn | ✅ | ✅ Easy Apply |
| Naukri | ✅ | ✅ |
| Wellfound | ✅ | ✅ |

## License

MIT
