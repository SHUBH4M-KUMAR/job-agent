"""
Base class all platform scrapers inherit from.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from playwright.async_api import Page


@dataclass
class JobListing:
    job_id: str
    platform: str
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    salary: str = ""
    easy_apply: bool = False   # True = platform-native apply, False = external portal


class BasePlatform(ABC):
    name: str = ""

    @abstractmethod
    async def search(self, page: Page, query: str) -> list[JobListing]:
        """Scrape job listings for a query. Returns list of JobListing."""

    @abstractmethod
    async def apply(self, page: Page, job: JobListing, resume_path: str) -> tuple[bool, str]:
        """
        Attempt to apply.
        Returns (True, "") on success or (False, "reason") on failure.
        Should pause and prompt user if CAPTCHA is detected.
        """

    # ── shared helpers ────────────────────────────────────────────────────────

    async def _safe_fill(self, page: Page, selector: str, value: str):
        """Fill a field if it exists, silently skip if not found."""
        try:
            el = page.locator(selector).first
            if await el.count() > 0:
                await el.clear()
                await el.fill(value)
        except Exception:
            pass

    async def _safe_click(self, page: Page, selector: str):
        try:
            el = page.locator(selector).first
            if await el.count() > 0:
                await el.click()
        except Exception:
            pass

    async def _captcha_pause(self, page: Page) -> bool:
        """
        Returns True if a CAPTCHA-like element is detected.
        Prints a message and waits for user to press Enter.
        """
        captcha_signals = [
            "iframe[src*='recaptcha']",
            "iframe[src*='hcaptcha']",
            "[class*='captcha']",
            "#captcha",
        ]
        for sel in captcha_signals:
            try:
                if await page.locator(sel).count() > 0:
                    print(
                        f"\n[CAPTCHA DETECTED on {page.url}]\n"
                        "Please solve the CAPTCHA in the browser window, then press Enter here to continue..."
                    )
                    input()
                    return True
            except Exception:
                pass
        return False
