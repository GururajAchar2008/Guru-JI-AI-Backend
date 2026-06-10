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
    "tomorrow", "price", "score", "schedule", "weather", "as of ",
    "reported ", "announced ", "confirmed ", "rumored ", "leaked ",
    "expected ", "upcoming ", "future ", "last ", "next ", "this week",
    "last week", "next week",
]
COMPARISON_KEYWORDS = [
    "difference between", "vs ", " versus ", "compare ", "comparison ",
    "pros and cons", "advantages", "disadvantages", "better",
]
MODERN_PRODUCT_KEYWORDS = [
    "iphone", "ipad", "macbook", "pixel", "galaxy", "samsung", "oneplus",
    "nothing phone", "playstation", "xbox", "nintendo", "gpu", "rtx",
    "ryzen", "intel", "snapdragon", "apple watch", "airpods",
]
SEARCH_TIMEOUT_SECONDS = 12
PAGE_TIMEOUT_SECONDS = 4
MAX_PAGE_CHARS = 1200

def needs_web_search(query: str) -> bool:
    """Detect if the query needs live web data"""
    if not query:
        return False

    q = query.lower()
    if any(kw in q for kw in TIME_SENSITIVE_KEYWORDS):
        return True

    is_comparison = any(kw in q for kw in COMPARISON_KEYWORDS) or bool(
        re.search(r"\bdiff\w*\s+between\b", q)
    )
    mentions_modern_product = any(kw in q for kw in MODERN_PRODUCT_KEYWORDS)
    has_model_number = bool(re.search(r"\b\d{1,4}\b", q))
    return is_comparison and (mentions_modern_product or has_model_number)


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
    iphone_models = re.findall(r"\biphone\s+\d+\w*\b", lowered)
    is_iphone_comparison = "iphone" in lowered and (
        any(kw in lowered for kw in COMPARISON_KEYWORDS)
        or bool(re.search(r"\bdiff\w*\s+between\b", lowered))
    )
    if is_iphone_comparison:
        if len(iphone_models) >= 2:
            return f"Apple {' '.join(iphone_models)} compare specs"
        iphone_numbers = re.findall(r"\b\d{1,2}\w*\b", lowered)
        if len(iphone_numbers) >= 2:
            models = " ".join(f"iphone {number}" for number in iphone_numbers[:2])
            return f"Apple {models} compare specs"
        return (
    re.sub(
        r"\bdiff\w*\s+between\b",
        "difference between",
        stripped,
        flags=re.IGNORECASE
    )
    + " Apple official specs"
)

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
    Search DuckDuckGo (with Bing fallback), scrape top pages, and return
    a clean context string. Falls back to snippet if scraping fails.
    Returns "" on any failure — never raises.
    """
    DDGS = get_ddgs_class()
    if DDGS is None:
        print("[RAG] DuckDuckGo search package is not installed; skipping web search")
        return ""

    results = []
    search_error = {"value": None}

    def run_search():
        try:
            hits = []
            # Try DuckDuckGo with up to 2 retries before falling back to Bing
            for attempt in range(2):
                try:
                    hits = _duckduckgo_hits(DDGS, query, max_results)
                    if hits:
                        break
                except Exception as ddg_error:
                    print(f"[RAG] DuckDuckGo attempt {attempt + 1} failed: {ddg_error}")
                    if attempt == 1:
                        # Both DDG attempts failed — try Bing
                        try:
                            print("[RAG] Trying Bing fallback...")
                            hits = _bing_hits(query, max_results)
                        except Exception as bing_error:
                            print(f"[RAG] Bing fallback also failed: {bing_error}")
                            hits = []

            for hit in hits:
                try:
                    normalized = _normalize_hit(hit)
                    result_index = None
                    if normalized["content"]:
                        results.append(normalized)
                        result_index = len(results) - 1

                    # Scrape page for richer content — skip on any error
                    try:
                        page_text = _scrape_page_text(normalized["source"])
                        if page_text:
                            normalized = {**normalized, "content": page_text}
                            if result_index is None:
                                results.append(normalized)
                            else:
                                results[result_index] = normalized
                    except Exception as scrape_err:
                        print(f"[RAG] Page scrape failed for {normalized['source']}: {scrape_err}")
                except Exception as hit_err:
                    print(f"[RAG] Error processing hit: {hit_err}")

        except Exception as e:
            search_error["value"] = e

    worker = threading.Thread(target=run_search, daemon=True)
    worker.start()
    worker.join(timeout=SEARCH_TIMEOUT_SECONDS)

    if worker.is_alive():
        print(f"[RAG] Web search timed out after {SEARCH_TIMEOUT_SECONDS}s for query: {query!r}")
        # Return whatever partial results we already have
        if not results:
            return ""

    if search_error["value"] is not None:
        print(f"[RAG] Web search failed with exception: {search_error['value']}")
        return ""

    if not results:
        print(f"[RAG] No results found for query: {query!r}")
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
        prompt += (
            "\n\nUse the above web search results as the source of truth for "
            "current facts, product comparisons, specs, prices, dates, and "
            "recent updates. Do not invent details that are not supported by "
            "the search context. If the context is incomplete, say what is "
            "unclear instead of guessing."
        )

    if file_context:
        prompt += f"\n\nUploaded Document (PRIMARY source for document questions):\n{file_context[:12000]}"

    return prompt
