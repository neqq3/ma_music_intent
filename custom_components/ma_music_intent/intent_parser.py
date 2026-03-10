from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.assist_pipeline.pipeline import async_get_pipeline
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .ai_parser import AIIntentParser
from .const import CONF_AGENT_ID, CONF_USE_CUSTOM_AGENT
from .fallback_parser import FallbackIntentParser
from .models import EnvironmentSnapshot, MusicIntent

LOGGER = logging.getLogger(__name__)


class IntentParser:
    """AI-first parser with a minimal deterministic fallback."""

    def __init__(self) -> None:
        self._ai_parser = AIIntentParser()
        self._fallback_parser = FallbackIntentParser()

    async def parse(
        self,
        hass: HomeAssistant,
        *,
        prompt: str,
        environment: EnvironmentSnapshot,
        count: int | None = None,
        target_player: str | None = None,
        mode: str | None = None,
    ) -> tuple[MusicIntent, dict[str, Any]]:
        agent_id = self._resolve_agent_id(hass)
        try:
            intent, debug = await self._ai_parser.parse(
                hass,
                prompt=prompt,
                environment=environment,
                count=count,
                target_player=target_player,
                mode=mode,
                agent_id=agent_id,
            )
            debug["parse_source"] = "ai"
            return intent, debug
        except Exception as err:
            LOGGER.exception("AI intent parsing failed; falling back to rule parser")
            fallback_intent = await self._fallback_parser.parse(
                prompt,
                count=count,
                target_player=target_player,
                mode=mode,
            )
            return fallback_intent, {
                "parse_source": "fallback",
                "agent_id": agent_id,
                "error": str(err),
            }

    def _resolve_agent_id(self, hass: HomeAssistant) -> str | None:
        entries = hass.config_entries.async_entries("ma_music_intent")
        if not entries:
            return self._resolve_assist_default_agent_id(hass)
        entry: ConfigEntry = entries[0]
        if CONF_USE_CUSTOM_AGENT in entry.options:
            if not entry.options.get(CONF_USE_CUSTOM_AGENT):
                return self._resolve_assist_default_agent_id(hass)
            return entry.options.get(CONF_AGENT_ID) or None

        # Backward-compatible behavior for older entries that only stored agent_id.
        return entry.options.get(CONF_AGENT_ID) or entry.data.get(CONF_AGENT_ID)

    def _resolve_assist_default_agent_id(self, hass: HomeAssistant) -> str | None:
        try:
            return async_get_pipeline(hass).conversation_engine
        except Exception:
            LOGGER.exception("Unable to resolve Assist preferred conversation engine")
            return None
