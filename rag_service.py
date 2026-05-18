# rag_service.py
import requests
from duckduckgo_search import DDGS

# Keywords that suggest the query needs fresh/current information
TIME_SENSITIVE_KEYWORDS = [
    'latest', 'current', 'today', 'now', 'recent', 'new',
    'update', '2025', '2026', 'trend', 'news', 'release',
    'this year', 'this month', 'what is', 'who is',
    'explain', 'how does', 'difference between'
]

def needs_web_search(query: str) -> bool:
    """Detect if the query needs live web data"""
    q = query.lower()
    return any(kw in q for kw in TIME_SENSITIVE_KEYWORDS)
    
def web_search_context(query: str, max_results: int = 3) -> str:
    """
    Fast and safe web search with timeout protection.
    """

    results = []

    try:
        with DDGS(timeout=10) as ddgs:
            hits = ddgs.text(query, max_results=max_results)

            for hit in hits:
                results.append({
                    "title": hit.get("title", ""),
                    "source": hit.get("href", ""),
                    "content": hit.get("body", "")
                })

    except Exception as e:
        print(f"[RAG] Web search failed: {e}")
        return ""

    if not results:
        return ""

    context_lines = ["📡 Latest Web Search Results:\n"]

    for i, r in enumerate(results, 1):
        context_lines.append(
            f"[{i}] {r['title']}\n"
            f"Source: {r['source']}\n"
            f"{r['content']}\n"
        )

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
