import importlib
import re
import threading
from base64 import urlsafe_b64decode
from html import unescape
from urllib.parse import parse_qs, quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

TIME_SENSITIVE_KEYWORDS = [
    "latest", "current", "today", "now", "recent", "new", "newest",
    "update", "updated", "2025", "2026", "trend", "trends", "news",
    "release", "released", "this year", "this month", "yesterday",
    "tomorrow", "price", "score", "schedule", "weather",
]
SEARCH_TIMEOUT_SECONDS = 8
PAGE_TIMEOUT_SECONDS = 4
MAX_PAGE_CHARS = 1200

def needs_web_search(query: str) -> bool:
    """Detect if the query needs live web data"""
    if not query:
        return False

    q = query.lower()
    return any(kw in q for kw in TIME_SENSITIVE_KEYWORDS)


def get_ddgs_class():
    for package_name in ("duckduckgo_search", "ddgs"):
        try:
            module = importlib.import_module(package_name)
            return module.DDGS
        except Exception as exc:
            print(f"[RAG] {package_name} unavailable: {exc}")

    return None


def _clean_text(text: str) -> str:
    text = unescape(text or "")
    return re.sub(r"\s+", " ", text).strip()


def _safe_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _unwrap_bing_url(url: str) -> str:
    parsed = urlparse(url or "")
    if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/"):
        encoded = parse_qs(parsed.query).get("u", [""])[0]
        if encoded.startswith("a1"):
            encoded = encoded[2:]
        try:
            decoded = urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            return decoded.decode("utf-8", errors="ignore") or url
        except Exception:
            return url

    return url


def _scrape_page_text(url: str) -> str:
    if not _safe_url(url):
        return ""

    response = requests.get(
        url,
        timeout=(3, PAGE_TIMEOUT_SECONDS),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            )
        },
    )
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        return ""

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    return _clean_text(soup.get_text(separator=" "))[:MAX_PAGE_CHARS]


def _normalize_hit(hit: dict) -> dict:
    title = _clean_text(hit.get("title") or hit.get("heading") or "")
    source = _unwrap_bing_url(hit.get("href") or hit.get("url") or "")
    content = _clean_text(hit.get("body") or hit.get("snippet") or "")
    return {
        "title": title or source,
        "source": source,
        "content": content,
    }


def _duckduckgo_hits(DDGS, query: str, max_results: int) -> list[dict]:
    with DDGS() as ddgs:
        return list(ddgs.text(query, backend="api", max_results=max_results))


def _fallback_query(query: str) -> str:
    stripped = (query or "").strip()
    lowered = stripped.lower()
    if lowered.startswith("current "):
        return f"who is {stripped[8:]} now"
    if lowered.startswith("latest "):
        return f"{stripped[7:]} latest official"
    return stripped


def _bing_hits(query: str, max_results: int) -> list[dict]:
    response = requests.get(
        (
            f"https://www.bing.com/search?q={quote_plus(_fallback_query(query))}"
            "&mkt=en-US&cc=US&setlang=en-US"
        ),
        timeout=(3, SEARCH_TIMEOUT_SECONDS),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    hits = []
    for item in soup.select("li.b_algo"):
        link = item.find("a", href=True)
        if not link:
            continue

        snippet = item.find("p")
        hits.append(
            {
                "title": link.get_text(" ", strip=True),
                "href": link["href"],
                "body": snippet.get_text(" ", strip=True) if snippet else "",
            }
        )
        if len(hits) >= max_results:
            break

    return hits


def web_search_context(query: str, max_results: int = 3) -> str:
    """
    Search DuckDuckGo, scrape top pages, and return a clean context string.
    Falls back to snippet if scraping fails
    """
    DDGS = get_ddgs_class()
    if DDGS is None:
        print("[RAG] DuckDuckGo search package is not installed; skipping web search")
        return ""

    results = []
    search_error = {"value": None}

    def run_search():
        try:
            try:
                hits = _duckduckgo_hits(DDGS, query, max_results)
            except Exception as ddg_error:
                print(f"[RAG] DuckDuckGo failed, trying Bing fallback: {ddg_error}")
                hits = _bing_hits(query, max_results)

            for hit in hits:
                normalized = _normalize_hit(hit)

                try:
                    page_text = _scrape_page_text(normalized["source"])
                    if page_text:
                        normalized["content"] = page_text
                except Exception:
                    pass

                if normalized["content"]:
                    results.append(normalized)

        except Exception as e:
            search_error["value"] = e

    worker = threading.Thread(target=run_search, daemon=True)
    worker.start()
    worker.join(timeout=SEARCH_TIMEOUT_SECONDS)

    if worker.is_alive():
        print(f"[RAG] Web search timed out for query: {query}")
        return ""

    if search_error["value"] is not None:
        print(f"[RAG] Web search failed: {search_error['value']}")
        return ""

    if not results:
        return ""

    context_lines = ["Web Search Results (use these for current info):\n"]
    for i, r in enumerate(results, 1):
        context_lines.append(f"[{i}] {r['title']}\nSource: {r['source']}\n{r['content']}\n")

    return "\n".join(context_lines)


def build_rag_system_prompt(base_prompt: str, web_context: str, file_context: str) -> str:
    """
    Combine base system prompt + web context + file context cleanly
    """
    prompt = base_prompt

    if web_context:
        prompt += f"\n\n{web_context}"
        prompt += "\n\nUse the above web search results to answer questions about current events, trends, or recent updates."

    if file_context:
        prompt += f"\n\nUploaded Document (PRIMARY source for document questions):\n{file_context[:12000]}"

    return prompt
