import os
import re
import requests

SERPER_API_KEY = os.getenv("SERPER_API_KEY")

TIME_SENSITIVE_KEYWORDS = [
    "latest", "current", "today", "now", "recent",
    "news", "price", "weather", "score",
    "update", "2025", "2026", "2024"
]

COMPARISON_KEYWORDS = [
    "difference between",
    "vs",
    "versus",
    "compare",
    "comparison"
]

MODERN_PRODUCT_KEYWORDS = [
    "iphone",
    "samsung",
    "pixel",
    "macbook",
    "rtx",
    "playstation",
    "xbox"
]


def needs_web_search(query: str) -> bool:
    if not query:
        return False

    q = query.lower()

    if any(k in q for k in TIME_SENSITIVE_KEYWORDS):
        return True

    comparison = any(k in q for k in COMPARISON_KEYWORDS)
    product = any(k in q for k in MODERN_PRODUCT_KEYWORDS)

    return comparison and product


def web_search_context(query: str, max_results: int = 5) -> str:
    if not SERPER_API_KEY:
        print("[RAG] SERPER_API_KEY missing")
        return ""

    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": SERPER_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "q": query,
                "num": max_results
            },
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        organic = data.get("organic", [])

        if not organic:
            print("[RAG] No search results")
            return ""

        context_lines = [
            "Live Search Results (Most Reliable Source):\n"
        ]

        for idx, result in enumerate(organic, start=1):

            title = result.get("title", "")
            link = result.get("link", "")
            snippet = result.get("snippet", "")

            context_lines.append(
                f"[{idx}] {title}\n"
                f"Source: {link}\n"
                f"{snippet}\n"
            )

        return "\n".join(context_lines)

    except Exception as e:
        print(f"[RAG] Serper search failed: {e}")
        return ""


def build_rag_system_prompt(
    base_prompt: str,
    web_context: str,
    file_context: str
) -> str:

    prompt = base_prompt

    if web_context:
        prompt += f"\n\n{web_context}"

        prompt += (
            "\n\nUse the search results above as the primary source "
            "for current facts, comparisons, specifications, prices, "
            "recent announcements and live information."
        )

    if file_context:
        prompt += (
            "\n\nUploaded Document:\n"
            f"{file_context[:12000]}"
        )

    return prompt
