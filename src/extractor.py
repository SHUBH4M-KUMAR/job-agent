"""
Finds and extracts text from the first PDF in the resume/ folder.
"""

from pathlib import Path
import pdfplumber
from config import RESUME_DIR


def get_resume_path() -> Path | None:
    pdfs = list(RESUME_DIR.glob("*.pdf"))
    return pdfs[0] if pdfs else None


def extract_resume_text() -> str:
    path = get_resume_path()
    if not path:
        return ""
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n".join(text_parts)
