"""
LinkedIn: search jobs and apply via Easy Apply.
"""

import asyncio
import re
from playwright.async_api import Page
from .base import BasePlatform, JobListing
from user_profile import USER_PROFILE
from src.skip_controller import skipper

LOGIN_URL = "https://www.linkedin.com/login"

# f_WT=2%2C3%2C1 = Remote + Hybrid + On-site  |  f_AL=true = Easy Apply only  |  sortBy=R = most recent
JOBS_URL = (
    "https://www.linkedin.com/jobs/search/"
    "?keywords={query}&location=India&f_WT=2%2C3%2C1&f_AL=true&sortBy=R"
)

MAX_SEARCH_RESULTS = 50
SEARCH_SCROLL_PASSES = 10


class LinkedInPlatform(BasePlatform):
    name = "linkedin"

    # ── search ────────────────────────────────────────────────────────────────

    async def search(self, page: Page, query: str) -> list[JobListing]:
        url = JOBS_URL.format(query=query.replace(" ", "%20"))
        await page.goto(url, timeout=30_000)
        await asyncio.sleep(3)

        # Wait for job list to appear — try multiple possible containers
        for sel in [
            ".jobs-search-results-list",
            ".scaffold-layout__list",
            "[data-results-list]",
            "ul.jobs-search__results-list",
        ]:
            try:
                await page.wait_for_selector(sel, timeout=6_000)
                break
            except Exception:
                continue

        card_selectors = [
            "li[data-occludable-job-id]",
            "li.jobs-search-results__list-item",
            "div.job-card-container",
        ]

        # Scroll more aggressively until result count stabilizes.
        best_selector = None
        best_count = 0
        stable_passes = 0
        for _ in range(SEARCH_SCROLL_PASSES):
            for card_sel in card_selectors:
                count = await page.locator(card_sel).count()
                if count > best_count:
                    best_count = count
                    best_selector = card_sel
            await page.keyboard.press("End")
            await asyncio.sleep(1.5)
            await page.mouse.wheel(0, 4000)
            await asyncio.sleep(1.0)
            new_count = best_count
            if best_selector:
                try:
                    new_count = await page.locator(best_selector).count()
                except Exception:
                    pass
            if new_count <= best_count:
                stable_passes += 1
            else:
                stable_passes = 0
                best_count = new_count
            if best_count >= MAX_SEARCH_RESULTS or stable_passes >= 3:
                break

        # Try multiple card selectors — LinkedIn changes these often
        cards = []
        for card_sel in card_selectors:
            cards = await page.query_selector_all(card_sel)
            if cards:
                break

        if not cards:
            console_msg = f"[LinkedIn] No cards found for '{query}' — page may need login or selector changed"
            print(console_msg)
            return []

        jobs: list[JobListing] = []
        for card in cards[:MAX_SEARCH_RESULTS]:
            try:
                job_id = (
                    await card.get_attribute("data-occludable-job-id")
                    or await card.get_attribute("data-job-id")
                    or ""
                )

                # Title — try several selector variants
                title_el = None
                for t_sel in [
                    "a.job-card-list__title--link",
                    "a.job-card-list__title",
                    "a[data-control-name='jobcard_title']",
                    ".job-card-list__title a",
                    "a.disabled.job-card-list__title",
                ]:
                    title_el = await card.query_selector(t_sel)
                    if title_el:
                        break

                # Company
                company_el = None
                for c_sel in [
                    ".job-card-container__primary-description",
                    ".job-card-container__company-name",
                    ".artdeco-entity-lockup__subtitle span",
                    "span.job-card-container__primary-description",
                ]:
                    company_el = await card.query_selector(c_sel)
                    if company_el:
                        break

                # Location
                location_el = None
                for l_sel in [
                    ".job-card-container__metadata-item",
                    ".job-card-container__metadata-wrapper li",
                    "li.job-card-container__metadata-item",
                ]:
                    location_el = await card.query_selector(l_sel)
                    if location_el:
                        break

                title = (await title_el.inner_text()).strip() if title_el else ""
                company = (await company_el.inner_text()).strip() if company_el else ""
                location = (
                    (await location_el.inner_text()).strip() if location_el else ""
                )

                href = await title_el.get_attribute("href") if title_el else ""
                job_url = (
                    f"https://www.linkedin.com{href}"
                    if href and href.startswith("/")
                    else href or ""
                )

                # Extract job ID from URL if not found on card
                if not job_id and job_url:
                    m = re.search(r"/jobs/view/(\d+)", job_url)
                    if m:
                        job_id = m.group(1)

                if not title:
                    continue

                jobs.append(
                    JobListing(
                        job_id=job_id or re.sub(r"\W+", "_", title + company),
                        platform=self.name,
                        title=title,
                        company=company,
                        location=location,
                        url=job_url,
                        easy_apply=True,
                    )
                )
            except Exception:
                continue

        return jobs

    async def get_description(self, page: Page, job: JobListing) -> str:
        try:
            # Click the matching card to open the detail pane
            for card_sel in [
                f"li[data-occludable-job-id='{job.job_id}']",
                f"div[data-job-id='{job.job_id}']",
            ]:
                card = page.locator(card_sel).first
                if await card.count() > 0:
                    await card.click()
                    await asyncio.sleep(2)
                    break

            for desc_sel in [
                ".jobs-description__content",
                ".jobs-description-content__text",
                "#job-details",
            ]:
                el = page.locator(desc_sel).first
                if await el.count() > 0:
                    return (await el.inner_text()).strip()
        except Exception:
            pass
        return ""

    # ── apply ─────────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        print(f"      [LI] {msg}", flush=True)

    async def apply(
        self, page: Page, job: JobListing, resume_path: str
    ) -> tuple[bool, str]:
        try:
            self._log(f"Navigating to job page: {job.url}")
            await page.goto(job.url, timeout=30_000)
            await asyncio.sleep(2)
            await self._captcha_pause(page)
            self._log("Page loaded.")

            # Wait up to 8s for the apply button
            self._log("Waiting for Easy Apply button...")
            try:
                await page.wait_for_selector(
                    "button.jobs-apply-button, "
                    "button[aria-label*='Easy Apply'], button:has-text('Easy Apply'), "
                    "button[aria-label*='LinkedIn Apply']",
                    timeout=8_000,
                )
                self._log("Selector wait done.")
            except Exception:
                self._log("Selector wait timed out — trying JS anyway.")

            # Find all buttons on page for debug
            btn_texts = await page.evaluate("""
                () => Array.from(document.querySelectorAll('button')).map(b => b.textContent.trim()).filter(t => t)
            """)
            self._log(f"Buttons on page: {btn_texts[:10]}")

            clicked = await self._click_easy_apply_button(page)

            if not clicked:
                self._log("Verified Easy Apply button NOT found on page.")
                return False, "Verified Easy Apply button not found on page"

            self._log(f"Clicked button: '{clicked}'")
            surface = await self._wait_for_application_surface(page)
            if surface == "modal":
                self._log("Application modal detected after click.")
            elif surface == "inline":
                self._log("Inline application form detected after click.")
            elif surface == "external":
                self._log("Detected external apply flow instead of Easy Apply.")
                return False, "External apply flow opened instead of Easy Apply"
            else:
                self._log("No application surface detected after clicking Easy Apply.")
                return False, "Clicked apply but no application surface opened"

            ok = await self._fill_easy_apply_modal(page, resume_path)
            return (True, "") if ok else (False, "Modal form did not reach Submit")

        except Exception as e:
            self._log(f"Exception in apply: {e}")
            return False, f"Exception: {e}"

    async def _click_easy_apply_button(self, page: Page) -> str | None:
        candidates = [
            (
                "button[aria-label='LinkedIn Apply to this job']",
                "exact linkedin apply",
            ),
            (
                "button[aria-label*='LinkedIn Apply to this job']",
                "partial linkedin apply to this job",
            ),
            ("button.jobs-apply-button", "jobs-apply-button"),
            ("button[aria-label*='Easy Apply']", "aria easy apply"),
            ("button:has-text('Easy Apply')", "text easy apply"),
            ("button[aria-label*='LinkedIn Apply']", "aria linkedin apply"),
        ]

        for selector, name in candidates:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                for i in range(count):
                    btn = locator.nth(i)
                    if not await btn.is_visible():
                        continue
                    try:
                        await btn.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    text = ((await btn.inner_text()) or "").strip()
                    aria = ((await btn.get_attribute("aria-label")) or "").strip()
                    self._log(
                        f"Trying Easy Apply candidate [{name}]: text='{text[:60]}' aria='{aria[:60]}'"
                    )
                    try:
                        await btn.click(timeout=5_000)
                        return text or aria or name
                    except Exception as e:
                        self._log(f"Candidate click failed [{name}]: {e}")
            except Exception as e:
                self._log(f"Candidate lookup failed [{name}]: {e}")
        return None

    async def _wait_for_application_surface(self, page: Page) -> str | None:
        checks = [
            (
                "modal",
                ".jobs-easy-apply-modal, "
                ".artdeco-modal:has(h2:has-text('Apply to')), "
                "[role='dialog']:has(h2:has-text('Apply to')), "
                "[data-sdui-screen*='easyapply']",
            ),
            (
                "inline",
                ".jobs-easy-apply-form-section__grouping, .jobs-easy-apply-form-element, [data-sdui-screen*='easyapply'] input, [data-sdui-screen*='easyapply'] select",
            ),
        ]

        for _ in range(12):
            await asyncio.sleep(0.75)
            for surface_name, selector in checks:
                try:
                    if await page.locator(selector).count() > 0:
                        return surface_name
                except Exception:
                    continue
        return None

    async def _fill_easy_apply_modal(self, page: Page, resume_path: str) -> bool:
        profile = USER_PROFILE
        answers = profile["form_answers"]

        self._log("Waiting for modal to appear...")
        try:
            await page.wait_for_selector(
                ".jobs-easy-apply-modal, "
                ".artdeco-modal:has(h2:has-text('Apply to')), "
                "[role='dialog']:has(h2:has-text('Apply to')), "
                "[data-sdui-screen*='easyapply']",
                timeout=10_000,
            )
            self._log("Modal detected.")
            await asyncio.sleep(1)
        except Exception:
            self._log("Modal wait timed out.")
            return False

        for step in range(15):
            await asyncio.sleep(0.8)

            # User pressed 's' — abort immediately
            if skipper.requested():
                self._log("Skip requested — closing modal and aborting.")
                await page.evaluate("""
                    () => {
                        const btn = document.querySelector('button[aria-label="Dismiss"], button[aria-label="Close"]');
                        if (btn) btn.click();
                    }
                """)
                return False

            await self._captcha_pause(page)

            # Dismiss messaging overlay and find the actual apply form
            try:
                await page.evaluate("""
                    () => {
                        // Close messaging overlay
                        const overlay = document.querySelector('.msg-overlay-bubble-header');
                        if (overlay) {
                            const closeBtn = overlay.querySelector('button');
                            if (closeBtn) closeBtn.click();
                        }
                    }
                """)
            except Exception:
                pass

            self._log(f"--- Modal step {step + 1} ---")
            scope = await self._get_easy_apply_scope(page)
            if scope == page:
                if await self._check_submit_success(page):
                    self._log("SUCCESS - application submitted after modal closed.")
                    return True
                self._log("Easy Apply scope not found.")
                return False

            state = await self._get_easy_apply_state(scope)
            buttons_in_scope = await self._list_buttons(scope)
            self._log(f"Easy Apply state: {state}")
            self._log(f"Buttons in dialog: {buttons_in_scope[:12]}")

            if state == "review":
                submit_clicked = await self._click_easy_apply_action(
                    scope,
                    ["Submit application", "Submit", "Send application"],
                )
                if not submit_clicked:
                    self._log("Submit button not found on review page.")
                    return False
                await asyncio.sleep(1)
                if await self._check_submit_success(page):
                    self._log("SUCCESS - application submitted!")
                    return True
                validation_errors = await self._get_validation_errors(page)
                if validation_errors:
                    await self._fix_validation_errors(page, validation_errors)
                    continue
                continue

            direct_submit = await self._click_easy_apply_action(
                scope,
                ["Submit application", "Submit", "Send application"],
            )
            if direct_submit:
                await asyncio.sleep(1)
                if await self._check_submit_success(page):
                    self._log("SUCCESS - application submitted!")
                    return True
                validation_errors = await self._get_validation_errors(page)
                if validation_errors:
                    self._log(
                        f"Direct submit blocked by {len(validation_errors)} validation errors"
                    )
                    await self._fix_validation_errors(page, validation_errors)
                    continue
                scope_after_submit = await self._get_easy_apply_scope(page)
                if scope_after_submit == page:
                    if await self._check_submit_success(page):
                        self._log("SUCCESS - application submitted after modal closed.")
                        return True
                continue

            if state == "additional_questions":
                await self._fill_additional_questions(scope, answers, profile)
                remaining_unchecked = await scope.locator(
                    "input[type='radio']:visible:not(:checked)"
                ).count()
                if remaining_unchecked:
                    self._log(
                        f"{remaining_unchecked} radio options still unchecked after fill pass"
                    )
                validation_errors = await self._get_validation_errors(page)
                if validation_errors:
                    self._log(
                        f"Found {len(validation_errors)} validation errors after question fill"
                    )
                    await self._fix_validation_errors(page, validation_errors)
                    continue

                review_clicked = await self._click_easy_apply_action(
                    scope, ["Review", "Review your application"]
                )
                if not review_clicked:
                    self._log("Review button not found on additional questions page.")
                    return False
                await asyncio.sleep(1)
                validation_errors = await self._get_validation_errors(page)
                if validation_errors:
                    self._log(
                        f"Review blocked by {len(validation_errors)} validation errors"
                    )
                    await self._fix_validation_errors(page, validation_errors)
                    continue
                continue

            await self._fill_basic_easy_apply_fields(scope, answers, profile)
            validation_errors = await self._get_validation_errors(page)
            if validation_errors:
                await self._fix_validation_errors(page, validation_errors)
                continue

            advanced = await self._click_easy_apply_action(
                scope,
                ["Next", "Continue to next step", "Continue", "Review"],
            )
            if advanced:
                await asyncio.sleep(1)
                validation_errors = await self._get_validation_errors(page)
                if validation_errors:
                    await self._fix_validation_errors(page, validation_errors)
                continue

            self._log("No recognized action button in Easy Apply dialog.")
            return False

        self._log("Modal loop ended without confirmed submission.")
        return False

    async def _get_easy_apply_scope(self, page: Page):
        modal_selectors = [
            ".artdeco-modal:has(h2:has-text('Apply to'))",
            "[role='dialog']:has(h2:has-text('Apply to'))",
            "[data-sdui-screen*='easyapply']",
            ".jobs-easy-apply-modal",
            ".artdeco-modal__content:has(h3:has-text('Review your application'))",
            ".jobs-easy-apply-modal",
            ".jobs-easy-apply-content",
            ".artdeco-modal",
        ]

        for sel in modal_selectors:
            try:
                modal = page.locator(sel).last
                if await modal.count() > 0 and await modal.is_visible():
                    form_count = await modal.locator(
                        "button, input, select, textarea, [data-sdui-screen*='easyapply']"
                    ).count()
                    if form_count > 0:
                        self._log(f"Found modal with selector: {sel}")
                        return modal
            except Exception:
                continue

        self._log("Modal not found - falling back to page scope")
        return page

    async def _list_buttons(self, scope) -> list[str]:
        try:
            return await scope.locator("button").evaluate_all(
                """els => els
                    .map(el => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim())
                    .filter(Boolean)"""
            )
        except Exception:
            return []

    async def _get_easy_apply_state(self, scope) -> str:
        try:
            text = (await scope.inner_text()).lower()
        except Exception:
            return "unknown"
        if "review your application" in text:
            return "review"
        if "additional questions" in text:
            return "additional_questions"
        return "form"

    async def _click_easy_apply_action(self, scope, labels: list[str]) -> str | None:
        for label in labels:
            try:
                btn = scope.get_by_role("button", name=label, exact=False)
                if await btn.count() == 0:
                    continue
                if not await btn.first.is_visible():
                    continue
                await btn.first.scroll_into_view_if_needed()
                await btn.first.click()
                self._log(f"Clicked dialog button: '{label}'")
                return label
            except Exception:
                continue
        try:
            buttons = await scope.locator("button").all()
            for button in buttons:
                if not await button.is_visible():
                    continue
                text = ((await button.inner_text()) or "").strip()
                aria = ((await button.get_attribute("aria-label")) or "").strip()
                haystack = f"{text} {aria}".lower()
                for label in labels:
                    if label.lower() in haystack:
                        try:
                            await button.scroll_into_view_if_needed()
                        except Exception:
                            pass
                        await button.click()
                        self._log(
                            f"Clicked dialog button by fuzzy match: '{text or aria}'"
                        )
                        return text or aria or label
        except Exception:
            pass
        return None

    async def _fill_basic_easy_apply_fields(
        self, scope, answers: dict, profile: dict
    ) -> int:
        filled = 0
        fields = await scope.locator(
            "input:not([type='hidden']):not([type='file']):not([type='radio']):not([type='checkbox']), textarea, select"
        ).all()
        for field in fields:
            try:
                if not await field.is_visible():
                    continue
                meta = await self._get_input_meta(field)
                if meta.get("value") and meta.get("valid", True):
                    continue
                label = await self._get_label(scope, field)
                if not label:
                    continue
                if meta.get("tag") == "select":
                    options = await field.evaluate(
                        "el => Array.from(el.options).map(o => o.text.trim()).filter(Boolean)"
                    )
                    pick = self._answer_for_label(label, answers, profile)
                    if pick:
                        try:
                            await field.select_option(label=pick)
                            filled += 1
                        except Exception:
                            pass
                    continue
                value = self._answer_for_label(label, answers, profile)
                if not value:
                    continue
                if self._looks_numeric_from_meta(meta):
                    value = self._extract_number(value)
                await field.fill(value)
                filled += 1
            except Exception:
                continue
        if filled:
            self._log(f"Filled {filled} non-question Easy Apply fields")
        return filled

    async def _fill_additional_questions(
        self, scope, answers: dict, profile: dict
    ) -> int:
        filled = 0
        self._log("Filling Additional Questions with Ollama-backed answers...")

        try:
            await self._handle_radio_groups(scope, answers, profile)
        except Exception as e:
            self._log(f"Additional question radio handling error: {e}")

        fields = await scope.locator(
            "input:not([type='hidden']):not([type='file']):not([type='radio']):not([type='checkbox']), textarea, select"
        ).all()
        for field in fields:
            try:
                if not await field.is_visible():
                    continue
                label = await self._get_label(scope, field)
                if not label:
                    continue
                meta = await self._get_input_meta(field)
                if meta.get("value") and meta.get("valid", True):
                    continue

                if meta.get("tag") == "select":
                    options = await field.evaluate(
                        "el => Array.from(el.options).map(o => o.text.trim()).filter(t => t && t.toLowerCase() !== 'select an option')"
                    )
                    if not options:
                        continue
                    value = self._answer_for_label(label, answers, profile)
                    if not value:
                        value = await self._ask_ollama_dropdown(label, options)
                    try:
                        await field.select_option(label=value)
                    except Exception:
                        await field.select_option(index=1)
                    self._log(f"  Additional question select: '{label[:70]}' -> '{value}'")
                    filled += 1
                    continue

                value = self._answer_for_label(label, answers, profile)
                if self._looks_like_numeric_question(label, meta):
                    if not value:
                        value = await self._ask_ollama_number(label)
                    value = self._extract_number(value)
                elif not value:
                    value = await self._ask_ollama_freetext(label)

                if not value:
                    continue

                await field.fill(value)
                self._log(f"  Additional question input: '{label[:70]}' -> '{value[:60]}'")
                filled += 1
            except Exception as e:
                self._log(f"Additional question fill error: {e}")
                continue

        fixed = await self._fix_browser_invalid_inputs(scope, answers, profile)
        if fixed:
            self._log(f"Fixed {fixed} invalid additional-question fields")
        return filled + fixed

    def _looks_like_numeric_question(self, label: str, meta: dict) -> bool:
        l = (label or "").lower()
        if self._looks_numeric_from_meta(meta):
            return True
        return any(
            key in l
            for key in [
                "how many years",
                "years of experience",
                "ctc",
                "salary",
                "notice period",
                "np",
                "days",
                "experience you have as",
            ]
        )

    async def _check_submit_success(self, page: Page) -> bool:
        """Returns True if LinkedIn shows a post-submission success indicator."""
        success_signals = [
            # Success toast / banner
            ".artdeco-toast-item--success",
            "[data-test-success-modal]",
            # Text-based: LinkedIn shows "Your application was sent to X"
        ]
        for sel in success_signals:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        # Check page text for success phrases
        try:
            text = await page.evaluate("() => document.body.innerText")
            for phrase in [
                "application was sent",
                "your application was submitted",
                "successfully applied",
                "application submitted",
            ]:
                if phrase in text.lower():
                    return True
        except Exception:
            pass
        return False

    async def _get_unresolved_required_fields(self, container) -> list[dict]:
        try:
            return await container.evaluate(
                """root => {
                    if (!root) return [];
                    const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                    const visible = el => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                    };
                    const labelFor = el => {
                        const values = [];
                        const push = value => {
                            const cleaned = clean(value);
                            if (cleaned) values.push(cleaned);
                        };
                        const id = el.id || '';
                        if (id) {
                            for (const lbl of root.querySelectorAll(`label[for="${id}"]`)) push(lbl.innerText || lbl.textContent);
                        }
                        for (const ref of (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean)) {
                            const node = root.querySelector(`#${ref}`) || document.getElementById(ref);
                            if (node) push(node.innerText || node.textContent);
                        }
                        const group = el.closest('.jobs-easy-apply-form-section__grouping, .jobs-easy-apply-form-element, .fb-form-element, .fb-dash-form-element, fieldset, [data-test-form-element], .artdeco-form-element, [class*="form-element"]');
                        if (group) {
                            push(group.querySelector('legend')?.innerText);
                            push(group.querySelector('.artdeco-text-input--label')?.innerText);
                            push(group.querySelector('label')?.innerText);
                            push(group.querySelector('[id*="label"]')?.innerText);
                        }
                        push(el.getAttribute('aria-label'));
                        push(el.getAttribute('placeholder'));
                        const bad = new Set(['search', 'next', 'review', 'submit', 'yes', 'no']);
                        return values.find(v => !bad.has(v.toLowerCase())) || values[0] || '';
                    };

                    const unresolved = [];
                    for (const field of root.querySelectorAll('input, textarea, select')) {
                        if (!visible(field) || field.disabled || field.type === 'hidden' || field.type === 'file') continue;
                        if (field.type === 'radio' || field.type === 'checkbox') continue;
                        const required = !!field.required || field.getAttribute('aria-required') === 'true';
                        const value = 'value' in field ? clean(field.value) : '';
                        const valid = typeof field.checkValidity === 'function' ? field.checkValidity() : true;
                        if (!required && valid && value) continue;
                        if ((required && !value) || !valid) {
                            unresolved.push({
                                kind: field.tagName.toLowerCase(),
                                type: (field.getAttribute('type') || '').toLowerCase(),
                                label: labelFor(field),
                                value,
                                validation_message: field.validationMessage || '',
                            });
                        }
                    }

                    const groups = new Map();
                    for (const radio of root.querySelectorAll('input[type="radio"]')) {
                        if (!visible(radio) || radio.disabled) continue;
                        const group = radio.closest('.jobs-easy-apply-form-section__grouping, .jobs-easy-apply-form-element, .fb-form-element, .fb-dash-form-element, fieldset, [data-test-form-element], .artdeco-form-element, [class*="form-element"]') || radio.parentElement;
                        const key = radio.name || labelFor(radio) || clean(group?.innerText);
                        if (!key) continue;
                        if (!groups.has(key)) {
                            groups.set(key, {
                                required: !!radio.required || radio.getAttribute('aria-required') === 'true' || !!group?.querySelector('[aria-required="true"]') || /\\*/.test(clean(group?.innerText)),
                                checked: false,
                                label: labelFor(radio) || clean(group?.querySelector('legend')?.innerText || group?.querySelector('label')?.innerText || group?.innerText),
                            });
                        }
                        if (radio.checked) groups.get(key).checked = true;
                    }

                    for (const info of groups.values()) {
                        if (info.required && !info.checked) {
                            unresolved.push({
                                kind: 'radio',
                                type: 'radio',
                                label: info.label,
                                value: '',
                                validation_message: 'selection required',
                            });
                        }
                    }

                    return unresolved.slice(0, 20);
                }"""
            )
        except Exception as e:
            self._log(f"Required field scan failed: {e}")
            return []

    async def _resolve_required_fields(self, container, fields: list[dict]) -> int:
        fixed = 0
        answers = USER_PROFILE["form_answers"]
        for field in fields:
            label = (field.get("label") or "").strip()
            kind = (field.get("kind") or "").lower()
            field_type = (field.get("type") or "").lower()
            try:
                if kind == "radio" or field_type == "radio":
                    await self._handle_radio_groups(container, answers, USER_PROFILE)
                    fixed += 1
                    continue

                target = None
                if label:
                    target = container.get_by_label(label, exact=False).first
                    if await target.count() == 0:
                        target = container.get_by_placeholder(label, exact=False).first
                if target is None or await target.count() == 0:
                    continue

                meta = await self._get_input_meta(target)
                if meta.get("tag") == "select":
                    options = await target.evaluate(
                        "el => Array.from(el.options).map(o => o.text.trim()).filter(t => t && t.toLowerCase() !== 'select an option')"
                    )
                    if not options:
                        continue
                    pick = self._answer_for_label(label, answers, USER_PROFILE)
                    if not pick:
                        pick = await self._ask_ollama_dropdown(label, options)
                    try:
                        await target.select_option(label=pick)
                    except Exception:
                        await target.select_option(index=1)
                    fixed += 1
                    continue

                value = self._answer_for_label(label, answers, USER_PROFILE)
                if self._looks_numeric_from_meta(meta):
                    if not value:
                        value = await self._ask_ollama_number(label or "numeric field")
                    value = self._extract_number(value)
                elif not value:
                    value = await self._ask_ollama_freetext(label or "application question")
                await target.fill(value)
                fixed += 1
            except Exception as e:
                self._log(f"Required field resolution error for '{label}': {e}")
        return fixed

    async def _get_label(self, page: Page, element) -> str:
        try:
            text = await element.evaluate(
                """el => {
                    const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                    const values = [];
                    const push = (value) => {
                        const cleaned = clean(value);
                        if (cleaned) values.push(cleaned);
                    };

                    const id = el.id || '';
                    if (id) {
                        for (const lbl of document.querySelectorAll(`label[for="${id}"]`)) {
                            push(lbl.innerText || lbl.textContent);
                        }
                    }

                    for (const ref of (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean)) {
                        const node = document.getElementById(ref);
                        if (node) push(node.innerText || node.textContent);
                    }

                    push(el.getAttribute('aria-label'));
                    push(el.getAttribute('placeholder'));

                    const group = el.closest(
                        '.jobs-easy-apply-form-section__grouping, .jobs-easy-apply-form-element, .fb-form-element, fieldset, [class*="form-element"], .fb-dash-form-element, [data-test-form-element]'
                    );
                    if (group) {
                        push(group.querySelector('legend')?.innerText);
                        push(group.querySelector('label')?.innerText);
                        push(group.querySelector('span[aria-hidden="true"]')?.innerText);
                        push(group.querySelector('[id*="label"]')?.innerText);
                        // New LinkedIn structure
                        push(group.querySelector('.artdeco-text-input--label')?.innerText);
                        push(group.querySelector('[data-test-single-line-text-form-component] label')?.innerText);
                    }

                    const bad = new Set(['search', 'next', 'review', 'submit', 'yes', 'no']);
                    return values.find(v => !bad.has(v.toLowerCase())) || values[0] || '';
                }"""
            )
            return text.lower().strip()
        except Exception:
            return ""

    def _extract_number(self, value: str) -> str:
        """Strip non-numeric text from a value, return plain decimal string."""
        import re

        m = re.search(r"\d+\.?\d*", value)
        return m.group() if m else "0"

    def _should_ask_ollama(self, label: str) -> bool:
        l = (label or "").strip().lower()
        if not l:
            return False
        return l not in {"search", "next", "review", "submit", "yes", "no", "edit"}

    async def _get_input_meta(self, element) -> dict:
        try:
            return await element.evaluate(
                """el => {
                    const validity = el.validity || {};
                    return {
                        tag: (el.tagName || '').toLowerCase(),
                        type: (el.getAttribute('type') || '').toLowerCase(),
                        inputmode: (el.getAttribute('inputmode') || '').toLowerCase(),
                        pattern: el.getAttribute('pattern') || '',
                        min: el.getAttribute('min') || '',
                        max: el.getAttribute('max') || '',
                        step: el.getAttribute('step') || '',
                        required: !!el.required,
                        value: 'value' in el ? (el.value || '') : '',
                        valid: typeof el.checkValidity === 'function' ? el.checkValidity() : true,
                        validation_message: el.validationMessage || '',
                        bad_input: !!validity.badInput,
                        step_mismatch: !!validity.stepMismatch,
                        range_underflow: !!validity.rangeUnderflow,
                        range_overflow: !!validity.rangeOverflow,
                        value_missing: !!validity.valueMissing,
                    };
                }"""
            )
        except Exception:
            return {}

    def _looks_numeric_from_meta(self, meta: dict) -> bool:
        field_type = (meta.get("type") or "").lower()
        inputmode = (meta.get("inputmode") or "").lower()
        pattern = meta.get("pattern") or ""
        validation_message = (meta.get("validation_message") or "").lower()
        return any(
            [
                field_type == "number",
                inputmode in {"numeric", "decimal"},
                bool(pattern and "\\d" in pattern),
                meta.get("bad_input"),
                meta.get("step_mismatch"),
                meta.get("range_underflow"),
                meta.get("range_overflow"),
                "number" in validation_message,
                "valid value" in validation_message,
            ]
        )

    def _answer_for_label(self, label: str, answers: dict, profile: dict) -> str:
        if not label:
            return ""
        l = label.lower()
        if l in {"search", "next", "review", "submit"}:
            return ""
        if "openai" in l or "gpt" in l or "custom model" in l:
            return "Built GPT workflows"
        if "phone" in l or "mobile" in l:
            return profile["phone"]
        if "email" in l:
            return profile["email"]
        if "linkedin" in l:
            return profile["linkedin"]
        if "github" in l or "portfolio" in l:
            return profile["github"]
        if "np" in l and "day" in l:
            return "0"
        if "notice" in l and "day" in l:
            return "0"
        if "notice" in l:
            return answers["notice_period"]
        if any(
            k in l for k in ["cctc", "ctc", "current ctc", "cost to company"]
        ) and not any(k in l for k in ["expected", "desired"]):
            return "7.3"
        if ("current" in l or "last" in l) and any(
            k in l for k in ["ctc", "salary", "compensation", "package"]
        ):
            return "7.3"  # plain number — numeric fields reject "7.3 LPA"
        if ("expected" in l or "desired" in l) and any(
            k in l for k in ["ctc", "salary", "compensation", "package"]
        ):
            return "10.8"
        if any(
            k in l
            for k in [
                "nlp",
                "natural language processing",
                "python (programming language)",
                "python programming",
                "generative ai developer",
                "generative ai",
                "work experience generative ai",
            ]
        ):
            return "2"
        if "experience" in l and "year" in l:
            return answers["years_of_experience"]
        if "city" in l or "location" in l:
            return "Aligarh, India"
        if "cover" in l:
            return answers["cover_letter_default"]
        if "gpa" in l or "cgpa" in l:
            return answers["gpa"]
        return ""

    def _radio_answer_for_label(self, label: str, answers: dict, profile: dict) -> str:
        """Return preferred visible option text for LinkedIn yes/no style questions."""
        l = (label or "").lower()
        if not l:
            return "Yes"

        if "serving notice" in l:
            return "No"
        if any(k in l for k in ["background check", "criminal check", "screening"]):
            return "Yes"
        if any(k in l for k in ["authorized", "legally", "eligible", "work in india"]):
            return answers.get("work_authorization_india", "Yes")
        if "sponsor" in l or "visa" in l:
            return answers.get("sponsorship_required", "Yes")
        if "relocat" in l:
            return answers.get("relocate", "Yes")
        if "remote" in l or "work from home" in l:
            return answers.get("remote_ok", "Yes")
        return "Yes"

    async def _select_radio_by_text(
        self, group, question: str, preferred_text: str
    ) -> bool:
        """Select a radio option within a group by matching visible option text."""
        try:
            radios = await group.locator("input[type='radio']").all()
            if not radios:
                return False

            option_entries = []
            for radio in radios:
                option = await radio.evaluate(
                    """el => {
                        const clean = value => (value || '').replace(/\\s+/g, ' ').trim();
                        const wrapper = el.closest('div._0f86e326, div._8313b98a, div');
                        let text = '';

                        if (wrapper) {
                            const siblingText = Array.from(wrapper.querySelectorAll('p, span, div'))
                                .map(node => clean(node.innerText || node.textContent))
                                .filter(Boolean)
                                .find(value => !['yes no', 'required'].includes(value.toLowerCase()));
                            if (siblingText) text = siblingText;
                        }

                        if (!text) {
                            const label = el.closest('label')
                                || (el.id ? document.querySelector(`label[for="${el.id}"]`) : null)
                                || el.parentElement;
                            if (label) {
                                text = clean(label.innerText || label.textContent);
                            }
                        }

                        return {
                            text,
                            id: el.id || '',
                        };
                    }"""
                )
                option_entries.append(option)

            options_text = [entry.get("text", "").strip() for entry in option_entries if entry.get("text")]

            self._log(f"    Radio options found: {options_text}")

            target_option = preferred_text
            if question and "Yes\nNo" in question or len(options_text) == 2:
                target_option = preferred_text

            for i, radio in enumerate(radios):
                opt_text = option_entries[i].get("text", "").strip() if i < len(option_entries) else ""
                if (
                    opt_text.lower() == target_option.lower()
                    or target_option.lower() in opt_text.lower()
                    or opt_text.lower() in target_option.lower()
                ):
                    clicked = False
                    try:
                        radio_id = option_entries[i].get("id", "")
                        if radio_id:
                            label = group.locator(f"label[for='{radio_id}']").first
                            if await label.count() > 0:
                                await label.click()
                                clicked = True
                    except Exception:
                        pass
                    if not clicked:
                        await radio.check(force=True)
                    await radio.evaluate(
                        "el => { el.dispatchEvent(new Event('change', { bubbles: true })); }"
                    )
                    self._log(f"    Selected option: '{opt_text}'")
                    return True

            try:
                first_id = option_entries[0].get("id", "") if option_entries else ""
                if first_id:
                    label = group.locator(f"label[for='{first_id}']").first
                    if await label.count() > 0:
                        await label.click()
                    else:
                        await radios[0].check(force=True)
                else:
                    await radios[0].check(force=True)
            except Exception:
                await radios[0].check(force=True)
            await radios[0].evaluate(
                "el => { el.dispatchEvent(new Event('change', { bubbles: true })); }"
            )
            self._log(f"    Clicked first option as fallback")
            return True
        except Exception as e:
            self._log(f"    Radio selection error: {e}")
            return False

    async def _handle_radio_groups(self, container, answers: dict, profile: dict):
        groups = await container.locator(
            ".jobs-easy-apply-form-section__grouping,"
            " .jobs-easy-apply-form-element,"
            " .fb-form-element,"
            " .fb-dash-form-element,"
            " fieldset,"
            " div:has(> fieldset),"
            " [data-test-form-element],"
            ".artdeco-form-element,"
            ".form-element,"
            "div[role='group'],"
            "div[class*='radio'],"
            "div[data-test-radio-button-form-component]"
        ).all()
        self._log(f"  Found {len(groups)} potential radio groups")
        for group in groups:
            try:
                if not await group.is_visible():
                    continue
                radio_count = await group.locator("input[type='radio']").count()
                self._log(f"    Group has {radio_count} radio buttons")
                if radio_count == 0:
                    continue
                checked_count = await group.locator(
                    "input[type='radio']:checked"
                ).count()
                if checked_count > 0:
                    self._log(
                        f"    Group already has {checked_count} checked, skipping"
                    )
                    continue

                group_text = await group.evaluate(
                    """group => {
                        const clean = value => (value || '').replace(/\\s+/g, ' ').trim();
                        const legend = group.querySelector('legend');
                        const label = group.querySelector('label');
                        const heading = group.querySelector('h1, h2, h3, h4, .label, .question');
                        const prompt = group.parentElement?.querySelector('p');
                        return clean(
                            prompt?.innerText
                            || legend?.innerText
                            || heading?.innerText
                            || label?.innerText
                            || group.innerText
                            || ''
                        );
                    }"""
                )
                self._log(f"    Group label: '{group_text[:50]}'")
                preferred = self._radio_answer_for_label(group_text, answers, profile)
                self._log(f"    Preferred answer: '{preferred}'")
                if await self._select_radio_by_text(group, group_text, preferred):
                    self._log(
                        f"  ✓ Radio group answered: '{group_text[:80]}' -> '{preferred}'"
                    )
                else:
                    self._log(f"  ✗ Radio group not answered: '{group_text[:80]}'")
            except Exception as e:
                self._log(f"  ✗ Radio group error: {e}")
                continue

        all_radios = await container.locator("input[type='radio']:not(:checked)").all()
        self._log(f"  Found {len(all_radios)} unchecked radio buttons")
        for radio in all_radios:
            try:
                if not await radio.is_visible():
                    continue

                wrapper = await radio.locator(
                    "xpath=ancestor::div[contains(@class, 'artdeco') or contains(@class, 'jobs') or contains(@class, 'form')][1]"
                ).first

                context_text = await wrapper.inner_text() if wrapper else ""
                context_text = context_text.replace("\n", " ").strip()[:200]

                parent_text = await radio.evaluate("""el => {
                    const label = el.closest('label');
                    if (label) {
                        const span = label.querySelector('span');
                        return span ? span.innerText.trim() : (label.innerText || '').trim();
                    }
                    const p = el.parentElement;
                    return p ? (p.innerText || p.textContent || '').trim() : '';
                }""")

                self._log(
                    f"    Unchecked radio option: '{parent_text}', context: '{context_text[:50]}...'"
                )

                answer = "Yes"
                if (
                    "not" in context_text.lower()
                    or "don't" in context_text.lower()
                    or "no " in context_text.lower()
                ):
                    answer = "No"

                if parent_text and len(parent_text) < 30:
                    if answer.lower() in parent_text.lower():
                        clicked = False
                        radio_id = await radio.get_attribute("id")
                        if radio_id:
                            label = container.locator(f"label[for='{radio_id}']").first
                            if await label.count() > 0:
                                await label.click()
                                clicked = True
                        if not clicked:
                            try:
                                await radio.check(force=True)
                            except Exception:
                                await radio.click(force=True)
                        await radio.evaluate(
                            "el => { el.dispatchEvent(new Event('change', { bubbles: true })); }"
                        )
                        self._log(f"  ✓ Clicked: '{parent_text}' (answer: {answer})")
            except Exception as e:
                self._log(f"  ✗ Radio click error: {e}")
                continue

    async def _fix_browser_invalid_inputs(
        self, container, answers: dict, profile: dict
    ) -> int:
        fixed = 0
        fields = await container.locator("input, textarea, select").all()
        for field in fields:
            try:
                if not await field.is_visible():
                    continue
                meta = await self._get_input_meta(field)
                if meta.get("valid", True):
                    continue
                label = await self._get_label(container, field)
                field_type = meta.get("type", "")
                if meta.get("tag") == "select":
                    options = await field.evaluate(
                        "el => Array.from(el.options).map(o => o.text.trim()).filter(t => t && t.toLowerCase() !== 'select an option')"
                    )
                    if not options:
                        continue
                    pick = self._answer_for_label(
                        label, answers, profile
                    ) or await self._ask_ollama_dropdown(label, options)
                    try:
                        await field.select_option(label=pick)
                    except Exception:
                        await field.select_option(index=1)
                    self._log(f"Browser-invalid select fixed: '{label}' -> '{pick}'")
                    fixed += 1
                    continue

                if field_type in {"radio", "checkbox"}:
                    continue

                if self._looks_numeric_from_meta(meta):
                    numeric_prompt = label or "numeric field"
                    constraints = []
                    for key in ("min", "max", "step"):
                        if meta.get(key):
                            constraints.append(f"{key}={meta[key]}")
                    if constraints:
                        numeric_prompt = f"{numeric_prompt} ({', '.join(constraints)})"
                    value = self._answer_for_label(label, answers, profile)
                    if not value:
                        value = await self._ask_ollama_number(numeric_prompt)
                    value = self._extract_number(value)
                    await field.fill(value)
                    self._log(
                        f"Browser-invalid numeric fixed: '{label}' | msg='{meta.get('validation_message', '')}' -> '{value}'"
                    )
                    fixed += 1
                    continue

                if meta.get("value_missing") or not meta.get("value"):
                    value = self._answer_for_label(label, answers, profile)
                    if not value:
                        value = await self._ask_ollama_freetext(label)
                    await field.fill(value)
                    self._log(f"Browser-invalid text fixed: '{label}'")
                    fixed += 1
                    continue

                value = self._answer_for_label(label, answers, profile)
                if value:
                    await field.fill(value)
                    self._log(
                        f"Browser-invalid generic fixed: '{label}' | msg='{meta.get('validation_message', '')}' -> '{value}'"
                    )
                    fixed += 1
            except Exception as e:
                self._log(f"Browser-invalid field fix error: {e}")
                continue
        return fixed

    # ── Validation error handling ─────────────────────────────────────────────

    async def _get_validation_errors(self, page: Page) -> list[dict]:
        """
        Find all visible validation error messages and their associated field labels.
        Returns list of {label, error, field_type, field_id, current_value, is_radio, radio_names}
        """
        errors = []
        try:
            error_els = await page.query_selector_all(
                ".artdeco-inline-feedback--error, "
                ".jobs-easy-apply-form-element__error-message, "
                "[class*='error-message'], "
                "[class*='inline-feedback']"
            )
            for err_el in error_els:
                if not await err_el.is_visible():
                    continue
                error_text = (await err_el.inner_text()).strip()
                if not error_text:
                    continue
                # Find the associated input/select near this error
                field_info = await err_el.evaluate("""
                    el => {
                        const group = el.closest(
                            '.jobs-easy-apply-form-section__grouping, .fb-form-element, [class*="form-element"]'
                        );
                        if (!group) return null;
                        // legend for radio groups, label for regular fields
                        const legendEl = group.querySelector('legend');
                        const labelEl  = group.querySelector('label');
                        const labelText = legendEl ? legendEl.innerText.trim()
                                        : labelEl  ? labelEl.innerText.trim()
                                        : '';
                        const input = group.querySelector(
                            'input:not([type="hidden"]):not([type="radio"]):not([type="checkbox"]), select, textarea'
                        );
                        const radioInputs = Array.from(group.querySelectorAll('input[type="radio"]'));
                        const isRadio = radioInputs.length > 0;
                        const radioNames = [...new Set(radioInputs.map(r => r.name).filter(Boolean))];
                        return {
                            label: labelText,
                            field_id: input ? (input.id || input.name || '') : '',
                            field_type: isRadio
                                ? 'radio'
                                : (input ? (input.tagName.toLowerCase() + (input.type ? ':' + input.type : '')) : ''),
                            current_value: input ? (input.value || '') : '',
                            is_radio: isRadio,
                            radio_names: radioNames,
                        };
                    }
                """)
                errors.append(
                    {
                        "error": error_text,
                        "label": field_info.get("label", "") if field_info else "",
                        "field_id": field_info.get("field_id", "")
                        if field_info
                        else "",
                        "field_type": field_info.get("field_type", "")
                        if field_info
                        else "",
                        "current_value": field_info.get("current_value", "")
                        if field_info
                        else "",
                        "is_radio": field_info.get("is_radio", False)
                        if field_info
                        else False,
                        "radio_names": field_info.get("radio_names", [])
                        if field_info
                        else [],
                    }
                )
        except Exception as e:
            self._log(f"Error while reading validation errors: {e}")
        return errors

    async def _fix_validation_errors(self, page: Page, errors: list[dict]):
        """Attempt to fix each validation error by correcting the field value."""
        for err in errors:
            label = err.get("label", "")
            error_msg = err.get("error", "").lower()
            field_id = err.get("field_id", "")
            field_type = err.get("field_type", "")
            current = err.get("current_value", "")
            is_radio = err.get("is_radio", False) or field_type == "radio"
            radio_names = err.get("radio_names", [])
            self._log(
                f"Fixing: '{label}' | error='{error_msg}' | type='{field_type}' | current='{current}'"
            )

            # ── Radio / "Please make a selection" ────────────────────────────
            if is_radio or "selection" in error_msg:
                preferred = self._radio_answer_for_label(
                    label, USER_PROFILE["form_answers"], USER_PROFILE
                )
                checked = False
                if radio_name := (radio_names[0] if radio_names else ""):
                    radio_group = page.locator(
                        f".jobs-easy-apply-form-section__grouping:has(input[type='radio'][name='{radio_name}']),"
                        f" .jobs-easy-apply-form-element:has(input[type='radio'][name='{radio_name}']),"
                        f" .fb-form-element:has(input[type='radio'][name='{radio_name}']),"
                        f" fieldset:has(input[type='radio'][name='{radio_name}'])"
                    ).first
                    if await radio_group.count() > 0:
                        try:
                            checked = await self._select_radio_by_text(
                                radio_group, label, preferred
                            )
                        except Exception as e:
                            self._log(f"  Radio group selection failed: {e}")

                if not checked:
                    all_groups = await page.query_selector_all(
                        ".jobs-easy-apply-form-section__grouping,"
                        " .jobs-easy-apply-form-element,"
                        " .fb-form-element,"
                        " fieldset"
                    )
                    label_lower = (label or "").lower()
                    for group in all_groups:
                        try:
                            if not await group.is_visible():
                                continue
                            group_text = (await group.inner_text()).lower()
                            if label_lower and label_lower not in group_text:
                                continue
                            checked = await self._select_radio_by_text(
                                group, label, preferred
                            )
                            if checked:
                                break
                        except Exception:
                            continue

                if checked:
                    self._log(f"  Radio: selected '{preferred}' for '{label}'")
                else:
                    self._log(f"  Radio: could not resolve group for '{label}'")
                continue

            # ── Locate the text/select/number field ───────────────────────────
            field = None
            if field_id:
                field = page.locator(f"#{field_id}, [name='{field_id}']").first
            if field is None or await field.count() == 0:
                field = page.get_by_label(label).first if label else None

            if field is None or (field and await field.count() == 0):
                self._log(f"  Could not locate field for '{label}' — skipping.")
                continue

            is_select = "select" in field_type

            # ── Numeric errors: "enter a decimal number", "larger than 0", etc. ──
            if (
                "decimal" in error_msg
                or "number" in error_msg
                or "larger than" in error_msg
            ):
                fixed = self._extract_number(current)
                if fixed in ("0", "") and "larger than 0" in error_msg:
                    fixed = await self._ask_ollama_number(label)
                    if fixed in ("0", ""):
                        fixed = "1"  # last resort
                self._log(f"  Fixing numeric: '{current}' → '{fixed}'")
                try:
                    await field.fill(fixed)
                except Exception as e:
                    self._log(f"  Fill failed: {e}")

            # ── Dropdown / required-selection errors ─────────────────────────
            elif (
                "valid answer" in error_msg
                or "required" in error_msg
                or "select" in error_msg
            ):
                if is_select:
                    options = await field.evaluate(
                        "el => Array.from(el.options).map(o => o.text.trim())"
                        ".filter(t => t && t.toLowerCase() !== 'select an option')"
                    )
                    if options:
                        pick = await self._ask_ollama_dropdown(label, options)
                        self._log(f"  Fixing dropdown: selected '{pick}'")
                        try:
                            await field.select_option(label=pick)
                        except Exception:
                            await field.select_option(index=1)
                else:
                    meta = await self._get_input_meta(field)
                    if self._looks_numeric_from_meta(meta):
                        numeric_prompt = label or "numeric field"
                        constraints = []
                        for key in ("min", "max", "step"):
                            if meta.get(key):
                                constraints.append(f"{key}={meta[key]}")
                        if constraints:
                            numeric_prompt = (
                                f"{numeric_prompt} ({', '.join(constraints)})"
                            )
                        answer = self._answer_for_label(
                            label, USER_PROFILE["form_answers"], USER_PROFILE
                        )
                        if not answer:
                            answer = await self._ask_ollama_number(numeric_prompt)
                        answer = self._extract_number(answer)
                        self._log(f"  Fixing numeric required field: '{answer}'")
                    else:
                        answer = await self._ask_ollama_freetext(label)
                        self._log(f"  Fixing freetext: '{answer[:40]}'")
                    try:
                        await field.fill(answer)
                    except Exception as e:
                        self._log(f"  Fill failed: {e}")

            # ── Generic fallback ──────────────────────────────────────────────
            else:
                if is_select:
                    options = await field.evaluate(
                        "el => Array.from(el.options).map(o => o.text.trim())"
                        ".filter(t => t && t.toLowerCase() !== 'select an option')"
                    )
                    if options:
                        pick = await self._ask_ollama_dropdown(label, options)
                        try:
                            await field.select_option(label=pick)
                        except Exception:
                            await field.select_option(index=1)
                else:
                    answer = await self._ask_ollama_freetext(label)
                    try:
                        await field.fill(answer)
                    except Exception as e:
                        self._log(f"  Fill failed: {e}")

    # ── Ollama helpers ────────────────────────────────────────────────────────

    async def _ask_ollama_dropdown(self, question: str, options: list[str]) -> str:
        """Ask Ollama to pick the best option from a dropdown given the question."""
        import ollama, re
        from config import OLLAMA_MODEL
        from user_profile import USER_PROFILE as P

        prompt = (
            f"You are filling a job application form for {P['name']}.\n"
            f"Candidate summary: {P['summary']}\n"
            f"Experience: {P['total_experience_years']} years. "
            f"Notice period: immediate. Current CTC: 7.3 LPA. Expected: 10.8 LPA.\n\n"
            f"Question: {question}\n"
            f"Available options:\n"
            + "\n".join(f"  {i + 1}. {o}" for i, o in enumerate(options))
            + "\n\nReply with ONLY the exact option text to select. Nothing else."
        )
        try:
            self._log(f"Ollama dropdown request: '{question[:80]}'")
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    ollama.chat,
                    model=OLLAMA_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0},
                ),
                timeout=20,
            )
            raw = resp["message"]["content"].strip()
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            # Match against actual options
            for opt in options:
                if opt.lower() in raw.lower() or raw.lower() in opt.lower():
                    return opt
            # Fallback: if Ollama returned a number, use that index
            m = re.search(r"\d+", raw)
            if m:
                idx = int(m.group()) - 1
                if 0 <= idx < len(options):
                    return options[idx]
            return options[0]  # last resort: first option
        except asyncio.TimeoutError:
            self._log(f"Ollama dropdown timed out for '{question[:80]}'")
            return options[0] if options else ""
        except Exception as e:
            self._log(f"Ollama dropdown error: {e}")
            return options[0] if options else ""

    async def _ask_ollama_number(self, question: str) -> str:
        """Ask Ollama for a numeric answer (years of experience, salary, etc.)."""
        import ollama, re
        from config import OLLAMA_MODEL
        from user_profile import USER_PROFILE as P

        prompt = (
            f"You are filling a job application form for {P['name']}.\n"
            f"Experience: {P['total_experience_years']} years total ML/AI engineering.\n"
            f"Current CTC: 7.3 LPA. Expected CTC: 10.8 LPA. Notice period: immediate (0 days).\n\n"
            f'Form field (numeric): "{question}"\n\n'
            "Reply with ONLY a single number (integer or decimal). No units, no text, just the number. "
            "If the candidate has no experience in that specific area, reply with 0."
        )
        try:
            self._log(f"Ollama number request: '{question[:80]}'")
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    ollama.chat,
                    model=OLLAMA_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0},
                ),
                timeout=20,
            )
            raw = resp["message"]["content"].strip()
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            m = re.search(r"\d+\.?\d*", raw)
            return m.group() if m else "0"
        except asyncio.TimeoutError:
            self._log(f"Ollama number timed out for '{question[:80]}'")
            return "0"
        except Exception as e:
            self._log(f"Ollama number error: {e}")
            return "0"

    async def _ask_ollama_freetext(self, question: str) -> str:
        """Ask Ollama to type a free-text answer to a custom application question."""
        import ollama, re
        from config import OLLAMA_MODEL
        from user_profile import USER_PROFILE as P

        prompt = (
            f"You are filling a job application form for {P['name']}.\n"
            f"Candidate summary: {P['summary']}\n"
            f"Skills: {', '.join(P['skills'][:15])}\n"
            f"Experience: {P['total_experience_years']} years. "
            f"Notice period: immediate. Expected CTC: 10.8 LPA.\n\n"
            f'Application form question: "{question}"\n\n'
            "Write a SHORT, professional answer (1-2 sentences max) suitable for a job application form field. "
            "Reply with ONLY the answer text. No preamble, no quotes."
        )
        try:
            self._log(f"Ollama freetext request: '{question[:80]}'")
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    ollama.chat,
                    model=OLLAMA_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.3},
                ),
                timeout=20,
            )
            raw = resp["message"]["content"].strip()
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            return raw[:500]  # cap length for form fields
        except asyncio.TimeoutError:
            self._log(f"Ollama freetext timed out for '{question[:80]}'")
            return ""
        except Exception as e:
            self._log(f"Ollama freetext error: {e}")
            return ""

    async def _ask_ollama_form_strategy(
        self,
        *,
        step: int,
        buttons: list[str],
        unresolved: list[dict],
        validation_errors: list[dict],
        has_submit: bool,
        modal_found: bool,
    ) -> str:
        """Return one of: fill, fix, advance, submit, wait, abort."""
        if not modal_found:
            return "wait"
        if validation_errors:
            return "fix"
        if unresolved:
            return "fill"
        if has_submit:
            return "submit"

        try:
            import json
            import ollama
            from config import OLLAMA_MODEL
            from user_profile import USER_PROFILE as P

            snapshot = {
                "step": step,
                "buttons": buttons[:12],
                "unresolved": [
                    (f.get("label") or f.get("kind") or "")[:120] for f in unresolved[:8]
                ],
                "validation_errors": [
                    {
                        "label": (e.get("label") or "")[:120],
                        "error": (e.get("error") or "")[:120],
                    }
                    for e in validation_errors[:8]
                ],
                "has_submit": has_submit,
            }
            prompt = (
                f"You are controlling a LinkedIn Easy Apply agent for {P['name']}.\n"
                "Choose exactly one action based on current form state.\n"
                "Rules:\n"
                "- If validation errors exist: fix\n"
                "- If required fields are unresolved: fill\n"
                "- If submit is available and no unresolved/errors: submit\n"
                "- If next/review style buttons are available and no unresolved/errors: advance\n"
                "- If the state is ambiguous: wait\n"
                "- Abort only if the form appears unrecoverably broken.\n\n"
                f"State JSON:\n{json.dumps(snapshot, ensure_ascii=True)}\n\n"
                "Reply with exactly one word: fill, fix, advance, submit, wait, or abort."
            )
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    ollama.chat,
                    model=OLLAMA_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0},
                ),
                timeout=12,
            )
            raw = resp["message"]["content"].strip().lower()
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            for action in ("fill", "fix", "advance", "submit", "wait", "abort"):
                if action in raw:
                    return action
        except Exception as e:
            self._log(f"Ollama strategy error: {e}")

        return "advance"
