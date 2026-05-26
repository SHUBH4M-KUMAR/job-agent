"""
Uses a local Ollama model to score how well a job matches the user's profile.
Returns a score (0–100) and a short reasoning string.
"""

import json
import re
import ollama
from config import OLLAMA_MODEL, MIN_SALARY_LPA
from user_profile import USER_PROFILE


SCORE_PROMPT = """You are a job-fit evaluator. Given a candidate profile and a job description, return a JSON object with:
- "score": integer 0-100 (how well the candidate fits this specific job)
- "reason": one sentence explaining the score
- "salary_ok": true/false (is the salary >= {min_lpa} LPA, or unknown/unspecified — treat unknown as true)
- "location_ok": true/false (is the job in India or Remote)
- "apply": true/false (should we apply? true if score >= 65 AND salary_ok AND location_ok)

Candidate profile:
{profile}

Job description:
{jd}

Respond ONLY with valid JSON. No markdown, no explanation outside the JSON."""


def score_job(title: str, company: str, description: str, location: str = "", salary_text: str = "") -> dict:
    profile_text = (
        f"Name: {USER_PROFILE['name']}\n"
        f"Summary: {USER_PROFILE['summary']}\n"
        f"Skills: {', '.join(USER_PROFILE['skills'])}\n"
        f"Experience: {USER_PROFILE['total_experience_years']} years\n"
        f"Target roles: {', '.join(USER_PROFILE['target_roles'])}\n"
        f"Open to: {', '.join(USER_PROFILE['open_to'])}\n"
        f"Min salary: {USER_PROFILE['min_salary_lpa']} LPA\n"
    )

    jd_text = (
        f"Title: {title}\n"
        f"Company: {company}\n"
        f"Location: {location}\n"
        f"Salary: {salary_text or 'Not specified'}\n\n"
        f"Description:\n{description[:4000]}"
    )

    prompt = SCORE_PROMPT.format(
        min_lpa=MIN_SALARY_LPA,
        profile=profile_text,
        jd=jd_text,
    )

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0},
        )
        raw = response["message"]["content"].strip()
        # Strip accidental markdown fences or <think> blocks (qwen3 thinking mode)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        return {"score": 0, "reason": f"Scorer error: {e}", "salary_ok": True, "location_ok": True, "apply": False}


def generate_cover_letter(title: str, company: str, description: str) -> str:
    prompt = (
        f"Write a concise, professional cover letter (max 150 words) for {USER_PROFILE['name']} "
        f"applying for the role of '{title}' at '{company}'.\n\n"
        f"Candidate summary: {USER_PROFILE['summary']}\n"
        f"Key skills: {', '.join(USER_PROFILE['skills'][:15])}\n\n"
        f"Job description excerpt:\n{description[:2000]}\n\n"
        "Make it specific to the role. Do not include placeholders. Return only the letter text."
    )
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.7},
        )
        raw = response["message"]["content"].strip()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        return raw
    except Exception:
        return USER_PROFILE["form_answers"]["cover_letter_default"]
