from __future__ import annotations

from tavily import TavilyClient


class TavilySearch:
    def __init__(self, api_key: str):
        self._client = TavilyClient(api_key=api_key)

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        try:
            response = self._client.search(query=query, max_results=max_results)
            return response.get("results", [])
        except Exception:
            return []

    def search_channel(self, queries: list[str], max_results_per_query: int = 5) -> list[dict]:
        """Run multiple queries for a channel and deduplicate by URL."""
        seen_urls = set()
        all_results = []
        for query in queries:
            results = self.search(query, max_results=max_results_per_query)
            for r in results:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)
        return all_results
