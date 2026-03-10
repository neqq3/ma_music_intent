from __future__ import annotations

import re

from .const import DEFAULT_COUNT, DEFAULT_MODE, SUPPORTED_MODES
from .models import MusicIntent


class FallbackIntentParser:
    """Minimal rule fallback when AI parsing is unavailable."""

    async def parse(
        self,
        prompt: str,
        *,
        count: int | None = None,
        target_player: str | None = None,
        mode: str | None = None,
    ) -> MusicIntent:
        normalized_mode = mode or DEFAULT_MODE
        if normalized_mode not in SUPPORTED_MODES:
            normalized_mode = DEFAULT_MODE

        stripped_prompt = prompt.strip()
        parsed_count, parsed_query = self._parse_query(stripped_prompt)
        resolved_query = parsed_query or stripped_prompt
        resolved_count = count or parsed_count or DEFAULT_COUNT

        intent = MusicIntent(
            prompt=stripped_prompt,
            query=resolved_query,
            count=resolved_count,
            mode=normalized_mode,
            target_player=target_player,
            source_scope="auto",
            allow_external_discovery=True,
            parse_source="fallback",
        )
        intent.keywords = [resolved_query]
        intent.seed_tracks = [resolved_query]
        intent.queue_direction = "Fallback direct search"
        intent.strategy_hint = "search_expand"
        return intent

    def _parse_query(self, prompt: str) -> tuple[int | None, str]:
        patterns = (
            r"^来\s*(?P<count>\d{1,3})\s*首\s+(?P<query>.+?)\s*的歌$",
            r"^来\s*(?P<count>\d{1,3})\s*首\s+(?P<query>.+)$",
            r"^播放\s+(?P<query>.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, prompt)
            if not match:
                continue
            count = match.groupdict().get("count")
            query = (match.groupdict().get("query") or "").strip()
            resolved_count = max(1, min(100, int(count))) if count else None
            return resolved_count, query
        return None, prompt
