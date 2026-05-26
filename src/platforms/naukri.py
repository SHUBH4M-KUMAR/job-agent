"""
Naukri.com: search jobs and apply.
Updated selectors for 2025 Naukri redesign.
"""

import asyncio
import re
import ollama
from playwright.async_api import Page
from .base import BasePlatform, JobListing
from user_profile import USER_PROFILE

# jobAge=7 = posted in last 7 days
SEARCH_URL = "https://www.naukri.com/{query}-jobs?jobAge=7"


class NaukriPlatform(BasePlatform):
    name = "naukri"

    def _log(self, msg: str):
        print(f"      [NK] {msg}", flush=True)

    # ── popup / overlay helpers ───────────────────────────────────────────────

    async def _dismiss_popups(self, page: Page):
        """Close login/cookie/promo popups that Naukri injects."""
        for sel in [
            "button[data-ga-track*='close']",
            "button.cross-button",
            "span.cross-button",
            "button[class*='close']",
            "span[class*='close']",
            "[aria-label='Close']",
            ".popup .ni-button--secondary",
            "#login_Layer button.crossIcon",
            "button#skip",
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    await asyncio.sleep(0.4)
            except Exception:
                pass

    async def _dismiss_chatbot_overlay(self, page: Page) -> bool:
        """
        If the Naukri chatbot popup is visible but we don't want to answer it,
        try closing it so we can click Apply manually.
        Returns True if it was closed.
        """
        close_sels = [
            "._chatBotContainer .crossIcon",
            "._chatBotContainer button[class*='cross']",
            "._chatBotContainer button[class*='close']",
            "div[class*='chatBotContainer'] .crossIcon",
            "div[class*='chatbot'] button[aria-label='Close']",
        ]
        for sel in close_sels:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    await asyncio.sleep(0.5)
                    return True
            except Exception:
                pass
        return False

    async def _chatbot_visible(self, page: Page) -> bool:
        """
        Detect the Naukri chatbot popup.
        Prioritises the inner overlay div (which is the only part with real dimensions)
        over the outer container wrapper.
        """
        for sel in [
            "div[class*='chatbot_Overlay'].show",  # inner overlay — has actual size
            "div.chatbot_Overlay",
            "._chatBotContainer",
            "div[class*='chatBotContainer']",
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    return True
            except Exception:
                pass
        return False

    async def _chatbot_state(self, page: Page) -> dict:
        """
        Introspect the chatbot DOM with JS and return a structured snapshot:
        question text, widget type (text/radio/select), option texts, send-button presence.
        Works no matter what obfuscated class names Naukri uses.
        """
        return await page.evaluate("""
            () => {
                const container = (
                    document.querySelector('._chatBotContainer') ||
                    document.querySelector('[class*="chatBotContainer"]') ||
                    document.querySelector('[id*="chatBotContainer"]')
                );
                if (!container) return {found: false};

                // ── Question: last leaf-node text that contains '?' ──────────
                const leaves = Array.from(container.querySelectorAll('*'))
                    .filter(el =>
                        el.children.length === 0 &&
                        el.textContent.trim().length > 5 &&
                        el.textContent.trim().length < 400
                    );
                // prefer a leaf with '?'
                let questionEl = [...leaves].reverse().find(el => el.textContent.includes('?'));
                // fallback: last leaf that isn't an input/button placeholder
                if (!questionEl) {
                    questionEl = [...leaves].reverse().find(el => {
                        const tag = el.tagName.toLowerCase();
                        return tag !== 'input' && tag !== 'button' && tag !== 'textarea';
                    });
                }
                const question = questionEl ? questionEl.textContent.trim() : '';

                // ── Text input: broad selector — covers placeholder-less inputs,
                //    number inputs, contenteditable divs, and footer siblings ──
                const inputSel = (
                    'input[placeholder*="message" i], ' +
                    'input[placeholder*="type" i], ' +
                    'input[placeholder*="answer" i], ' +
                    'input[type="number"], ' +
                    'input[type="text"], ' +
                    'input:not([type="radio"]):not([type="checkbox"]):not([type="file"]):not([type="hidden"]):not([type="submit"]):not([type="button"]), ' +
                    '[contenteditable="true"], ' +
                    '[role="textbox"], ' +
                    'textarea'
                );
                let textInput = container.querySelector(inputSel);
                if (!textInput) {
                    let p = container.parentElement;
                    while (p && p !== document.body) {
                        textInput = p.querySelector(inputSel);
                        if (textInput) break;
                        p = p.parentElement;
                    }
                }

                // ── Radio inputs ─────────────────────────────────────────────
                const radios = Array.from(container.querySelectorAll('input[type="radio"]'));

                // ── Clickable option divs (Naukri renders options as divs) ───
                // Heuristic: direct children of a list-like container, each with
                // short text and no nested inputs.
                const optionDivs = Array.from(container.querySelectorAll(
                    '[class*="option" i], [class*="choice" i], [class*="answer" i]'
                )).filter(el =>
                    el.textContent.trim().length > 1 &&
                    el.textContent.trim().length < 80 &&
                    !el.querySelector('input, select, textarea')
                );

                // ── Select ───────────────────────────────────────────────────
                const select = container.querySelector('select');

                // ── Send / Save / Next button — search the whole panel,
                //    not just inside container (button is often in a sibling footer)
                const isSaveEl = el =>
                    /^\\s*(save|send|next|submit)\\s*$/i.test(el.textContent.trim()) &&
                    el.offsetParent !== null;
                let sendBtn = null;
                let scanRoot = container ? container.parentElement : document.body;
                while (scanRoot && scanRoot !== document.body) {
                    sendBtn = Array.from(scanRoot.querySelectorAll('*')).find(isSaveEl);
                    if (sendBtn) break;
                    scanRoot = scanRoot.parentElement;
                }
                if (!sendBtn) {
                    sendBtn = Array.from(document.querySelectorAll('*')).find(isSaveEl);
                }

                return {
                    found: true,
                    question,
                    hasTextInput: !!textInput,
                    textInputId: textInput ? (textInput.id || textInput.name || '') : '',
                    textInputPlaceholder: textInput ? textInput.placeholder : '',
                    radioOptions: radios.map(r => {
                        const lbl = r.labels && r.labels[0] ? r.labels[0].textContent.trim() : '';
                        const parent = r.parentElement ? r.parentElement.textContent.trim() : '';
                        return lbl || parent || r.value;
                    }).filter(t => t),
                    divOptions: optionDivs.map(el => el.textContent.trim()),
                    hasSelect: !!select,
                    selectOptions: select
                        ? Array.from(select.options).map(o => o.text.trim()).filter(t => t)
                        : [],
                    hasSendBtn: !!sendBtn,
                    sendBtnText: sendBtn ? sendBtn.textContent.trim() : '',
                };
            }
        """)

    # ── chatbot question handler ──────────────────────────────────────────────

    async def _scan_all_chatbot_widgets(self, page: Page) -> list[dict]:
        """
        Return every unanswered question-widget pair currently visible in the
        chatbot panel.  A single chatbot view can show N questions at once.
        Returns list of:
          {type: 'radio'|'text'|'select', question: str, options: [...], answered: bool}
        """
        return await page.evaluate("""
            () => {
                // Widen scope to the chatbot panel parent (widgets are often siblings)
                const container = (
                    document.querySelector('._chatBotContainer') ||
                    document.querySelector('[class*="chatBotContainer"]') ||
                    document.querySelector('[id*="chatBotContainer"]')
                );
                let scope = container ? container.parentElement : document.body;
                if (!scope || scope === document.body) scope = container || document.body;

                const isSel = 'input[type="text"], input[type="number"], ' +
                    'input:not([type="radio"]):not([type="checkbox"]):not([type="file"])' +
                    ':not([type="hidden"]):not([type="submit"]):not([type="button"]), ' +
                    '[contenteditable="true"], [role="textbox"], textarea';

                // ── Helper: nearest question text above an element ────────────
                function nearestQuestion(el) {
                    let p = el.parentElement;
                    while (p && p !== scope) {
                        const leaves = Array.from(p.querySelectorAll('*'))
                            .filter(e => e.children.length === 0 && e.textContent.includes('?')
                                     && e.textContent.trim().length < 300);
                        if (leaves.length > 0) return leaves[leaves.length - 1].textContent.trim();
                        p = p.parentElement;
                    }
                    return '';
                }

                const widgets = [];

                // ── Radio groups (group by name attr) ────────────────────────
                const allRadios = Array.from(scope.querySelectorAll('input[type="radio"]'));
                const seenNames = new Set();
                for (const r of allRadios) {
                    const name = r.name || '';
                    if (seenNames.has(name)) continue;
                    seenNames.add(name);
                    const group = allRadios.filter(x => x.name === name);
                    const already = group.some(x => x.checked);
                    const options = group.map(x => {
                        const lbl = x.labels?.[0]?.textContent.trim()
                                 || x.parentElement?.textContent.trim()
                                 || x.value;
                        return lbl;
                    }).filter(t => t && t.length < 80);
                    widgets.push({
                        type: 'radio',
                        name,
                        question: nearestQuestion(group[0]),
                        options,
                        answered: already,
                    });
                }

                // ── Text / number inputs ──────────────────────────────────────
                const textEls = Array.from(scope.querySelectorAll(isSel))
                    .filter(el => el.offsetParent !== null);
                for (const inp of textEls) {
                    const val = inp.value || inp.textContent || '';
                    widgets.push({
                        type: 'text',
                        question: nearestQuestion(inp),
                        placeholder: inp.placeholder || '',
                        id: inp.id || '',
                        name: inp.name || '',
                        answered: val.trim().length > 0,
                    });
                }

                // ── Selects ───────────────────────────────────────────────────
                const selectEls = Array.from(scope.querySelectorAll('select'))
                    .filter(el => el.offsetParent !== null);
                for (const sel of selectEls) {
                    const opts = Array.from(sel.options).map(o => o.text.trim()).filter(t => t);
                    widgets.push({
                        type: 'select',
                        question: nearestQuestion(sel),
                        options: opts,
                        answered: sel.value !== '' && sel.selectedIndex > 0,
                    });
                }

                return widgets;
            }
        """)

    async def _handle_chatbot_questions(self, page: Page):
        """
        Answer ALL visible Naukri chatbot questions per round, then click Save.
        Repeats until chatbot closes or no progress after 3 rounds.
        """
        prev_sig = ""
        stuck = 0

        for step in range(15):
            await asyncio.sleep(1.5)

            if not await self._chatbot_visible(page):
                self._log("Chatbot no longer visible — done answering.")
                break

            widgets = await self._scan_all_chatbot_widgets(page)
            unanswered = [w for w in widgets if not w.get("answered")]

            # Build a signature of the current state for stuck detection
            sig = "|".join(w.get("question", "")[:30] for w in widgets)
            if sig == prev_sig and sig:
                stuck += 1
                if stuck >= 3:
                    self._log("  No progress after 3 rounds — breaking.")
                    break
            else:
                stuck = 0
                prev_sig = sig

            self._log(
                f"  Round {step + 1}: {len(widgets)} widget(s), {len(unanswered)} unanswered"
            )

            # ── Answer every unanswered widget ────────────────────────────────
            for w in unanswered:
                wtype = w.get("type")
                question = w.get("question", "")
                options = w.get("options", [])

                if wtype == "radio" and options:
                    target = await self._best_option(question, options)
                    radio_name = w.get("name", "")
                    clicked = await page.evaluate(f"""
                        () => {{
                            const target = {repr(target.lower())};
                            const name   = {repr(radio_name)};
                            const radios = Array.from(document.querySelectorAll(
                                name ? `input[type='radio'][name='${{name}}']` : 'input[type="radio"]'
                            ));
                            for (const r of radios) {{
                                const lbl = (r.labels?.[0]?.textContent || r.parentElement?.textContent || '').trim().toLowerCase();
                                if (lbl.includes(target) || target.includes(lbl)) {{
                                    r.click(); return lbl;
                                }}
                            }}
                            // fallback: first non-skip
                            const fb = radios.find(r => !/skip/i.test(r.parentElement?.textContent || ''));
                            if (fb) {{ fb.click(); return 'fallback'; }}
                            return false;
                        }}
                    """)
                    self._log(
                        f"    Radio '{question[:40]}' → '{target}' (clicked={clicked})"
                    )

                elif wtype == "text":
                    answer = self._quick_text_answer(
                        question or w.get("placeholder", "")
                    )
                    if not answer:
                        answer = await self._ask_ollama_text(
                            question or w.get("placeholder", "")
                        )
                    if answer:
                        filled = False
                        # Prefer Playwright .fill() — it simulates real keystrokes and
                        # properly triggers React's synthetic onChange, unlike direct
                        # inp.value assignment which only updates the DOM but not
                        # React's internal fiber state.
                        inp_id = w.get("id", "")
                        inp_name = w.get("name", "")
                        inp_ph = w.get("placeholder", "")
                        loc = None
                        if inp_id:
                            loc = page.locator(f"#{inp_id}").first
                        elif inp_name:
                            loc = page.locator(f'[name="{inp_name}"]').first
                        elif inp_ph:
                            loc = page.locator(f'[placeholder="{inp_ph}"]').first

                        if loc:
                            try:
                                if await loc.count() > 0 and await loc.is_visible():
                                    await loc.click()
                                    await loc.fill(answer)
                                    filled = True
                            except Exception:
                                pass

                        if not filled:
                            # Fallback: React-compatible native value setter via JS
                            filled = await page.evaluate(f"""
                                () => {{
                                    const isSel = 'input[type="text"], input[type="number"], ' +
                                        'input:not([type="radio"]):not([type="checkbox"])' +
                                        ':not([type="file"]):not([type="hidden"])' +
                                        ':not([type="submit"]):not([type="button"]), ' +
                                        '[contenteditable="true"], [role="textbox"], textarea';
                                    const inputs = Array.from(document.querySelectorAll(isSel))
                                        .filter(el => el.offsetParent !== null
                                                   && !(el.value || el.textContent).trim());
                                    if (!inputs.length) return false;
                                    const inp = inputs[0];
                                    inp.focus();
                                    if (inp.isContentEditable) {{
                                        inp.textContent = {repr(answer)};
                                        inp.dispatchEvent(new Event('input',  {{bubbles: true}}));
                                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                                    }} else {{
                                        // Use the native prototype setter so React's
                                        // synthetic event system sees a real value change.
                                        const setter = Object.getOwnPropertyDescriptor(
                                            window.HTMLInputElement.prototype, 'value'
                                        ).set;
                                        setter.call(inp, {repr(answer)});
                                        inp.dispatchEvent(new Event('input',  {{bubbles: true}}));
                                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                                    }}
                                    return true;
                                }}
                            """)

                        self._log(
                            f"    Text  '{question[:40]}' → '{answer[:30]}' (filled={filled})"
                        )

                elif wtype == "select" and options:
                    pick = await self._ask_ollama_option(question, options)
                    sel_el = page.locator(
                        "._chatBotContainer select, [class*='chatBotContainer'] select"
                    ).first
                    if await sel_el.count() > 0:
                        try:
                            await sel_el.select_option(label=pick)
                        except Exception:
                            await sel_el.select_option(index=1)
                    self._log(f"    Select '{question[:40]}' → '{pick}'")

            # Wait for UI to register all answers before clicking Save
            await asyncio.sleep(2)

            # ── Click Save / Send / Next ──────────────────────────────────────
            sent = await page.evaluate("""
                () => {
                    const isSave = el =>
                        /^\\s*(save|send|next|submit)\\s*$/i.test(el.textContent.trim()) &&
                        el.offsetParent !== null;
                    const container = (
                        document.querySelector('._chatBotContainer') ||
                        document.querySelector('[class*="chatBotContainer"]') ||
                        document.querySelector('[id*="chatBotContainer"]')
                    );
                    let root = container ? container.parentElement : null;
                    while (root && root !== document.body) {
                        const btn = Array.from(root.querySelectorAll('*')).find(isSave);
                        if (btn) { btn.click(); return btn.textContent.trim(); }
                        root = root.parentElement;
                    }
                    const btn = Array.from(document.querySelectorAll('*')).find(isSave);
                    if (btn) { btn.click(); return btn.textContent.trim(); }
                    return false;
                }
            """)
            if sent:
                self._log(f"  Clicked: '{sent}'")
            else:
                self._log("  No Save button — trying Enter.")
                await page.keyboard.press("Enter")
            await asyncio.sleep(2.5)

    async def _best_option(self, question: str, options: list[str]) -> str:
        """
        Pick the best option for a chatbot question using profile data first,
        falling back to Ollama.
        """
        q = question.lower()
        profile = USER_PROFILE

        # Hard-coded fast answers for common questions
        if "notice" in q:
            for opt in options:
                if "15" in opt or (
                    "less" in opt.lower() and "month" not in opt.lower()
                ):
                    return opt
            return options[0]

        if "experience" in q and "year" in q:
            for opt in options:
                if re.search(r"[12]\s*(year|yr)", opt, re.I):
                    return opt

        if "salary" in q or "ctc" in q or "compensation" in q:
            for opt in options:
                if re.search(r"(10|11|12|13|14|15)", opt):
                    return opt

        if "relocat" in q or "remote" in q or "work from home" in q:
            for opt in options:
                if opt.lower() in ("yes", "open to remote", "open to relocation"):
                    return opt
            for opt in options:
                if "yes" in opt.lower():
                    return opt

        # Ask Ollama
        return await self._ask_ollama_option(question, options)

    def _quick_text_answer(self, question: str) -> str:
        """
        Return a profile-based answer for common text questions without Ollama.
        Returns '' if the question is not recognised.
        """
        q = question.lower()
        P = USER_PROFILE
        if "current" in q and any(
            k in q for k in ("ctc", "salary", "fixed", "lpa", "compensation")
        ):
            return "7.3"
        if ("expected" in q or "desired" in q) and any(
            k in q for k in ("ctc", "salary", "lpa", "compensation")
        ):
            return "10.8"
        if "notice" in q:
            return "0"
        if "experience" in q and any(k in q for k in ("year", "total", "overall")):
            return str(P.get("total_experience_years", "2"))
        if "phone" in q or "mobile" in q or "contact" in q:
            return P["phone"]
        if "email" in q:
            return P["email"]
        if "location" in q or "city" in q:
            return "Aligarh, India"
        if "linkedin" in q:
            return P["linkedin"]
        if "github" in q or "portfolio" in q:
            return P["github"]
        return ""

    # ── Ollama helpers ────────────────────────────────────────────────────────

    async def _ask_ollama_option(self, question: str, options: list[str]) -> str:
        from config import OLLAMA_MODEL

        P = USER_PROFILE
        opts_text = "\n".join(f"  {i + 1}. {o}" for i, o in enumerate(options))
        prompt = (
            f"Job application form for {P['name']}.\n"
            f"Experience: {P['total_experience_years']} yrs ML/AI. "
            f"Notice: immediate (0 days). Current CTC: 7.3 LPA. Expected: 10.8 LPA.\n\n"
            f"Question: {question}\nOptions:\n{opts_text}\n\n"
            "Reply with ONLY the exact option text to select. Nothing else."
        )
        try:
            resp = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0},
            )
            raw = re.sub(
                r"<think>.*?</think>", "", resp["message"]["content"], flags=re.DOTALL
            ).strip()
            for opt in options:
                if opt.lower() in raw.lower() or raw.lower() in opt.lower():
                    return opt
            m = re.search(r"\d+", raw)
            if m:
                idx = int(m.group()) - 1
                if 0 <= idx < len(options):
                    return options[idx]
            return options[0]
        except Exception:
            return options[0]

    async def _ask_ollama_text(self, question: str) -> str:
        from config import OLLAMA_MODEL

        P = USER_PROFILE
        prompt = (
            f"Job application for {P['name']}. "
            f"Experience: {P['total_experience_years']} yrs ML/AI. "
            f"Notice: immediate. Expected CTC: 10.8 LPA.\n\n"
            f'Question: "{question}"\n\n'
            "Give a SHORT professional answer (1-2 sentences). No preamble, no quotes."
        )
        try:
            resp = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.3},
            )
            raw = re.sub(
                r"<think>.*?</think>", "", resp["message"]["content"], flags=re.DOTALL
            ).strip()
            return raw[:300]
        except Exception:
            return ""

    # ── search ────────────────────────────────────────────────────────────────

    async def search(self, page: Page, query: str) -> list[JobListing]:
        slug = query.lower().replace(" ", "-")
        url = SEARCH_URL.format(query=slug)
        await page.goto(url, timeout=30_000)
        await asyncio.sleep(3)

        await self._dismiss_popups(page)

        # Scroll to trigger lazy-loaded cards
        for _ in range(4):
            await page.keyboard.press("End")
            await asyncio.sleep(1.2)

        # Wait for any card container to appear
        for sel in [
            "article[data-job-id]",
            "div.srp-jobtuple-wrapper",
            "article.jobTuple",
            "div.list-container",
        ]:
            try:
                await page.wait_for_selector(sel, timeout=5_000)
                break
            except Exception:
                continue

        # Try selectors from most specific to most generic
        cards = []
        for card_sel in [
            "article[data-job-id]",
            "div.srp-jobtuple-wrapper",
            "article.jobTuple",
            "div[data-job-id]",
            "div[class*='srp-jobtuple']",
            "article[class*='jobTuple']",
        ]:
            cards = await page.query_selector_all(card_sel)
            if cards:
                break

        if not cards:
            page_title = await page.title()
            card_count = await page.evaluate(
                "() => document.querySelectorAll('[data-job-id], article, .jobTuple').length"
            )
            print(
                f"[Naukri] No cards found for '{query}' — "
                f"page='{page_title}' | JS count={card_count}"
            )
            return []

        jobs: list[JobListing] = []
        for card in cards[:25]:
            try:
                job_id = (
                    await card.get_attribute("data-job-id")
                    or await card.get_attribute("id")
                    or ""
                )

                title_el = None
                for t_sel in [
                    "a.title",
                    "div.row1 a",
                    ".row1 a",
                    "h2 a",
                    "a[class*='title']",
                ]:
                    title_el = await card.query_selector(t_sel)
                    if title_el:
                        break

                company_el = None
                for c_sel in [
                    "a.comp-name",
                    ".comp-name",
                    "a[class*='comp']",
                    ".row2 a",
                ]:
                    company_el = await card.query_selector(c_sel)
                    if company_el:
                        break

                location_el = None
                for l_sel in [
                    "span.locWdth",
                    "li.location",
                    ".locWdth",
                    "span[class*='loc']",
                ]:
                    location_el = await card.query_selector(l_sel)
                    if location_el:
                        break

                salary_el = None
                for s_sel in ["span.sal", "li.salary", ".sal", "span[class*='sal']"]:
                    salary_el = await card.query_selector(s_sel)
                    if salary_el:
                        break

                exp_el = None
                for e_sel in [
                    "span.expwdth",
                    "li.experience",
                    ".expwdth",
                    "span[class*='exp']",
                    "li[class*='exp']",
                    "span[title*='year']",
                ]:
                    exp_el = await card.query_selector(e_sel)
                    if exp_el:
                        break

                title = (await title_el.inner_text()).strip() if title_el else ""
                company = (await company_el.inner_text()).strip() if company_el else ""
                location = (
                    (await location_el.inner_text()).strip() if location_el else ""
                )
                salary = (await salary_el.inner_text()).strip() if salary_el else ""
                exp_text = (await exp_el.inner_text()).strip() if exp_el else ""
                href = await title_el.get_attribute("href") if title_el else ""

                if not job_id and href:
                    m = re.search(r"-(\d+)\?", href) or re.search(
                        r"/(\d+)(?:\?|$)", href
                    )
                    if m:
                        job_id = m.group(1)
                if not job_id:
                    job_id = re.sub(r"\W+", "_", (title + company)[:40])

                if not title:
                    continue

                # Skip jobs that require more experience than Shubham has (+2 yr buffer).
                # exp_text is typically "2-5 Yrs" or "6-11 Yrs".
                if exp_text:
                    m = re.search(r"(\d+)\s*[-–]\s*(\d+)", exp_text)
                    if m:
                        min_exp = int(m.group(1))
                        if min_exp > USER_PROFILE["total_experience_years"] + 2:
                            continue  # too senior

                jobs.append(
                    JobListing(
                        job_id=job_id,
                        platform=self.name,
                        title=title,
                        company=company,
                        location=location,
                        url=href or "",
                        salary=salary,
                        easy_apply=True,
                    )
                )
            except Exception:
                continue

        return jobs

    # ── apply ─────────────────────────────────────────────────────────────────

    async def apply(
        self, page: Page, job: JobListing, resume_path: str
    ) -> tuple[bool, str]:
        try:
            if not job.url:
                return False, "No URL"

            self._log(f"Navigating to: {job.url}")
            await page.goto(job.url, timeout=30_000)
            await asyncio.sleep(2)
            await self._captcha_pause(page)
            await self._dismiss_popups(page)

            # Extract description
            for d_sel in [
                "#job-desc",
                ".job-desc",
                ".jobDescriptionText",
                "section.job-desc",
            ]:
                el = page.locator(d_sel).first
                if await el.count() > 0:
                    job.description = (await el.inner_text()).strip()
                    break

            # If chatbot is already open before clicking Apply, answer it first —
            # it may be the application flow itself.
            if await self._chatbot_visible(page):
                self._log("Chatbot open on page load — answering before Apply click.")
                await self._handle_chatbot_questions(page)
                await asyncio.sleep(2)
                if await self._verify_success(page):
                    return True, ""

            # Use JS click to bypass chatbot_Overlay that intercepts Playwright events
            self._log("Clicking Apply via JS (bypasses overlay)...")
            clicked = await page.evaluate("""
                () => {
                    const sels = [
                        '#apply-button',
                        'button.apply-button',
                        'button[class*="apply-button"]',
                        'a#applyButton',
                        'button[class*="applyBtn"]',
                    ];
                    for (const s of sels) {
                        const btn = document.querySelector(s);
                        if (btn) { btn.click(); return btn.textContent.trim(); }
                    }
                    return null;
                }
            """)

            if not clicked:
                self._log("Apply button not found via JS.")
                return False, "Apply button not found"

            self._log(f"JS clicked: '{clicked}' — waiting for response...")
            await asyncio.sleep(4)  # chatbot needs ~3 s to render

            # Check for immediate navigation to success page
            if await self._verify_success(page):
                self._log("Navigated to saveApply — application submitted.")
                return True, ""

            # Handle chatbot popup that appears after clicking Apply
            if await self._chatbot_visible(page):
                self._log("Chatbot popup appeared — answering questions...")
                await self._handle_chatbot_questions(page)
                await asyncio.sleep(2)
                if await self._verify_success(page):
                    self._log("Reached saveApply after chatbot — applied.")
                    return True, ""
                # Chatbot was involved but didn't reach success — stop here.
                # Do NOT fall through to _fill_apply_flow; it would interact
                # with chatbot elements (upload file, click Apply) and break things.
                return False, "Chatbot questions incomplete or answer rejected"

            # No chatbot — try a regular multi-step form page
            ok = await self._fill_apply_flow(page, resume_path)
            if ok or await self._verify_success(page):
                return True, ""

            return False, "Form did not reach Submit"

        except Exception as e:
            # Even if Playwright throws on the click, the page may have navigated
            # to the success URL — check before reporting failure.
            try:
                if await self._verify_success(page):
                    self._log("Exception occurred but saveApply confirmed — applied.")
                    return True, ""
            except Exception:
                pass
            self._log(f"Exception: {e}")
            return False, f"Exception: {e}"

    def _on_success_page(self, page: Page) -> bool:
        """True when Naukri has navigated to its post-apply confirmation URL."""
        try:
            url = page.url
            return "saveApply" in url or "myapply" in url
        except Exception:
            return False

    async def _verify_success(self, page: Page) -> bool:
        """
        Checks the saveApply page text for real success vs the
        'incomplete information' rejection that still uses the same URL.
        """
        if not self._on_success_page(page):
            return False
        try:
            text = await page.evaluate("() => document.body.innerText.toLowerCase()")
            # Naukri rejection message on saveApply page
            rejection_phrases = [
                "not accepted",
                "incomplete information",
                "please answer all mandatory",
                "application was not accepted",
            ]
            for phrase in rejection_phrases:
                if phrase in text:
                    self._log(f"saveApply page shows rejection: '{phrase}'")
                    return False
            return True
        except Exception:
            return True  # can't read page — assume success if URL matched

    # ── multi-step form filler (fallback for ATS-style pages) ────────────────

    async def _fill_apply_flow(self, page: Page, resume_path: str) -> bool:
        profile = USER_PROFILE
        answers = profile["form_answers"]

        for _ in range(8):
            await asyncio.sleep(1.5)
            await self._captcha_pause(page)

            if self._on_success_page(page):
                return True

            # Resume upload — skip any file inputs inside the chatbot container
            for up_el in await page.query_selector_all("input[type='file']"):
                in_chatbot = await up_el.evaluate(
                    "el => !!el.closest('._chatBotContainer, [class*=\"chatBotContainer\"]')"
                )
                if not in_chatbot and resume_path:
                    await up_el.set_input_files(resume_path)
                    await asyncio.sleep(1)
                    break

            # Fill visible text/number/tel inputs and textareas
            inputs = await page.query_selector_all(
                "input[type='text']:not([type='hidden']), "
                "input[type='number'], input[type='tel'], textarea"
            )
            for inp in inputs:
                if not await inp.is_visible():
                    continue
                current = await inp.input_value()
                if current:
                    continue
                ph = (await inp.get_attribute("placeholder") or "").lower()
                name = (await inp.get_attribute("name") or "").lower()
                label = ph or name
                value = self._map_field(label, answers, profile)
                if value:
                    await inp.fill(value)

            # Submit / Next — use force=True so chatbot overlay can't block the click
            submitted = False
            for s_sel in [
                "button[type='submit']",
                "button:has-text('Submit')",
                "input[type='submit']",
            ]:
                btn = page.locator(s_sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(force=True)
                    await asyncio.sleep(2)
                    for c_sel in [
                        "button:has-text('Yes')",
                        "button:has-text('Confirm')",
                        "button:has-text('OK')",
                    ]:
                        c_btn = page.locator(c_sel).first
                        if await c_btn.count() > 0:
                            await c_btn.click(force=True)
                    submitted = True
                    break

            if submitted:
                return True

            for n_sel in [
                "button:has-text('Next')",
                "button:has-text('Continue')",
                "a:has-text('Next')",
            ]:
                n_btn = page.locator(n_sel).first
                if await n_btn.count() > 0 and await n_btn.is_visible():
                    await n_btn.click(force=True)
                    break
            else:
                break

        return self._on_success_page(
            page
        )  # sync URL check — close enough for form filler

    def _map_field(self, label: str, answers: dict, profile: dict) -> str:
        l = label.lower()
        if "phone" in l or "mobile" in l:
            return profile["phone"]
        if "email" in l:
            return profile["email"]
        if "notice" in l:
            return "0"
        if ("current" in l or "last" in l) and any(
            k in l for k in ("ctc", "salary", "lpa", "compensation")
        ):
            return "7.3"
        if ("expected" in l or "desired" in l) and any(
            k in l for k in ("ctc", "salary", "lpa", "compensation")
        ):
            return "10.8"
        if "experience" in l:
            return "2"
        if "city" in l or "location" in l:
            return "Aligarh"
        return ""
