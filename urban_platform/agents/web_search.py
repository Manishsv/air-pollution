"""Provider-agnostic web search for AirOS agents.

Mirrors the LLM provider pattern — configure via .env, switch providers without
code changes.  If no provider is configured the search_web tool is silently
omitted from the agent's tool list and no search calls are made.

Environment variables
---------------------
WEB_SEARCH_PROVIDER  — none | duckduckgo | tavily | brave | serpapi
                       Default: none (search disabled)
WEB_SEARCH_API_KEY   — API key for the configured provider.
                       Not required for duckduckgo.

Supported providers
-------------------
none          Search disabled.  No imports, no network calls, no errors.

duckduckgo    No API key required.  Uses the duckduckgo-search package
              (pip install duckduckgo-search).  Rate-limited by DDG but
              sufficient for occasional agent use.  News-only mode with
              a 1-month recency filter.

tavily        Set WEB_SEARCH_API_KEY=tvly-...  (tavily.com)
              pip install tavily-python
              Returns clean AI-ready snippets.  Best quality for agent use.

brave         Set WEB_SEARCH_API_KEY=BSA...  (brave.com/search/api)
              No extra package — uses requests (already a dep).
              Brave Search API free tier: 2000 queries/month.

serpapi       Set WEB_SEARCH_API_KEY=...  (serpapi.com)
              pip install google-search-results
              Wraps Google, Bing, etc.  100 free searches/month.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDER_PRESETS: dict[str, dict] = {
    "none": {
        "label":        "Disabled",
        "requires_key": False,
        "notes":        "Web search disabled. Set WEB_SEARCH_PROVIDER to enable.",
    },
    "duckduckgo": {
        "label":        "DuckDuckGo (no API key required)",
        "requires_key": False,
        "install":      "pip install duckduckgo-search",
        "notes":        "Free, no key needed. Unofficial API — may rate-limit under heavy use.",
    },
    "tavily": {
        "label":        "Tavily",
        "requires_key": True,
        "key_env":      "WEB_SEARCH_API_KEY",
        "install":      "pip install tavily-python",
        "notes":        "Best quality for agent use. See tavily.com for an API key.",
    },
    "brave": {
        "label":        "Brave Search",
        "requires_key": True,
        "key_env":      "WEB_SEARCH_API_KEY",
        "install":      "No extra package (uses requests)",
        "notes":        "2000 free queries/month. See brave.com/search/api.",
    },
    "serpapi": {
        "label":        "SerpAPI",
        "requires_key": True,
        "key_env":      "WEB_SEARCH_API_KEY",
        "install":      "pip install google-search-results",
        "notes":        "100 free queries/month. Wraps Google/Bing. See serpapi.com.",
    },
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class WebSearchConfig:
    provider: str       = "none"
    api_key:  str | None = None
    enabled:  bool      = False

    @property
    def label(self) -> str:
        return PROVIDER_PRESETS.get(self.provider, {}).get("label", self.provider)


def load_web_search_config() -> WebSearchConfig:
    """Read WEB_SEARCH_PROVIDER / WEB_SEARCH_API_KEY from environment."""
    provider = os.getenv("WEB_SEARCH_PROVIDER", "none").strip().lower()

    if provider not in PROVIDER_PRESETS:
        logger.warning(
            "Unknown WEB_SEARCH_PROVIDER=%r — disabling web search. "
            "Valid values: %s", provider, ", ".join(PROVIDER_PRESETS),
        )
        provider = "none"

    if provider == "none":
        return WebSearchConfig(provider="none", enabled=False)

    preset = PROVIDER_PRESETS[provider]
    api_key: str | None = None

    if preset.get("requires_key"):
        api_key = os.getenv("WEB_SEARCH_API_KEY", "").strip() or None
        if not api_key:
            logger.warning(
                "WEB_SEARCH_PROVIDER=%r requires WEB_SEARCH_API_KEY — "
                "disabling web search.", provider,
            )
            return WebSearchConfig(provider=provider, enabled=False)

    return WebSearchConfig(provider=provider, api_key=api_key, enabled=True)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    title:          str
    url:            str
    snippet:        str
    published_date: str | None = None
    source:         str | None = None

    def to_dict(self) -> dict:
        return {
            "title":          self.title,
            "url":            self.url,
            "snippet":        self.snippet,
            "published_date": self.published_date,
            "source":         self.source,
        }


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

def _search_duckduckgo(query: str, max_results: int) -> list[SearchResult]:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        raise RuntimeError(
            "duckduckgo-search not installed. Run: pip install duckduckgo-search"
        )
    results = []
    # Use news search with 1-month recency window
    with DDGS() as ddgs:
        for r in ddgs.news(query, max_results=max_results, timelimit="m"):
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("body", ""),
                published_date=r.get("date"),
                source=r.get("source"),
            ))
    return results


def _search_tavily(query: str, max_results: int, api_key: str) -> list[SearchResult]:
    try:
        from tavily import TavilyClient
    except ImportError:
        raise RuntimeError(
            "tavily-python not installed. Run: pip install tavily-python"
        )
    client = TavilyClient(api_key=api_key)
    resp = client.search(
        query,
        max_results=max_results,
        search_depth="basic",
        include_answer=False,
    )
    results = []
    for r in resp.get("results", []):
        results.append(SearchResult(
            title=r.get("title", ""),
            url=r.get("url", ""),
            snippet=r.get("content", ""),
            published_date=r.get("published_date"),
            source=r.get("url", "").split("/")[2] if r.get("url") else None,
        ))
    return results


def _search_brave(query: str, max_results: int, api_key: str) -> list[SearchResult]:
    import requests
    resp = requests.get(
        "https://api.search.brave.com/res/v1/news/search",
        params={"q": query, "count": max_results, "freshness": "pm"},
        headers={
            "Accept":                "application/json",
            "Accept-Encoding":       "gzip",
            "X-Subscription-Token":  api_key,
        },
        timeout=10,
    )
    resp.raise_for_status()
    results = []
    for r in resp.json().get("results", []):
        results.append(SearchResult(
            title=r.get("title", ""),
            url=r.get("url", ""),
            snippet=r.get("description", ""),
            published_date=r.get("age"),
            source=r.get("meta_url", {}).get("hostname"),
        ))
    return results


def _search_serpapi(query: str, max_results: int, api_key: str) -> list[SearchResult]:
    try:
        from serpapi import GoogleSearch
    except ImportError:
        raise RuntimeError(
            "google-search-results not installed. Run: pip install google-search-results"
        )
    search = GoogleSearch({
        "q":       query,
        "tbm":     "nws",          # news results
        "num":     max_results,
        "api_key": api_key,
        "tbs":     "qdr:m",        # past month
    })
    results = []
    for r in search.get_dict().get("news_results", []):
        results.append(SearchResult(
            title=r.get("title", ""),
            url=r.get("link", ""),
            snippet=r.get("snippet", ""),
            published_date=r.get("date"),
            source=r.get("source", {}).get("name") if isinstance(r.get("source"), dict) else r.get("source"),
        ))
    return results


# ---------------------------------------------------------------------------
# Public search function
# ---------------------------------------------------------------------------

def search(
    query: str,
    *,
    max_results: int = 3,
    config: WebSearchConfig | None = None,
) -> list[SearchResult]:
    """Execute a web search and return a list of SearchResult objects.

    Returns an empty list (never raises) if search is disabled or fails,
    so callers don't need error handling.
    """
    if config is None:
        config = load_web_search_config()

    if not config.enabled:
        return []

    try:
        if config.provider == "duckduckgo":
            return _search_duckduckgo(query, max_results)
        if config.provider == "tavily":
            return _search_tavily(query, max_results, config.api_key)
        if config.provider == "brave":
            return _search_brave(query, max_results, config.api_key)
        if config.provider == "serpapi":
            return _search_serpapi(query, max_results, config.api_key)
    except Exception as exc:
        logger.warning("Web search failed [%s]: %s", config.provider, exc)

    return []


def format_results_for_llm(results: list[SearchResult]) -> str:
    """Format search results as a compact markdown block for LLM context."""
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, 1):
        date = f" ({r.published_date})" if r.published_date else ""
        src  = f" — {r.source}" if r.source else ""
        lines.append(f"**{i}. {r.title}**{date}{src}")
        lines.append(r.snippet)
        lines.append(f"   Source: {r.url}")
        lines.append("")
    return "\n".join(lines).strip()
