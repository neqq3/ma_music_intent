from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from homeassistant.config_entries import ConfigEntry

from .const import MAX_CANDIDATES
from .models import CandidateTrack, EnvironmentSnapshot, ExecutionPlan, MusicIntent, ProviderSnapshot
from .search_normalizer import normalize_search_result, summarize_search_payload

LOGGER = logging.getLogger(__name__)


class CandidateBuilder:
    async def build(
        self,
        hass: HomeAssistant,
        intent: MusicIntent,
        environment: EnvironmentSnapshot,
        plan: ExecutionPlan,
    ) -> tuple[list[CandidateTrack], list[dict[str, object]]]:
        provider = self._resolve_search_provider(environment, plan)
        if provider is None:
            return self._build_dry_run_candidates(intent), []

        queries = self._build_queries(intent)
        candidates: list[CandidateTrack] = []
        debug_rows: list[dict[str, object]] = []
        for query in queries:
            results, debug_row = await self._search(hass, provider.domain, query)
            debug_rows.append(debug_row)
            playable_results = [row for row in results if row.available and (row.uri or row.item_id)]
            candidates.extend(playable_results)
            if len(candidates) >= MAX_CANDIDATES:
                break

        if candidates:
            return candidates[:MAX_CANDIDATES], debug_rows
        return self._build_dry_run_candidates(intent), debug_rows

    def _resolve_search_provider(
        self,
        environment: EnvironmentSnapshot,
        plan: ExecutionPlan,
    ) -> ProviderSnapshot | None:
        if not environment.providers:
            return None
        if plan.primary_provider:
            for provider in environment.providers:
                if provider.domain == plan.primary_provider and "search" in provider.capabilities:
                    return provider
        for provider in environment.providers:
            if "search" in provider.capabilities:
                return provider
        return None

    def _build_queries(self, intent: MusicIntent) -> list[str]:
        queries: list[str] = [intent.query]
        seen: set[str] = set()
        deduped: list[str] = []
        for query in queries:
            normalized = query.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped[:1]

    def _resolve_music_assistant_entry(self, hass: HomeAssistant, domain: str) -> ConfigEntry | None:
        entries = hass.config_entries.async_entries(domain)
        if entries:
            return entries[0]
        if domain != "music_assistant":
            fallback_entries = hass.config_entries.async_entries("music_assistant")
            if fallback_entries:
                return fallback_entries[0]
        return None

    async def _search(self, hass: HomeAssistant, domain: str, query: str) -> tuple[list[CandidateTrack], dict[str, object]]:
        search_payload = {"name": query, "media_type": "track", "limit": 10}
        config_entry = self._resolve_music_assistant_entry(hass, domain)
        if config_entry is not None:
            search_payload["config_entry_id"] = config_entry.entry_id
        try:
            response = await hass.services.async_call(
                domain,
                "search",
                search_payload,
                blocking=True,
                return_response=True,
            )
        except Exception as err:
            LOGGER.exception("Music Assistant search failed for query=%s via domain=%s", query, domain)
            return [], {"query": query, "provider_domain": domain, "search_payload": search_payload, "error": str(err)}

        LOGGER.debug("Music Assistant search raw response for query=%s via %s: %r", query, domain, response)
        normalized = normalize_search_result(response, provider_domain=domain, fallback_query=query)
        debug_row = {
            "query": query,
            "provider_domain": domain,
            "search_payload": search_payload,
            "raw_response_summary": summarize_search_payload(response),
            "raw_response": response,
            "normalized_tracks": [
                {
                    "name": track.name,
                    "artist": track.artist,
                    "provider": track.provider,
                    "item_id": track.item_id,
                    "uri": track.uri,
                    "media_type": track.media_type,
                    "available": track.available,
                }
                for track in normalized
            ],
            "playable_count": len([track for track in normalized if track.available and (track.uri or track.item_id)]),
        }
        LOGGER.debug("Music Assistant search normalized tracks for query=%s: %s", query, debug_row["normalized_tracks"])
        return normalized, debug_row

    def _build_dry_run_candidates(self, intent: MusicIntent) -> list[CandidateTrack]:
        labels = [intent.query]
        candidates: list[CandidateTrack] = []
        for index, label in enumerate(labels[: intent.count], start=1):
            candidates.append(
                CandidateTrack(
                    name=f"Intent Seed {index}: {label}",
                    artist=None,
                    uri=None,
                    item_id=None,
                    media_type="track",
                    provider="dry_run",
                    available=False,
                    score=max(0.0, 1 - index * 0.05),
                    metadata={"query": label},
                )
            )
        return candidates
