"""
Indeed India: search jobs and apply.
Handles both Indeed-native apply and external ATS portals (Greenhouse, Lever, Workday, etc.)
"""

import asyncio
import re
from playwright.async_api import Page
from .base import BasePlatform, JobListing
from user_profile import USER_PROFILE

SEARCH_URL = "https://in.indeed.com/jobs?q={query}&l=India&sc=0kf%3Aattr%28DSQF7%29%3B&sort=date"
# attr(DSQF7) = Remote filter


class IndeedPlatform(BasePlatform):
    name = "indeed"

    async def search(self, page: Page, query: str) -> list[JobListing]:
        url = SEARCH_URL.format(query=query.replace(" ", "+"))
        await page.goto(url, timeout=30_000)
        await asyncio.sleep(2)
        await self._captcha_pause(page)

        # Wait for cards
        for sel in ["div.job_seen_beacon", ".jobsearch-ResultsList", "#mosaic-jobResults"]:
            try:
                await page.wait_for_selector(sel, timeout=6_000)
                break
            except Exception:
                continue

        cards = []
        for card_sel in [
            "div.job_seen_beacon",
            "div.resultContent",
            "li.css-5lfssm",
        ]:
            cards = await page.query_selector_all(card_sel)
            if cards:
                break

        if not cards:
            print(f"[Indeed] No cards found for '{query}'")
            return []

        jobs: list[JobListing] = []
        for card in cards[:25]:
            try:
                title_el = None
                for t_sel in [
                    "h2.jobTitle a",
                    "a.jcs-JobTitle",
                    "h2 a[data-jk]",
                    "a[id^='job_']",
                ]:
                    title_el = await card.query_selector(t_sel)
                    if title_el:
                        break

                company_el = None
                for c_sel in [
                    "[data-testid='company-name']",
                    "span.companyName",
                    ".css-63koeb",
                ]:
                    company_el = await card.query_selector(c_sel)
                    if company_el:
                        break

                location_el = None
                for l_sel in [
                    "[data-testid='text-location']",
                    "div.companyLocation",
                    ".css-1p0sjhy",
                ]:
                    location_el = await card.query_selector(l_sel)
                    if location_el:
                        break

                salary_el = None
                for s_sel in [
                    "[data-testid='attribute_snippet_testid']",
                    ".salary-snippet-container",
                    ".css-1cvvo1h",
                ]:
                    salary_el = await card.query_selector(s_sel)
                    if salary_el:
                        break

                title    = (await title_el.inner_text()).strip()    if title_el    else ""
                company  = (await company_el.inner_text()).strip()  if company_el  else ""
                location = (await location_el.inner_text()).strip() if location_el else ""
                salary   = (await salary_el.inner_text()).strip()   if salary_el   else ""

                job_id = await card.get_attribute("data-jk") or ""
                href   = await title_el.get_attribute("href") if title_el else ""
                if not job_id and href:
                    m = re.search(r"jk=([a-z0-9]+)", href)
                    if m:
                        job_id = m.group(1)

                full_url = (
                    f"https://in.indeed.com{href}"
                    if href and href.startswith("/")
                    else href or ""
                )

                if not title:
                    continue

                jobs.append(JobListing(
                    job_id=job_id or re.sub(r"\W+", "_", title + company),
                    platform=self.name,
                    title=title,
                    company=company,
                    location=location,
                    url=full_url,
                    salary=salary,
                    easy_apply=False,
                ))
            except Exception:
                continue

        return jobs

    async def apply(self, page: Page, job: JobListing, resume_path: str) -> tuple[bool, str]:
        try:
            await page.goto(job.url, timeout=30_000)
            await asyncio.sleep(2)
            await self._captcha_pause(page)

            # Extract description
            for d_sel in ["#jobDescriptionText", ".jobsearch-jobDescriptionText", ".job-desc"]:
                el = page.locator(d_sel).first
                if await el.count() > 0:
                    job.description = (await el.inner_text()).strip()
                    break

            # Find the Apply button
            apply_btn = None
            for b_sel in [
                "button[id='indeedApplyButton']",
                "button[id*='apply']",
                "a[id*='apply']",
                "button:has-text('Apply now')",
                "button:has-text('Apply')",
                "a:has-text('Apply on company site')",
                "a:has-text('Apply')",
            ]:
                apply_btn = page.locator(b_sel).first
                if await apply_btn.count() > 0:
                    break

            if not apply_btn or await apply_btn.count() == 0:
                return False, "Apply button not found"

            # Note which pages exist before clicking (may open new tab)
            pages_before = len(page.context.pages)
            await apply_btn.click()
            await asyncio.sleep(3)

            # Check if a new tab opened (company portal)
            all_pages = page.context.pages
            if len(all_pages) > pages_before:
                target = all_pages[-1]
                await target.wait_for_load_state("domcontentloaded")
                portal_url = target.url
                await asyncio.sleep(2)
            else:
                target = page
                portal_url = page.url

            await self._captcha_pause(target)
            ok = await self._fill_ats_form(target, resume_path)
            if ok:
                return True, ""
            return False, f"ATS form incomplete — portal: {portal_url}"

        except Exception as e:
            return False, f"Exception: {e}"

    async def _fill_ats_form(self, page: Page, resume_path: str) -> bool:
        """
        Generic ATS form filler — handles Indeed-native, Greenhouse, Lever, and generic portals.
        """
        profile = USER_PROFILE
        answers = profile["form_answers"]

        for step in range(10):
            await asyncio.sleep(2)
            await self._captcha_pause(page)

            # Resume / file upload
            for up_sel in ["input[type='file']", "input[accept*='pdf']", "input[accept*='.pdf']"]:
                upload = page.locator(up_sel).first
                if await upload.count() > 0 and resume_path:
                    await upload.set_input_files(resume_path)
                    await asyncio.sleep(1)
                    break

            # Fill named fields first (most reliable)
            named_fills = [
                (["input[name*='first'][type='text']", "input[id*='first'][type='text']"],
                 profile["name"].split()[0]),
                (["input[name*='last'][type='text']", "input[id*='last'][type='text']"],
                 profile["name"].split()[-1]),
                (["input[name*='name'][type='text']", "input[id*='name'][type='text']",
                  "input[placeholder*='name' i]"],
                 profile["name"]),
                (["input[name*='email']", "input[type='email']", "input[id*='email']"],
                 profile["email"]),
                (["input[name*='phone']", "input[name*='mobile']", "input[type='tel']",
                  "input[id*='phone']"],
                 profile["phone"]),
                (["input[name*='linkedin']", "input[id*='linkedin']",
                  "input[placeholder*='linkedin' i]"],
                 profile["linkedin"]),
                (["input[name*='github']", "input[id*='github']",
                  "input[placeholder*='github' i]"],
                 profile["github"]),
                (["input[name*='location']", "input[name*='city']",
                  "input[placeholder*='city' i]", "input[placeholder*='location' i]"],
                 "Aligarh, India"),
            ]
            for selectors, value in named_fills:
                for sel in selectors:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible():
                        await el.triple_click()
                        await el.fill(value)
                        break

            # Generic visible text inputs — map by placeholder / label
            inputs = await page.query_selector_all(
                "input[type='text']:not([type='hidden']), "
                "input[type='number'], input[type='tel'], textarea"
            )
            for inp in inputs:
                if not await inp.is_visible():
                    continue
                ph   = (await inp.get_attribute("placeholder") or "").lower()
                name = (await inp.get_attribute("name") or "").lower()
                label = ph or name
                value = self._map_field(label, answers, profile)
                if value:
                    current = await inp.input_value()
                    if not current:   # only fill if empty
                        await inp.fill(value)

            # Select dropdowns
            selects = await page.query_selector_all("select")
            for sel_el in selects:
                if not await sel_el.is_visible():
                    continue
                name = (await sel_el.get_attribute("name") or "").lower()
                value = self._map_field(name, answers, profile)
                if value:
                    try:
                        await sel_el.select_option(label=value)
                    except Exception:
                        pass

            # Cover letter textarea
            for tsel in ["textarea[name*='cover']", "textarea[id*='cover']",
                         "textarea[placeholder*='cover' i]"]:
                ta = page.locator(tsel).first
                if await ta.count() > 0 and await ta.is_visible():
                    if not await ta.input_value():
                        await ta.fill(answers["cover_letter_default"])

            # Check for "Yes/No" required questions and default to Yes
            for radio in await page.query_selector_all("input[type='radio']"):
                val = (await radio.get_attribute("value") or "").lower()
                if val in ("yes", "true", "1"):
                    try:
                        if await radio.is_visible() and not await radio.is_checked():
                            parent = await radio.query_selector("xpath=..")
                            if parent:
                                label_el = await parent.query_selector("label")
                                # Only auto-check positive answers
                                await radio.check()
                    except Exception:
                        pass

            # ── Look for Submit ────────────────────────────────────────────────
            submitted = False
            for s_sel in [
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('Submit application')",
                "button:has-text('Submit')",
                "button:has-text('Send application')",
                "button:has-text('Apply')",
            ]:
                btn = page.locator(s_sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(2)
                    submitted = True
                    break

            if submitted:
                # Handle any post-submit confirmation
                for c_sel in ["button:has-text('Done')", "button:has-text('OK')",
                               "button:has-text('Close')"]:
                    c = page.locator(c_sel).first
                    if await c.count() > 0:
                        await c.click()
                return True

            # ── Next step ──────────────────────────────────────────────────────
            advanced = False
            for n_sel in [
                "button:has-text('Next')",
                "button:has-text('Continue')",
                "button:has-text('Save and continue')",
                "a:has-text('Next')",
            ]:
                n_btn = page.locator(n_sel).first
                if await n_btn.count() > 0 and await n_btn.is_visible():
                    await n_btn.click()
                    advanced = True
                    break

            if not advanced:
                break

        return False

    def _map_field(self, label: str, answers: dict, profile: dict) -> str:
        l = label.lower()
        if "phone" in l or "mobile" in l or "tel" in l:
            return profile["phone"]
        if "email" in l:
            return profile["email"]
        if "linkedin" in l:
            return profile["linkedin"]
        if "github" in l or "portfolio" in l:
            return profile["github"]
        if "notice" in l:
            return answers["notice_period"]
        if ("current" in l or "last" in l) and ("salary" in l or "ctc" in l or "compensation" in l):
            return answers["current_ctc"]
        if ("expected" in l or "desired" in l) and ("salary" in l or "ctc" in l or "compensation" in l):
            return answers["expected_ctc"]
        if "experience" in l:
            return answers["years_of_experience"]
        if "cover" in l:
            return answers["cover_letter_default"]
        if "city" in l or "location" in l:
            return "Aligarh, India"
        return ""
