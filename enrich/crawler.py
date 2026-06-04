"""Crawl event pages to extract text content."""

import asyncio
import hashlib
import json
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import httpx

CACHE_DIR = Path(".cache/crawled")
CACHE_TTL = 86400  # 24 hours
MAX_CONCURRENT = 10
MAX_PER_DOMAIN = 2
DOMAIN_DELAY = 0.5
TIMEOUT = 15
MAX_TEXT_LENGTH = 3000


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _read_cache(url: str) -> str | None:
    path = CACHE_DIR / f"{_cache_key(url)}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if time.time() - data.get("ts", 0) > CACHE_TTL:
        return None
    return data.get("text", "")


def _write_cache(url: str, text: str):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{_cache_key(url)}.json"
    path.write_text(json.dumps({"url": url, "text": text, "ts": time.time()}))


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TEXT_LENGTH]


def _get_domain(url: str) -> str:
    return urlparse(url).netloc


async def _fetch_one(
    client: httpx.AsyncClient,
    url: str,
    global_semaphore: asyncio.Semaphore,
    domain_semaphores: dict[str, asyncio.Semaphore],
    domain_last: dict[str, float],
    domain_lock: dict[str, asyncio.Lock],
) -> tuple[str, str]:
    """Fetch a single URL, respecting rate limits. Returns (url, text)."""
    domain = _get_domain(url)

    cached = _read_cache(url)
    if cached is not None:
        return (url, cached)

    async with global_semaphore:
        async with domain_semaphores[domain]:
            async with domain_lock[domain]:
                elapsed = time.time() - domain_last.get(domain, 0)
                if elapsed < DOMAIN_DELAY:
                    await asyncio.sleep(DOMAIN_DELAY - elapsed)
                domain_last[domain] = time.time()

            for attempt in range(2):
                try:
                    resp = await client.get(url, timeout=TIMEOUT, follow_redirects=True)
                    resp.raise_for_status()
                    text = _strip_html(resp.text)
                    _write_cache(url, text)
                    return (url, text)
                except Exception as e:
                    if attempt == 0:
                        await asyncio.sleep(1)
                    else:
                        print(f"  Warning: failed to crawl {url}: {e}")
                        _write_cache(url, "")
                        return (url, "")


async def crawl_urls(urls: list[str]) -> dict[str, str]:
    """Crawl multiple URLs concurrently with rate limiting."""
    valid_urls = [u for u in urls if u and "coming soon" not in u.lower() and u.startswith("http")]
    if not valid_urls:
        return {}

    global_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    domain_semaphores: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(MAX_PER_DOMAIN))
    domain_last: dict[str, float] = {}
    domain_lock: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    results = {}
    async with httpx.AsyncClient(
        headers={"User-Agent": "CannesLionsMCP/1.0 (event-enrichment)"},
    ) as client:
        tasks = [
            _fetch_one(client, url, global_semaphore, domain_semaphores, domain_last, domain_lock)
            for url in valid_urls
        ]
        for coro in asyncio.as_completed(tasks):
            url, text = await coro
            results[url] = text

    return results


def crawl_urls_sync(urls: list[str]) -> dict[str, str]:
    """Synchronous wrapper for crawl_urls."""
    return asyncio.run(crawl_urls(urls))
