# rag_service.py
import importlib
import threading

import requests
from bs4 import BeautifulSoup

# Keywords that suggest the query needs fresh/current information
TIME_SENSITIVE_KEYWORDS = [
    'latest', 'current', 'today', 'now', 'recent', 'new',
    'update', '2025', '2026', 'trend', 'news', 'release',
    'this year', 'this month'
]

def needs_web_search(query: str) -> bool:
    """Detect if the query needs live web data"""
    q = query.lower()
    return any(kw in q for kw in TIME_SENSITIVE_KEYWORDS)


def get_ddgs_class():
    try:
        return importlib.import_module("duckduckgo_search").DDGS
    except Exception as exc:
        print(f"[RAG] duckduckgo_search unavailable: {exc}")
        return None


def web_search_context(query: str, max_results: int = 3) -> str:
    """
    Search DuckDuckGo → scrape top pages → return clean context string
    Falls back to snippet if scraping fails
    """
    DDGS = get_ddgs_class()
    if DDGS is None:
        print("[RAG] duckduckgo_search is not installed; skipping web search")
        return ""

    results = []
    search_error = {"value": None}

    def run_search():
        try:
            with DDGS() as ddgs:
                hits = list(ddgs.text(query, max_results=max_results))

            for hit in hits:
                content = hit.get('body', '')  # DDG snippet as fallback

                try:
                    page = requests.get(hit['href'], timeout=5, headers={
                        'User-Agent': 'Mozilla/5.0'
                    })
                    soup = BeautifulSoup(page.content, 'html.parser')

                    # Remove noise
                    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                        tag.decompose()

                    content = soup.get_text(separator=' ', strip=True)[:1000]

                except Exception:
                    pass  # stick with DDG snippet

                results.append({
                    "title": hit.get('title', ''),
                    "source": hit.get('href', ''),
                    "content": content[:1000]
                })

        except Exception as e:
            search_error["value"] = e

    worker = threading.Thread(target=run_search, daemon=True)
    worker.start()
    worker.join(timeout=8)

    if worker.is_alive():
        print(f"[RAG] Web search timed out for query: {query}")
        return ""

    if search_error["value"] is not None:
        print(f"[RAG] Web search failed: {search_error['value']}")
        return ""

    if not results:
        return ""

    # Format as readable context block
    context_lines = ["📡 Web Search Results (use these for current info):\n"]
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
