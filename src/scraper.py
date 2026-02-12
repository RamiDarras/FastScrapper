"""Scraper engine — Nodriver (stealth) and httpx+BS4 (simple) modes."""

from __future__ import annotations

import asyncio
import json
import os
import random
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional, List, Union

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from lxml import html as lxml_html

from src.exceptions import BrowserError, ElementNotFoundError, ScrapeFailedError
from src.models import ScrapedData, SelectorConfig, SelectorType, TargetConfig

# Optional nodriver import (only needed for stealth mode)
try:
    import nodriver as uc
except ImportError:
    uc = None

# User-agent rotation pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


class ScraperEngine:
    """Core scraping logic with retry, backoff, and dual-mode extraction."""

    def __init__(self, max_retries: int = 3, retry_delay: int = 5) -> None:
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def scrape(self, target: TargetConfig) -> ScrapedData:
        """Scrape a target with automatic retries and exponential backoff."""
        start = time.monotonic()

        for attempt in range(1, self.max_retries + 1):
            try:
                if target.use_stealth:
                    result = await self._scrape_with_nodriver(target)
                else:
                    result = await self._scrape_with_httpx(target)

                duration_ms = int((time.monotonic() - start) * 1000)
                return ScrapedData(
                    target_name=target.name,
                    url=str(target.url),
                    success=True,
                    data=result,
                    scrape_duration_ms=duration_ms,
                )

            except Exception as exc:
                if attempt < self.max_retries:
                    delay = self.retry_delay * (2 ** (attempt - 1)) + random.random()
                    logger.warning(
                        "Scrape '{}' attempt {}/{} failed: {} — retrying in {:.1f}s",
                        target.name, attempt, self.max_retries, exc, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    duration_ms = int((time.monotonic() - start) * 1000)
                    logger.error(
                        "Scrape '{}' failed after {} attempts: {}",
                        target.name, self.max_retries, exc,
                    )
                    return ScrapedData(
                        target_name=target.name,
                        url=str(target.url),
                        success=False,
                        error=str(exc),
                        scrape_duration_ms=duration_ms,
                    )

        # Should never reach here, but satisfy type checker
        return ScrapedData(
            target_name=target.name,
            url=str(target.url),
            success=False,
            error="Unexpected scrape loop exit",
        )

    async def _scrape_with_nodriver(self, target: TargetConfig) -> Dict[str, Any]:
        """Stealth scrape using Nodriver (headless Chrome via CDP)."""
        if uc is None:
            raise BrowserError(
                "nodriver is not installed. Install it with: pip install nodriver"
            )

        browser_path = self._find_browser_binary(target.browser_executable_path)
        kwargs: Dict[str, Any] = {"headless": target.headless}
        if browser_path:
            kwargs["browser_executable_path"] = browser_path
            logger.debug("Using browser binary: {}", browser_path)
        logger.info("Launching browser (headless={}) for '{}'", target.headless, target.name)

        browser = await uc.start(**kwargs)
        try:
            page = await browser.get(str(target.url))

            # Wait for Cloudflare challenge to resolve (poll until gone or timeout)
            await self._wait_for_cloudflare(page, target.name, target.timeout)

            # Optional: Wait for specific selector if configured
            if target.wait_for_selector:
                await self._wait_for_selector(page, target.wait_for_selector, target.timeout)

            data: Dict[str, Any] = {}

            for sel_cfg in target.selectors:
                logger.debug("Processing selector '{}' (param='{}', type='{}')",
                             sel_cfg.selector, sel_cfg.param, sel_cfg.selector_type)

                value = await self._extract_nodriver(page, sel_cfg)
                # logger.debug("Extracted param '{}' = {!r}", sel_cfg.param, value)
                data[sel_cfg.param] = value

            return data
        finally:
            browser.stop()

    async def _wait_for_cloudflare(self, page: Any, target_name: str, timeout: int) -> None:
        """Poll the page until Cloudflare challenge disappears or timeout is reached."""
        poll_interval = 2  # seconds between checks
        elapsed = 0

        # Initial wait to let the page start loading
        await page.sleep(3)
        elapsed += 3

        while elapsed < timeout:
            source = await self._get_page_source(page)
            html_content = str(source) if source else ""
            logger.debug(
                "CF check on '{}': {}s elapsed, HTML={} chars",
                target_name, elapsed, len(html_content),
            )

            # Check if Cloudflare challenge markers are gone
            cf_markers = ("challenge-platform", "cf-challenge", "Just a moment")
            if not any(marker in html_content for marker in cf_markers):
                logger.info(
                    "Cloudflare challenge cleared on '{}' after {}s (HTML={} chars)",
                    target_name, elapsed, len(html_content),
                )
                # Extra wait for JS content to render after CF clears
                await page.sleep(2)
                return

            logger.debug("Cloudflare still active on '{}', waiting…", target_name)
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        logger.warning(
            "Cloudflare challenge did NOT clear on '{}' within {}s — "
            "proceeding anyway (extraction may fail)",
            target_name, timeout,
        )

    async def _wait_for_selector(self, page: Any, selector: str, timeout: int) -> None:
        """Poll until a specific selector is present in the DOM."""
        logger.info("Waiting for selector '{}'...", selector)
        start = time.monotonic()

        # Determine if xpath or css based on starting characters (simple heuristic)
        # or just try both or use the logic from models?
        # Actually TargetConfig.wait_for_selector is just a string.
        # Let's assume XPath if it starts with / or (, else CSS.
        is_xpath = selector.strip().startswith(("/", "("))

        while time.monotonic() - start < timeout:
            try:
                if is_xpath:
                    # Reuse our robust XPath check script
                    safe_selector = json.dumps(selector)
                    check_script = (
                        f"(() => {{ "
                        f"const result = document.evaluate({safe_selector}, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null); "
                        f"return !!result.singleNodeValue; "
                        f"}})()"
                    )
                    found = await page.evaluate(check_script, await_promise=False)
                else:
                    # CSS check
                    found = await page.evaluate(f"!!document.querySelector('{selector}')", await_promise=False)

                if found:
                    elapsed = time.monotonic() - start
                    logger.info("Selector '{}' found after {:.1f}s", selector, elapsed)
                    return

            except Exception:
                pass

            await asyncio.sleep(1) # Poll every second

        logger.warning("Timeout waiting for selector '{}' after {}s", selector, timeout)

    @staticmethod
    async def _get_page_source(page: Any) -> Optional[str]:
        """Get page HTML source, handling different nodriver API versions."""
        try:
            return await page.get_content()
        except (AttributeError, TypeError):
            pass
        try:
            return await page.content()
        except Exception:
            pass
        return None

    @staticmethod
    def _find_browser_binary(config_path: Optional[str] = None) -> Optional[str]:
        """Auto-detect Chrome/Chromium binary on the system."""
        # 1. Explicit config path
        if config_path and Path(config_path).is_file():
            return config_path

        # 2. CHROME_PATH environment variable
        env_path = os.environ.get("CHROME_PATH")
        if env_path and Path(env_path).is_file():
            return env_path

        # 3. Common binary names on PATH
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
            found = shutil.which(name)
            if found:
                return found

        # 4. Common hardcoded locations
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
            "/usr/lib/chromium/chromium",
            "/usr/lib/chromium-browser/chromium-browser",
        ]
        for path in candidates:
            if Path(path).is_file():
                return path

        return None

    async def _extract_nodriver(self, page: Any, sel_cfg: SelectorConfig) -> Any:
        """Extract value(s) from a Nodriver page using CSS or XPath."""

        # Helper to get content from a JS element handle
        async def get_element_content(node: Any) -> str:
            if sel_cfg.attribute:
                 # nodriver Element object usually has attrs property
                return (node.attrs.get(sel_cfg.attribute, "") or "").strip()

            if sel_cfg.content_mode == "inner_html":
                return await node.get_html() # usually returns outerHTML? nodriver API check needed
                # Actually nodriver Element often has .html property or get_html()
                # Let's try to use JS execution for reliability
                return await node.eval("this.innerHTML")
            elif sel_cfg.content_mode == "outer_html":
                return await node.eval("this.outerHTML")
            else: # text
                return (node.text or "").strip()

        if sel_cfg.selector_type == SelectorType.xpath:
            # Nodriver doesn't have native select_xpath in all versions,
            # but usually it's just 'select' with a different strategy or we can use custom JS.
            # However, looking at nodriver source (if known) or common usage:
            # We can use page.evaluate to run document.evaluate for robust XPath support.


            # Wrapper comment for logic
            # Let's try to simple approach: utilize nodriver's connection to CDP
            # but 'select' takes a selector.

            # If we want to return the whole element content reliably, doing it in browser context is best.

            extract_script = ""
            if sel_cfg.attribute:
                extract_script = f"el => el.getAttribute('{sel_cfg.attribute}') || ''"
            elif sel_cfg.content_mode == "inner_html":
                extract_script = "el => el.innerHTML"
            elif sel_cfg.content_mode == "outer_html":
                extract_script = "el => el.outerHTML"
            else:
                extract_script = "el => el.innerText || el.textContent || ''"

            # Flattened script with embedded selector to avoid parameter passing issues
            safe_selector = json.dumps(sel_cfg.selector)
            full_script = (
                f"(() => {{ const xpath = {safe_selector}; "
                f"const query = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null); "
                f"const results = []; "
                f"for (let i = 0; i < query.snapshotLength; i++) {{ "
                f"const el = query.snapshotItem(i); "
                f"results.push(({extract_script})(el)); "
                f"}} return results; }})()"
            )

            try:
                # Execute the script directly. await_promise=False as it is synchronous JS.
                values = await page.evaluate(full_script, await_promise=False)

                if sel_cfg.multiple:
                    return values

                if not values:
                    if sel_cfg.default is not None:
                         return sel_cfg.default
                    raise ElementNotFoundError(f"XPath '{sel_cfg.selector}' not found on {page.url}")

                return values[0]

            except Exception as exc:
                logger.warning("XPath eval failed: {}", exc)
                if sel_cfg.default is not None:
                    return sel_cfg.default
                raise ElementNotFoundError(f"XPath '{sel_cfg.selector}' failed: {exc}")

        else:
            # CSS / ID / Class
            css_selector = self._to_css(sel_cfg)

            if sel_cfg.multiple:
                elements = await page.select_all(css_selector)
                if not elements:
                    return []

                values = []
                for el in elements:
                   values.append(await get_element_content(el))
                return values
            else:
                try:
                    element = await page.select(css_selector)
                except Exception:
                    element = None

                if element is None:
                    if sel_cfg.default is not None:
                        return sel_cfg.default
                    raise ElementNotFoundError(
                        f"Element '{css_selector}' not found on {page.url}"
                    )

                return await get_element_content(element)

    async def _scrape_with_httpx(self, target: TargetConfig) -> Dict[str, Any]:
        """Simple scrape using httpx + (BS4 or lxml)."""
        headers = dict(target.headers or {})
        headers.setdefault("User-Agent", random.choice(USER_AGENTS))

        async with httpx.AsyncClient(
            timeout=target.timeout,
            follow_redirects=True,
            proxy=target.proxy,
        ) as client:
            response = await client.get(str(target.url), headers=headers)
            response.raise_for_status()

        # Decision: Use lxml for everything if XPath is used in any selector,
        # OR just use lxml always for better performance/feature set if we add dependency.
        # Since we added lxml, let's use it for XPath enabled selectors.

        # Parse tree once? Or per selector?
        # If we have mixed selectors, we might need both representations or convert.
        # Simplest solid approach:
        # If ANY selector is XPath -> use lxml tree
        # If ALL are CSS -> can use BS4 (or lxml cssselect)

        # Let's convert response to lxml tree always if we support XPath,
        # but to keep backward compatibility with BS4 'soup' logic (maybe custom BS4 parsers used?),
        # let's try to stick to what works.
        # However, BS4 doesn't do XPath.

        use_lxml_xpath = any(s.selector_type == SelectorType.xpath for s in target.selectors)

        data: Dict[str, Any] = {}

        # We might need both
        soup = None
        tree = None

        if use_lxml_xpath:
             tree = lxml_html.fromstring(response.content)

        # If we have non-xpath selectors, we might still want BS4 for ease of use
        # (unless we convert CSS to XPath which implies 'cssselect' dep).
        # We will initialize BS4 only if needed.
        if any(s.selector_type != SelectorType.xpath for s in target.selectors):
            soup = BeautifulSoup(response.text, "lxml")

        for sel_cfg in target.selectors:
            if sel_cfg.selector_type == SelectorType.xpath:
                if tree is None:
                    tree = lxml_html.fromstring(response.content)
                value = self._extract_lxml_xpath(tree, sel_cfg)
            else:
                if soup is None: # Should have been init above, but safety check
                    soup = BeautifulSoup(response.text, "lxml")
                value = self._extract_bs4(soup, sel_cfg)

            data[sel_cfg.param] = value

        return data

    def _extract_lxml_xpath(self, tree: lxml_html.HtmlElement, sel_cfg: SelectorConfig) -> Any:
        """Extract value using lxml and XPath."""
        try:
            elements = tree.xpath(sel_cfg.selector)
        except Exception as exc:
             logger.error("Invalid XPath '{}': {}", sel_cfg.selector, exc)
             if sel_cfg.default is not None:
                 return sel_cfg.default
             raise

        # xpath() returns a list of results (Elements, strings, etc.)
        if not isinstance(elements, list):
            elements = [elements]

        def get_content(el: Any) -> str:
            if isinstance(el, str): # result of string() or attributes sometimes
                return el.strip()
            if not hasattr(el, 'tag'): # some other primitive
                 return str(el)

            # It's an Element
            if sel_cfg.attribute:
                return el.get(sel_cfg.attribute, "") or ""

            if sel_cfg.content_mode == "inner_html":
                # lxml inner HTML is tricky, usually involves iterating children
                # or stringifying children.
                # simple way: (text + children_tostring)
                return (el.text or "") + "".join([lxml_html.tostring(child, encoding='unicode') for child in el])
            elif sel_cfg.content_mode == "outer_html":
                return lxml_html.tostring(el, encoding='unicode')
            else: # text
                return el.text_content().strip()

        if sel_cfg.multiple:
            return [get_content(e) for e in elements]

        if not elements:
            if sel_cfg.default is not None:
                return sel_cfg.default
            raise ElementNotFoundError(f"XPath '{sel_cfg.selector}' not found")

        return get_content(elements[0])

    def _extract_bs4(self, soup: BeautifulSoup, sel_cfg: SelectorConfig) -> Any:
        """Extract value(s) from a BeautifulSoup tree."""
        selector = sel_cfg.selector
        st = sel_cfg.selector_type

        # Helper to extract content based on mode
        def get_content(el: Any) -> str:
            if sel_cfg.attribute:
                return el.get(sel_cfg.attribute, "")

            if sel_cfg.content_mode == "inner_html":
                 # decode_contents() returns inner HTML string
                return el.decode_contents()
            elif sel_cfg.content_mode == "outer_html":
                return str(el)
            else:
                return el.get_text(strip=True)

        if sel_cfg.multiple:
            elements = self._find_all_bs4(soup, selector, st)
            return [get_content(el) for el in elements]
        else:
            element = self._find_one_bs4(soup, selector, st)
            if element is None:
                if sel_cfg.default is not None:
                    return sel_cfg.default
                raise ElementNotFoundError(
                    f"Element '{selector}' (type={st.value}) not found"
                )
            return get_content(element)

    @staticmethod
    def _find_one_bs4(soup: BeautifulSoup, selector: str, st: SelectorType) -> Any:
        if st == SelectorType.id:
            return soup.find(id=selector)
        elif st == SelectorType.class_:
            return soup.find(class_=selector)
        else:  # css (default)
            return soup.select_one(selector)

    @staticmethod
    def _find_all_bs4(soup: BeautifulSoup, selector: str, st: SelectorType) -> list:
        if st == SelectorType.id:
            return soup.find_all(id=selector)
        elif st == SelectorType.class_:
            return soup.find_all(class_=selector)
        else:  # css (default)
            return soup.select(selector)

    @staticmethod
    def _to_css(sel_cfg: SelectorConfig) -> str:
        """Convert a SelectorConfig to a CSS selector string for Nodriver."""
        if sel_cfg.selector_type == SelectorType.id:
            return f"#{sel_cfg.selector}"
        elif sel_cfg.selector_type == SelectorType.class_:
            return f".{sel_cfg.selector}"
        return sel_cfg.selector  # css regex pass-through
