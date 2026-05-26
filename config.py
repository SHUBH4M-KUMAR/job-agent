import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
RESUME_DIR = BASE_DIR / "resume"
DATA_DIR = BASE_DIR / "data"
COOKIES_DIR = BASE_DIR / "cookies"
LOGS_DIR = BASE_DIR / "logs"

for d in [DATA_DIR, COOKIES_DIR, LOGS_DIR, RESUME_DIR]:
    d.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "applications.db"

# Local Ollama model to use for scoring and cover letter generation
# Run: ollama pull qwen3:8b  (or any model you prefer)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

# Search queries sent to each platform
JOB_SEARCH_QUERIES = [
    "machine learning engineer",
    "ML engineer",
    "AI engineer",
    "LLM engineer",
    "deep learning engineer",
    "AI developer",
    "applied AI engineer",
]

LOCATION_FILTERS = ["India", "Remote"]

# Salary filters (in LPA)
MIN_SALARY_LPA = float(os.getenv("MIN_SALARY_LPA", "8.0"))
PREFERRED_SALARY_LPA = float(os.getenv("PREFERRED_SALARY_LPA", "12.0"))
LAST_SALARY_LPA = float(os.getenv("LAST_SALARY_LPA", "0.0"))

# Minimum Ollama fit score (0–100) required to auto-apply
JOB_FIT_THRESHOLD = int(os.getenv("JOB_FIT_THRESHOLD", "65"))

# Companies to never apply to
BLACKLISTED_COMPANIES: list[str] = [
    # "ExCompany Inc.",
]

PLATFORMS = ["linkedin", "naukri", "wellfound"]

# Path to Chromium binary — override via env var if needed
CHROMIUM_BIN = os.getenv("CHROMIUM_BIN", "/usr/bin/chromium")

# Playwright settings
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
SLOW_MO_MS = int(os.getenv("SLOW_MO_MS", "120"))
PAGE_TIMEOUT_MS = 30_000
