from __future__ import annotations

import logging
from collections.abc import Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import MAX_CANDIDATES
from .models import CandidateTrack, EnvironmentSnapshot, ExecutionPlan, MusicIntent, ProviderPlan, ProviderSnapshot
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
        candidates: list[CandidateTrack] = []
        debug_rows: list[dict[str, object]] = []

        for provider_plan in plan.provider_plans:
            provider = self._resolve_provider(environment, provider_plan.provider_domain)
            if provider is None:
                debug_rows.append({"provider_domain": provider_plan.provider_domain, "error": "provider_not_found"})
                continue

            provider_candidates, provider_debug = await self._build_for_provider(hass, provider, provider_plan, intent, plan)
            candidates.extend(provider_candidates)
            debug_rows.extend(provider_debug)
            if len(candidates) >= MAX_CANDIDATES:
                break

        if candidates:
            return candidates[:MAX_CANDIDATES], debug_rows
        return self._build_dry_run_candidates(intent, plan), debug_rows

    async def _build_for_provider(
        self,
        hass: HomeAssistant,
        provider: ProviderSnapshot,
        provider_plan: ProviderPlan,
        intent: MusicIntent,
        plan: ExecutionPlan,
    ) -> tuple[list[CandidateTrack], list[dict[str, object]]]:
        candidates: list[CandidateTrack] = []
        debug_rows: list[dict[str, object]] = []

        seed_matches: list[CandidateTrack] = []
        if provider_plan.allow_provider_expansion and provider_plan.recommendation_service:
            seed_matches, seed_debug = await self._resolve_seed_tracks(hass, provider, provider_plan)
            debug_rows.extend(seed_debug)
            expanded, expand_debug = await self._expand_from_provider(
                hass,
                provider,
                provider_plan,
                plan,
                seed_matches,
            )
            candidates.extend(expanded)
            debug_rows.extend(expand_debug)

        if provider_plan.use_search:
            sanitized_queries = self._sanitize_queries(provider_plan.query_hints, intent)
            search_candidates, search_debug = await self._search_queries(
                hass,
                provider,
                sanitized_queries,
                use_library_only=provider_plan.use_library_only,
                source_label=provider_plan.route,
            )
            candidates.extend(search_candidates)
            debug_rows.extend(search_debug)

        return self._score_candidates(candidates, provider_plan, intent, plan), debug_rows

    def _resolve_provider(self, environment: EnvironmentSnapshot, domain: str) -> ProviderSnapshot | None:
        for provider in environment.providers:
            if provider.domain == domain:
                return provider
        return None

    async def _resolve_seed_tracks(
        self,
        hass: HomeAssistant,
        provider: ProviderSnapshot,
        provider_plan: ProviderPlan,
    ) -> tuple[list[CandidateTrack], list[dict[str, object]]]:
        seed_queries = self._build_seed_queries(provider_plan)
        return await self._search_queries(
            hass,
            provider,
            seed_queries[:8],
            use_library_only=False,
            source_label="seed_resolution",
            per_query_limit=5,
        )

    async def _expand_from_provider(
        self,
        hass: HomeAssistant,
        provider: ProviderSnapshot,
        provider_plan: ProviderPlan,
        plan: ExecutionPlan,
        seed_matches: list[CandidateTrack],
    ) -> tuple[list[CandidateTrack], list[dict[str, object]]]:
        if not provider_plan.recommendation_service:
            return [], []

        seed = next((match for match in seed_matches if match.item_id or match.uri), None)
        if seed is None:
            return [], [
                {
                    "provider_domain": provider.domain,
                    "operation": "provider_expand",
                    "service": provider_plan.recommendation_service,
                    "result": "skipped",
                    "reason": "No playable seed track could be resolved from seed_tracks/seed_artists/candidate_tracks.",
                }
            ]

        payload = {
            "media_type": seed.media_type,
            "item_id": seed.item_id,
            "limit": int(
                min(
                    MAX_CANDIDATES,
                    max(plan.source_mix.get(provider.domain, 1.0) * plan.queue_constraints.same_artist_spacing * 10, 10),
                )
            ),
        }
        if seed.provider:
            payload["provider"] = seed.provider

        config_entry = self._resolve_music_assistant_entry(hass, provider.domain)
        if config_entry is not None:
            payload["config_entry_id"] = config_entry.entry_id

        try:
            response = await hass.services.async_call(
                provider.domain,
                provider_plan.recommendation_service,
                payload,
                blocking=True,
                return_response=True,
            )
        except Exception as err:
            LOGGER.exception(
                "Provider expansion failed for provider=%s service=%s",
                provider.domain,
                provider_plan.recommendation_service,
            )
            return [], [
                {
                    "provider_domain": provider.domain,
                    "operation": "provider_expand",
                    "service": provider_plan.recommendation_service,
                    "payload": payload,
                    "error": str(err),
                }
            ]

        normalized = normalize_search_result(response, provider_domain=provider.domain, fallback_query=seed.name)
        debug_row = {
            "provider_domain": provider.domain,
            "operation": "provider_expand",
            "service": provider_plan.recommendation_service,
            "payload": payload,
            "raw_response_summary": summarize_search_payload(response),
            "normalized_tracks": [self._serialize_track(track) for track in normalized],
        }
        for track in normalized:
            track.metadata.setdefault("source_operation", "provider_expand")
        return normalized, [debug_row]

    async def _search_queries(
        self,
        hass: HomeAssistant,
        provider: ProviderSnapshot,
        queries: Iterable[str],
        *,
        use_library_only: bool,
        source_label: str,
        per_query_limit: int = 10,
    ) -> tuple[list[CandidateTrack], list[dict[str, object]]]:
        candidates: list[CandidateTrack] = []
        debug_rows: list[dict[str, object]] = []
        for query in queries:
            normalized_query = query.strip()
            if not normalized_query:
                continue
            results, debug_row = await self._search(
                hass,
                provider.domain,
                normalized_query,
                use_library_only=use_library_only,
                limit=per_query_limit,
            )
            debug_row["operation"] = source_label
            debug_rows.append(debug_row)
            for row in results:
                row.metadata.setdefault("source_operation", source_label)
            candidates.extend(results)
            if len(candidates) >= MAX_CANDIDATES:
                break
        return candidates[:MAX_CANDIDATES], debug_rows

    async def _search(
        self,
        hass: HomeAssistant,
        domain: str,
        query: str,
        *,
        use_library_only: bool,
        limit: int,
    ) -> tuple[list[CandidateTrack], dict[str, object]]:
        search_payload = {"name": query, "media_type": "track", "limit": limit}
        if use_library_only:
            search_payload["library_only"] = True
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

        normalized = normalize_search_result(response, provider_domain=domain, fallback_query=query)
        debug_row = {
            "query": query,
            "provider_domain": domain,
            "search_payload": search_payload,
            "raw_response_summary": summarize_search_payload(response),
            "normalized_tracks": [self._serialize_track(track) for track in normalized],
            "playable_count": len([track for track in normalized if track.available and (track.uri or track.item_id)]),
        }
        return normalized, debug_row

    def _score_candidates(
        self,
        candidates: list[CandidateTrack],
        provider_plan: ProviderPlan,
        intent: MusicIntent,
        plan: ExecutionPlan,
    ) -> list[CandidateTrack]:
        scored: list[CandidateTrack] = []
        preferred_artists = {artist.lower() for artist in intent.preferred_artists}
        avoided_artists = {artist.lower() for artist in plan.queue_constraints.avoided_artists}

        for candidate in candidates:
            if not candidate.available or not (candidate.uri or candidate.item_id):
                continue

            score = candidate.score
            artist_name = (candidate.artist or "").lower()
            if artist_name and artist_name in preferred_artists:
                score += 0.3
            if artist_name and artist_name in avoided_artists:
                score -= 0.7

            source_operation = str(candidate.metadata.get("source_operation") or "")
            if source_operation == "provider_expand":
                score += 0.25
            elif source_operation in {"seed_resolution", "recommendation"}:
                score += 0.15
            elif source_operation == "library":
                score += 0.05

            if plan.allow_multi_source and candidate.provider:
                score += min(0.2, provider_plan.target_share * 0.2)

            candidate.score = score
            scored.append(candidate)
        return scored

    def _resolve_music_assistant_entry(self, hass: HomeAssistant, domain: str) -> ConfigEntry | None:
        entries = hass.config_entries.async_entries(domain)
        if entries:
            return entries[0]
        if domain != "music_assistant":
            fallback_entries = hass.config_entries.async_entries("music_assistant")
            if fallback_entries:
                return fallback_entries[0]
        return None

    def _sanitize_queries(self, queries: Iterable[str], intent: MusicIntent) -> list[str]:
        sanitized: list[str] = []
        for query in queries:
            normalized = " ".join(query.strip().split())
            if not self._is_specific_query(normalized):
                continue
            sanitized.append(normalized)

        if sanitized:
            return sanitized[:12]

        fallback_parts: list[str] = []
        if "zh" in {value.lower() for value in intent.language_preference}:
            fallback_parts.append("中文")
        if any(value.lower() in {"calm", "focused"} for value in intent.mood):
            fallback_parts.extend(value for value in intent.mood if value.lower() in {"calm", "focused"})
        if any(value.lower() in {"coding", "late_night"} for value in intent.atmosphere):
            fallback_parts.extend(value for value in intent.atmosphere if value.lower() in {"coding", "late_night"})
        if fallback_parts:
            return [" ".join(dict.fromkeys(fallback_parts))]
        return []

    def _build_seed_queries(self, provider_plan: ProviderPlan) -> list[str]:
        queries: list[str] = []
        queries.extend(provider_plan.seed_tracks)
        queries.extend(provider_plan.seed_artists)
        queries.extend(provider_plan.candidate_artists)
        queries.extend(
            f"{track.name} {track.artist}".strip() if track.artist else track.name
            for track in provider_plan.candidate_tracks
        )
        seen: set[str] = set()
        deduped: list[str] = []
        for query in queries:
            normalized = query.strip()
            if not self._is_specific_query(normalized) or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped[:8]

    def _is_specific_query(self, query: str) -> bool:
        normalized = query.strip()
        if not normalized:
            return False
        generic_terms = {
            "晚上",
            "夜晚",
            "晚风",
            "新鲜",
            "熟悉",
            "中文",
            "写代码",
            "别太吵",
            "安静",
            "专注",
            "fallback",
            "direction",
            "search",
        }
        if normalized.lower() in generic_terms or normalized in generic_terms:
            return False
        if len(normalized) <= 2:
            return False
        if any(token in normalized for token in ("给我来", "来20首", "来 20 首", "七成新鲜", "三成熟悉", "别太吵")):
            return False
        if "，" in normalized or "," in normalized:
            return False
        return True

    def _build_dry_run_candidates(self, intent: MusicIntent, plan: ExecutionPlan) -> list[CandidateTrack]:
        labels = (
            [f"{track.name} {track.artist}".strip() if track.artist else track.name for track in intent.candidate_tracks]
            or intent.seed_tracks
            or intent.keywords
            or [intent.query]
        )
        candidates: list[CandidateTrack] = []
        for index, label in enumerate(labels[: intent.count], start=1):
            candidates.append(
                CandidateTrack(
                    name=f"Intent Seed {index}: {label}",
                    artist=None,
                    uri=None,
                    item_id=None,
                    media_type="track",
                    provider=plan.primary_provider or "dry_run",
                    available=False,
                    score=max(0.0, 1 - index * 0.05),
                    metadata={"query": label, "strategy": plan.strategy},
                )
            )
        return candidates

    def _serialize_track(self, track: CandidateTrack) -> dict[str, object]:
        return {
            "name": track.name,
            "artist": track.artist,
            "provider": track.provider,
            "item_id": track.item_id,
            "uri": track.uri,
            "media_type": track.media_type,
            "available": track.available,
            "score": track.score,
        }
