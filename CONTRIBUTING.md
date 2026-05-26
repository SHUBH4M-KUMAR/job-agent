# Contributing to job-agent

Thanks for your interest. Contributions are welcome — bug fixes, new platform support, better apply logic, or anything that makes the bot more reliable.

## Setup

```bash
git clone https://github.com/SHUBH4M-KUMAR/job-agent
cd job-agent
pip install -r requirements.txt
playwright install chromium
ollama pull qwen3:8b
```

Fill in `user_profile.py` and `.env` (copy from `.env.example`), drop your resume PDF in `resume/`, then:

```bash
python main.py login-google
python main.py login all
python main.py dry-run
```

## How to contribute

1. Fork the repo and create a branch: `git checkout -b your-feature`
2. Make your changes
3. Test with `dry-run` before submitting
4. Open a PR with a short description of what you changed and why

## Good first issues

- Add Glassdoor platform support (see `src/platforms/` for how existing ones work)
- Better form-fill logic for edge cases (dropdowns, radio buttons, custom fields)
- Windows / macOS Chromium path detection
- Resume text extraction improvements
- CAPTCHA detection and pause-for-human handling
- CLI flag to set a custom score threshold at runtime

## Project structure

```
main.py                  # CLI entry point
config.py                # Search queries, filters, settings
user_profile.py          # Your profile (not committed)
src/
  runner.py              # Orchestrates search → score → apply
  scorer.py              # Ollama-based job fit scoring
  tracker.py             # SQLite application history
  cookie_manager.py      # Browser session persistence
  extractor.py           # Resume PDF text extraction
  skip_controller.py     # Handles 's + Enter' mid-run skip
  platforms/
    base.py              # Base class all platforms extend
    linkedin.py
    naukri.py
    wellfound.py
```

## Adding a new platform

1. Create `src/platforms/yourplatform.py` extending `BasePlatform`
2. Implement `search(page, query) -> list[JobListing]` and `apply(page, job, resume_path) -> tuple[bool, str]`
3. Add it to `PLATFORM_MAP` in `src/runner.py` and `PLATFORMS` in `config.py`

## Guidelines

- Keep PRs focused — one thing per PR
- No personal data in commits (cookies, DB, resume, `.env`)
- Test with `dry-run` first
- If you're unsure, open an issue before writing code
