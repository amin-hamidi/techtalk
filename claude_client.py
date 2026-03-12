from __future__ import annotations

import json
from anthropic import Anthropic
from search_client import TavilySearch
from collections import OrderedDict

BASE_PERSONA = """You are a senior intelligence analyst with deep expertise across cybersecurity, \
technology, and geopolitics. You hold advanced degrees from top institutions and have decades of \
experience in threat intelligence, technology assessment, and strategic analysis.

You write like a professional intelligence briefer — concise, direct, no fluff. Every sentence \
earns its place. You prioritize by significance and impact."""

SOURCE_CITATION_RULES = """
Citation format:
- Cite sources inline using Discord hyperlinked markdown numbers
- Format each citation as a clickable link: [(1)](URL) [(2)](URL) etc.
- Do NOT include a separate Sources section at the bottom — the inline links ARE the sources
"""

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": "Search the web to fact-check claims, verify reported events, or find additional context.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            }
        },
        "required": ["query"],
    },
}


def _build_x_prompt(prompt_overlay: str) -> str:
    return f"""{BASE_PERSONA}

You are analyzing social media posts from monitored X (Twitter) accounts.

Your task:
1. Analyze ONLY the provided tweets — do NOT use external sources
2. Produce a concise, prioritized intelligence briefing based solely on these posts

Structure:
- The tweets are grouped by X source account. Your briefing MUST be organized the same way: \
one section per source, using **@username** as the section header.
- Order the source sections by significance — the source with the most important/newsworthy \
updates comes first.
- Within each source section, list updates in order of significance.
- Skip any sources that had no posts — do not mention them.

Channel-specific instructions:
{prompt_overlay}

Rules:
- Be thorough — cover ALL significant updates from the provided posts
- For each development: state what happened, provide brief strategic context on why it matters
- Cite sources inline using Discord hyperlinked numbers linking to the original tweet: [(1)](tweet_url)
- Do NOT include a separate Sources section — the inline links ARE the sources
- Keep total response under 3500 characters to fit Discord limits
- Do NOT include preamble or sign-offs - jump straight into the briefing"""


def _build_web_prompt(prompt_overlay: str) -> str:
    return f"""{BASE_PERSONA}

You are producing an intelligence briefing from web search results and news articles.

Your task:
1. Analyze the provided search results
2. Use the web_search tool to find additional context or verify claims as needed
3. Produce a concise, prioritized briefing

Channel-specific instructions:
{prompt_overlay}

Rules:
- Start with the MOST SIGNIFICANT developments first
- Group related events together under clear headings
- For each item: what happened, why it matters strategically
- Keep total response under 3500 characters
- Do NOT include preamble or sign-offs — jump straight into the briefing
{SOURCE_CITATION_RULES}"""


def _build_combined_prompt(prompt_overlay: str) -> str:
    return f"""{BASE_PERSONA}

You are producing a comprehensive intelligence briefing from both X (Twitter) posts and web search results.

Your task:
1. Analyze all provided content (tweets AND web articles)
2. Use the web_search tool to find additional context if needed
3. Produce a unified, prioritized briefing that synthesizes both sources

Channel-specific instructions:
{prompt_overlay}

Rules:
- Start with the MOST SIGNIFICANT developments first
- Group by topic/theme, not by source type
- Clearly attribute information — use [(1)](tweet_url) for tweets and [(2)](article_url) for articles
- Do NOT include a separate Sources section — the inline links ARE the sources
- Keep total response under 3500 characters
- Do NOT include preamble or sign-offs — jump straight into the briefing"""


class ClaudeAnalyzer:
    def __init__(self, api_key: str, tavily: TavilySearch, model: str = "claude-4-sonnet-20250514"):
        self._client = Anthropic(api_key=api_key)
        self._tavily = tavily
        self._model = model

    def _run_no_tools(self, system: str, user_message: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        return self._extract_text(response)

    def _run_with_tools(self, system: str, user_message: str) -> str:
        messages = [{"role": "user", "content": user_message}]

        max_iterations = 10
        response = None
        for _ in range(max_iterations):
            response = self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=system,
                tools=[WEB_SEARCH_TOOL],
                messages=messages,
            )

            if response.stop_reason == "tool_use":
                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        search_query = block.input.get("query", "")
                        results = self._tavily.search(search_query, max_results=3)
                        result_text = json.dumps(results, indent=2)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text,
                        })

                messages.append({"role": "user", "content": tool_results})
            else:
                return self._extract_text(response)

        return self._extract_text(response) if response else "Analysis could not be generated."

    def analyze_x_digest(self, tweets: list[dict], prompt_overlay: str) -> str:
        if not tweets:
            return "No posts found in the specified time window."

        tweet_block = self._format_tweets(tweets)
        system = _build_x_prompt(prompt_overlay)
        user_message = (
            f"Here are the posts from monitored X accounts. "
            f"Analyze ONLY these posts and produce your briefing.\n\n{tweet_block}"
        )
        return self._run_no_tools(system, user_message)

    def analyze_web_digest(self, search_results: list[dict], prompt_overlay: str) -> str:
        if not search_results:
            return "No web results found."

        articles = self._format_search_results(search_results)
        system = _build_web_prompt(prompt_overlay)
        user_message = (
            f"Here are web search results from news and analysis sources. "
            f"Analyze them and produce your briefing.\n\n{articles}"
        )
        return self._run_with_tools(system, user_message)

    def analyze_combined_digest(self, tweets: list[dict], search_results: list[dict], prompt_overlay: str) -> str:
        system = _build_combined_prompt(prompt_overlay)
        parts = []
        if tweets:
            parts.append(f"=== X (TWITTER) POSTS ===\n{self._format_tweets(tweets)}")
        if search_results:
            parts.append(f"=== WEB SEARCH RESULTS ===\n{self._format_search_results(search_results)}")

        if not parts:
            return "No content found from any source."

        user_message = (
            "Here is content from both X posts and web sources. "
            "Produce a unified briefing.\n\n" + "\n\n".join(parts)
        )
        return self._run_with_tools(system, user_message)

    @staticmethod
    def _format_tweets(tweets: list[dict]) -> str:
        by_source: OrderedDict[str, list[dict]] = OrderedDict()
        for t in tweets:
            user = t.get("username", "unknown")
            by_source.setdefault(user, []).append(t)

        lines = []
        idx = 1
        for username, user_tweets in by_source.items():
            lines.append(f"=== @{username} ({len(user_tweets)} posts) ===")
            for t in user_tweets:
                lines.append(f"[{idx}] ({t['created_at']})")
                lines.append(t["text"])
                if t.get("url"):
                    lines.append(f"Link: {t['url']}")
                lines.append("")
                idx += 1
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _format_search_results(results: list[dict]) -> str:
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.get('title', 'No title')}")
            lines.append(r.get("content", "")[:500])
            url = r.get("url", "")
            if url:
                lines.append(f"Source: {url}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _extract_text(response) -> str:
        parts = []
        for block in response.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts) if parts else "Analysis could not be generated."
