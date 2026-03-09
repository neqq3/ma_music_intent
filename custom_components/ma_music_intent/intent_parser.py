from __future__ import annotations

import re

from .const import DEFAULT_COUNT, DEFAULT_MODE, DEFAULT_TARGET_DURATION_MINUTES, SUPPORTED_MODES
from .models import MusicIntent

_ARTIST_PATTERNS = (
    r"和(?P<artist>[\w\u4e00-\u9fff]+)气质接近",
    r"像(?P<artist>[\w\u4e00-\u9fff]+)那种",
    r"(?P<artist>[\w\u4e00-\u9fff]+)风格",
)

_MOOD_KEYWORDS = {
    "calm": ("平静", "安静", "别太吵", "不吵", "calm"),
    "focused": ("写代码", "专注", "focus", "工作"),
    "sad": ("伤感", "悲伤", "sad"),
    "energetic": ("热血", "运动", "high", "亢奋"),
}

_LANGUAGE_KEYWORDS = {
    "zh": ("中文", "国语", "华语"),
    "en": ("英文", "英语"),
    "ja": ("日语", "日文"),
}

_EXCLUDE_KEYWORDS = {
    "too_noisy": ("别太吵", "不要太吵", "不吵"),
    "instrumental_only": ("不要纯器乐", "别纯器乐", "不要器乐"),
    "too_pop": ("不要太口水",),
    "too_familiar": ("别太耳熟",),
}


class IntentParser:
    """Heuristic MVP parser.

    This is intentionally replaceable with a future HA-configured LLM-backed parser.
    """

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

        resolved_count = count or self._extract_count(prompt) or self._extract_duration_count(prompt) or DEFAULT_COUNT

        intent = MusicIntent(
            prompt=prompt,
            count=resolved_count,
            mode=normalized_mode,
            target_player=target_player,
        )
        intent.language_preference = self._extract_languages(prompt)
        intent.mood = self._extract_moods(prompt)
        intent.exclude = self._extract_exclude(prompt)
        intent.seed_artists = self._extract_seed_artists(prompt)
        intent.freshness = self._extract_ratio(prompt, ("新鲜", "新歌"))
        intent.familiarity = self._extract_ratio(prompt, ("熟悉", "耳熟"))
        intent.allow_external_discovery = "本地" not in prompt or "一起找" in prompt
        intent.source_scope = self._extract_source_scope(prompt)
        intent.keywords = self._build_keywords(prompt, intent)
        return intent

    def _extract_count(self, prompt: str) -> int | None:
        match = re.search(r"(\d{1,3})\s*首", prompt)
        if not match:
            return None
        return max(1, min(100, int(match.group(1))))

    def _extract_duration_count(self, prompt: str) -> int | None:
        if "一小时" in prompt or "1小时" in prompt:
            return DEFAULT_TARGET_DURATION_MINUTES // 3
        return None

    def _extract_languages(self, prompt: str) -> list[str]:
        return [code for code, aliases in _LANGUAGE_KEYWORDS.items() if any(alias in prompt for alias in aliases)]

    def _extract_moods(self, prompt: str) -> list[str]:
        return [mood for mood, aliases in _MOOD_KEYWORDS.items() if any(alias in prompt for alias in aliases)]

    def _extract_exclude(self, prompt: str) -> list[str]:
        return [label for label, aliases in _EXCLUDE_KEYWORDS.items() if any(alias in prompt for alias in aliases)]

    def _extract_seed_artists(self, prompt: str) -> list[str]:
        artists: list[str] = []
        for pattern in _ARTIST_PATTERNS:
            match = re.search(pattern, prompt)
            if match:
                artists.append(match.group("artist"))
        return artists

    def _extract_ratio(self, prompt: str, keywords: tuple[str, ...]) -> float | None:
        if not any(keyword in prompt for keyword in keywords):
            return None
        mapping = {"七成": 0.7, "三成": 0.3, "一半": 0.5, "多一点": 0.6}
        for text, value in mapping.items():
            if text in prompt:
                return value
        return None

    def _extract_source_scope(self, prompt: str) -> str:
        if "本地" in prompt and "一起找" not in prompt:
            return "library_only"
        if "网易云" in prompt or "流媒体" in prompt:
            return "any"
        return "auto"

    def _build_keywords(self, prompt: str, intent: MusicIntent) -> list[str]:
        keywords = [prompt]
        keywords.extend(intent.seed_artists)
        keywords.extend(intent.mood)
        keywords.extend(intent.language_preference)
        return [keyword for keyword in keywords if keyword]
