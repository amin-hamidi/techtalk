from __future__ import annotations

import time
import logging
import requests
from typing import Dict, List, Optional

log = logging.getLogger("x-client")


class XClient:
    BASE = "https://api.x.com/2"

    def __init__(self, bearer_token: str, timeout_s: int = 60, max_retries: int = 2):
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {bearer_token}",
            "User-Agent": "techtalk-bot/0.1",
        })
        self._timeout = timeout_s
        self._max_retries = max_retries

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.BASE}{path}"
        last_err = None
        for attempt in range(1, self._max_retries + 1):
            try:
                r = self._session.get(url, params=params, timeout=self._timeout)
                if not r.ok:
                    raise RuntimeError(f"X API error {r.status_code}: {r.text}")
                return r.json()
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_err = e
                if attempt < self._max_retries:
                    wait = 2 ** attempt
                    log.warning("X API request to %s timed out (attempt %d/%d), retrying in %ds...",
                                path, attempt, self._max_retries, wait)
                    time.sleep(wait)
        raise RuntimeError(f"X API request to {path} failed after {self._max_retries} attempts: {last_err}")

    def get_user_id(self, username: str) -> str:
        data = self._get(f"/users/by/username/{username}")
        user = data.get("data") or {}
        uid = user.get("id")
        if not uid:
            raise RuntimeError(f"Could not resolve @{username}. Response: {data}")
        return uid

    def get_posts(
        self,
        user_id: str,
        username: str,
        start_time_utc_iso: str,
        end_time_utc_iso: str,
        include_replies: bool = False,
        include_retweets: bool = False,
        max_pages: int = 50,
    ) -> List[Dict]:
        all_posts: List[Dict] = []
        pagination_token: Optional[str] = None
        page = 0

        excludes = []
        if not include_replies:
            excludes.append("replies")
        if not include_retweets:
            excludes.append("retweets")

        while page < max_pages:
            page += 1
            params = {
                "start_time": start_time_utc_iso,
                "end_time": end_time_utc_iso,
                "max_results": 100,
                "tweet.fields": "created_at",
            }
            if excludes:
                params["exclude"] = ",".join(excludes)
            if pagination_token:
                params["pagination_token"] = pagination_token

            data = self._get(f"/users/{user_id}/tweets", params=params)

            items = data.get("data") or []
            for it in items:
                tid = it.get("id")
                all_posts.append({
                    "id": tid,
                    "username": username,
                    "created_at": it.get("created_at", ""),
                    "text": it.get("text", ""),
                    "url": f"https://x.com/{username}/status/{tid}" if tid else "",
                })

            meta = data.get("meta") or {}
            pagination_token = meta.get("next_token")
            if not pagination_token:
                break

        return all_posts
