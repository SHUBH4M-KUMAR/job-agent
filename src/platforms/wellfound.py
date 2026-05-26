"""
Wellfound (AngelList Talent): search AI/ML jobs at startups and apply.
"""

import asyncio
import re
from playwright.async_api import Page
from .base import BasePlatform, JobListing
from user_profile import USER_PROFILE


SEARCH_URL = "https://wellfound.com/jobs?q={query}&remote=true"


class WellfoundPlatform(BasePlatform):
    name = "wellfound"

    # ── search ────────────────────────────────────────────────────────────────

    async def search(self, page: Page, query: str) -> list[JobListing]:
        url = SEARCH_URL.format(query=query.replace(" ", "+"))
        await page.goto(url, timeout=30_000)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(3)

        # Wellfound uses obfuscated class names — use text/structure anchors.
        # Scroll gently so virtual-scroll renders cards, but stay near top.
        for _ in range(3):
            await page.keyboard.press("PageDown")
            await asyncio.sleep(1.2)
        # Scroll back to top so all cards are in the DOM
        await page.keyboard.press("Control+Home")
        await asyncio.sleep(1)

        # ── Use Playwright locator to count badges first (reliable) ──────────
        badge_loc = page.get_by_text("Apply on Wellfound")
        badge_count = await badge_loc.count()
        print(f"      [WF] Playwright badge count: {badge_count}", flush=True)

        raw = await page.evaluate("""
            () => {
                const jobs = [];
                const seen = new Set();
                const searchUrl = window.location.href;

                // Helper: find nearest heading text walking up the DOM
                function nearestHeading(el, exclude) {
                    let p = el.parentElement;
                    for (let i = 0; i < 14 && p && p !== document.body; i++) {
                        for (const tag of ['h1','h2','h3','h4']) {
                            const h = p.querySelector(tag);
                            if (h) {
                                const t = h.textContent.trim();
                                if (t && t !== exclude && t.length < 100
                                        && !/recruiter|actively|employees|stage|hiring/i.test(t)) {
                                    return t;
                                }
                            }
                        }
                        p = p.parentElement;
                    }
                    return '';
                }

                // Helper: find direct job-page link anywhere in subtree or ancestor chain
                function findJobLink(el, depth=6) {
                    const sub = el.querySelector('a[href*="/jobs/"]');
                    if (sub && /\\/jobs\\/[^?#]+/.test(sub.pathname) && sub.pathname !== '/jobs/') {
                        return sub.href;
                    }
                    let p = el.parentElement;
                    for (let i = 0; i < depth && p && p !== document.body; i++) {
                        const a = p.querySelector('a[href*="/jobs/"]');
                        if (a && /\\/jobs\\/[^?#]+/.test(a.pathname) && a.pathname !== '/jobs/') {
                            return a.href;
                        }
                        p = p.parentElement;
                    }
                    return '';
                }

                // ── Find badge elements ───────────────────────────────────────
                // Use innerText (not textContent) so hidden/decorative text is excluded.
                // Do NOT require children.length===0 — badge might have icon children.
                // Do NOT require offsetParent — some badge wrappers are position:fixed etc.
                const allEls = Array.from(document.querySelectorAll('*'));
                let badges = allEls.filter(el => {
                    const t = (el.innerText || '').trim();
                    return /apply on wellfound/i.test(t)
                        && t.length < 50   // exclude large containers
                        && el.getBoundingClientRect().width > 0;
                });

                // Keep only the most specific (deepest) badge elements —
                // remove ancestors so we don't process the same badge N times.
                const badgeSet = new Set(badges);
                for (const b of badges) {
                    let p = b.parentElement;
                    while (p && p !== document.body) { badgeSet.delete(p); p = p.parentElement; }
                }
                badges = Array.from(badgeSet);

                for (const badge of badges) {
                    // Walk up to find a row containing bullet-separated location/salary
                    let row = badge.parentElement;
                    for (let i = 0; i < 10 && row && row !== document.body; i++) {
                        if (/\\S[^\\n]*•[^\\n]*\\S/.test(row.innerText || '')) break;
                        row = row.parentElement;
                    }
                    if (!row || row === document.body) continue;

                    // Title: first non-noise line (skip lines with • or badge/button words)
                    const lines = (row.innerText || '').split('\\n')
                        .map(l => l.trim()).filter(l => l.length > 2);
                    let title = '';
                    for (const ln of lines) {
                        if (ln.includes('•')) continue;
                        if (/^(apply|save|hide|report|learn more|w:|recruiter|posted|ago|actively)/i.test(ln)) continue;
                        title = ln;
                        break;
                    }
                    if (!title) continue;

                    const company = nearestHeading(row, title);
                    const key = `${title}|${company}`;
                    if (seen.has(key)) continue;
                    seen.add(key);

                    const bulletLine = lines.find(l => l.includes('•')) || '';
                    const parts = bulletLine.split('•').map(s => s.trim()).filter(Boolean);
                    const jobHref = findJobLink(row, 6) || searchUrl;

                    jobs.push({
                        title,
                        company,
                        location: parts[0] || '',
                        salary: parts.slice(1, 3).join(' • '),
                        href: jobHref,
                        is_search_url: jobHref === searchUrl,
                    });
                }

                return jobs;
            }
        """)

        jobs: list[JobListing] = []
        for item in (raw or [])[:30]:
            try:
                title   = (item.get("title") or "").strip()
                company = (item.get("company") or "").strip()
                if not title:
                    continue
                job_id = re.sub(r"\W+", "_", (title + company)[:40])
                jobs.append(JobListing(
                    job_id=job_id,
                    platform=self.name,
                    title=title,
                    company=company,
                    location=(item.get("location") or "").strip(),
                    url=item.get("href", ""),
                    salary=(item.get("salary") or "").strip(),
                    easy_apply=True,
                    description=str(item.get("is_search_url", False)),  # temp flag
                ))
            except Exception:
                continue
        return jobs

    # ── apply ─────────────────────────────────────────────────────────────────

    async def apply(self, page: Page, job: JobListing, resume_path: str) -> tuple[bool, str]:
        """
        Wellfound native-apply flow:
          1. Navigate to job URL (direct page) OR search URL + click the job row.
          2. Extract job description from the left panel.
          3. Generate personalised "What interests you?" answer via Ollama.
          4. Fill the textarea and click Apply.
        """
        try:
            await page.goto(job.url, timeout=30_000)
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)
            await self._captcha_pause(page)

            # If we landed on a search-results page (no direct job URL was found),
            # click the job title row to open the job detail + apply panel.
            is_search_page = (
                "/jobs?" in page.url
                or "/jobs#" in page.url
                or page.url.rstrip("/") == "https://wellfound.com/jobs"
            )
            if is_search_page:
                clicked = await page.evaluate(f"""
                    () => {{
                        const title   = {repr(job.title)};
                        const company = {repr(job.company)};
                        // Find leaf nodes whose text exactly matches the job title
                        const els = Array.from(document.querySelectorAll('*')).filter(el =>
                            el.children.length === 0
                            && el.textContent.trim() === title
                            && el.offsetParent !== null
                        );
                        for (const el of els) {{
                            // Confirm the company name is in a nearby ancestor
                            let p = el.parentElement;
                            for (let i = 0; i < 10 && p && p !== document.body; i++) {{
                                if ((p.innerText || '').includes(company)) {{
                                    el.click();
                                    return true;
                                }}
                                p = p.parentElement;
                            }}
                        }}
                        // Fallback: click any element containing the title text
                        for (const el of els) {{ el.click(); return true; }}
                        return false;
                    }}
                """)
                if not clicked:
                    return False, f"Job row for '{job.title}' not found on search page"
                await asyncio.sleep(2.5)  # wait for apply panel to slide in

            # ── Extract description from left panel ───────────────────────────
            description = await page.evaluate("""
                () => {
                    const blocks = Array.from(document.querySelectorAll(
                        'p, li, [class*="description"], [class*="about"], [class*="prose"]'
                    )).filter(el => el.offsetParent !== null && el.textContent.trim().length > 30);
                    return blocks.slice(0, 20).map(el => el.textContent.trim()).join('\\n');
                }
            """)
            if description:
                job.description = description[:2000]

            # ── Click Apply / Submit Application if textarea not yet visible ──
            # On the job detail page the apply panel is hidden behind a button.
            textarea = page.locator("textarea").first
            if await textarea.count() == 0 or not await textarea.is_visible():
                open_btn = page.locator(
                    "button:has-text('Apply'), "
                    "button:has-text('Submit Application'), "
                    "a:has-text('Apply'), "
                    "a:has-text('Submit Application')"
                ).first
                if await open_btn.count() > 0:
                    await open_btn.click()
                    await asyncio.sleep(2)

            # ── Wait for apply panel textarea ─────────────────────────────────
            textarea = page.locator("textarea").first
            for _ in range(6):
                if await textarea.count() > 0 and await textarea.is_visible():
                    break
                await asyncio.sleep(0.8)
            else:
                return False, "Apply panel / textarea not found"

            # ── Generate interest answer ──────────────────────────────────────
            interest_text = await self._generate_interest_answer(
                company=job.company,
                title=job.title,
                description=job.description,
            )

            # ── Fill textarea (Playwright .fill() triggers React onChange) ────
            await textarea.click()
            await textarea.fill(interest_text)
            await asyncio.sleep(0.5)

            # ── Click submit button inside the modal ──────────────────────────
            # The modal button says "Send application" (not "Apply" — that button
            # is on the background page and gets intercepted by the ReactModal overlay).
            # Scope the search to the ReactModalPortal so we never hit the background.
            modal = page.locator(".ReactModalPortal, [class*='ReactModal__Content']").first
            submit_btn = None
            if await modal.count() > 0:
                submit_btn = modal.locator(
                    "button:has-text('Send application'), "
                    "button:has-text('Submit application'), "
                    "button:has-text('Apply')"
                ).last
            if submit_btn is None or await submit_btn.count() == 0:
                # Fallback: find any visible submit-like button not labelled Cancel
                submit_btn = page.locator(
                    "button:has-text('Send application'), "
                    "button:has-text('Submit application')"
                ).first

            if await submit_btn.count() == 0:
                return False, "Submit button not found in apply modal"

            # Use JS click to bypass ReactModal overlay interception
            await submit_btn.evaluate("el => el.click()")
            await asyncio.sleep(3)

            # ── Detect success ────────────────────────────────────────────────
            confirmed = await page.evaluate("""
                () => /applied|thank you|application submitted|success/i.test(
                    document.body.innerText
                )
            """)
            if confirmed or "applied" in page.url.lower():
                return True, ""

            # If textarea is gone, the apply went through (Wellfound hides it)
            if await textarea.count() == 0 or not await textarea.is_visible():
                return True, ""

            return False, "Apply clicked but no confirmation detected"

        except Exception as e:
            return False, f"Exception: {e}"

    # ── Ollama helper ─────────────────────────────────────────────────────────

    async def _generate_interest_answer(
        self, company: str, title: str, description: str
    ) -> str:
        """
        Write 2-3 sentences for "What interests you about working for this company?"
        Uses Ollama for a personalised answer; falls back to a template.
        """
        from config import OLLAMA_MODEL
        P = USER_PROFILE

        prompt = (
            f"You are filling a job application for {P['name']}, an ML/AI engineer "
            f"with {P['total_experience_years']} years of experience in LLMs, RAG, "
            f"computer vision, and agentic AI.\n\n"
            f"Company: {company}\n"
            f"Role: {title}\n"
            f"Job context:\n{description[:800]}\n\n"
            "Write 2-3 concise, genuine sentences answering: "
            "\"What interests you about working for this company?\"\n"
            "Be specific to the company/role. No generic filler. No preamble. "
            "First person. Under 120 words."
        )
        try:
            import ollama
            resp = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.4},
            )
            raw = re.sub(r"<think>.*?</think>", "", resp["message"]["content"],
                         flags=re.DOTALL).strip()
            if raw:
                return raw[:500]
        except Exception:
            pass

        return (
            f"I'm excited about {company}'s work because it directly aligns with my "
            f"background building production ML systems — LLMs, RAG pipelines, and "
            f"agentic AI. The {title} role matches my hands-on experience shipping "
            f"end-to-end AI products, and I'm drawn to contributing at a company that "
            f"moves fast on real problems."
        )
