from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.core import HomeAssistant

from .const import MAX_CANDIDATES
from .models import CandidateTrack, EnvironmentSnapshot, ExecutionPlan, MusicIntent, ProviderSnapshot


class CandidateBuilder:
    async def build(
        self,
        hass: HomeAssistant,
        intent: MusicIntent,
        environment: EnvironmentSnapshot,
        plan: ExecutionPlan,
    ) -> list[CandidateTrack]:
        provider = self._resolve_search_provider(environment, plan)
        if provider is None:
            return self._build_dry_run_candidates(intent)

        queries = self._build_queries(intent)
        candidates: list[CandidateTrack] = []
        for query in queries:
            results = await self._search(hass, provider.domain, query)
            candidates.extend(results)
            if len(candidates) >= MAX_CANDIDATES:
                break

        if candidates:
            return candidates[:MAX_CANDIDATES]
        return self._build_dry_run_candidates(intent)

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
        queries: list[str] = []
        queries.extend(intent.seed_tracks)
        queries.extend(intent.seed_artists)
        queries.extend(intent.keywords)
        if intent.prompt not in queries:
            queries.append(intent.prompt)
        seen: set[str] = set()
        deduped: list[str] = []
        for query in queries:
            normalized = query.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped[:12]

    async def _search(self, hass: HomeAssistant, domain: str, query: str) -> list[CandidateTrack]:
        try:
            response = await hass.services.async_call(
                domain,
                "search",
                {"query": query, "media_type": "track", "limit": 10},
                blocking=True,
                return_response=True,
            )
        except Exception:
            return []
        return self._normalize_search_response(response, provider=domain, query=query)

    def _normalize_search_response(self, response: Any, *, provider: str, query: str) -> list[CandidateTrack]:
        rows = list(self._extract_rows(response))
        candidates: list[CandidateTrack] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("name") or row.get("title") or query
            artist = self._extract_artist(row)
            uri = row.get("uri") or row.get("item_id") or row.get("id")
            available = row.get("available", True)
            score = float(row.get("score") or row.get("confidence") or 0.0)
            candidates.append(
                CandidateTrack(
                    name=str(name),
                    artist=artist,
                    uri=str(uri) if uri is not None else None,
                    provider=provider,
                    available=bool(available),
                    score=score,
                    metadata=row,
                )
            )
        return candidates

    def _extract_rows(self, response: Any) -> Iterable[Any]:
        if response is None:
            return []
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            for key in ("items", "tracks", "result", "results"):
                value = response.get(key)
                if isinstance(value, list):
                    return value
            nested = response.get("tracks")
            if isinstance(nested, dict):
                items = nested.get("items")
                if isinstance(items, list):
                    return items
        return []

    def _extract_artist(self, row: dict[str, Any]) -> str | None:
        artists = row.get("artists")
        if isinstance(artists, list) and artists:
            first = artists[0]
            if isinstance(first, dict):
                return str(first.get("name")) if first.get("name") else None
            return str(first)
        artist = row.get("artist")
        return str(artist) if artist else None

    def _build_dry_run_candidates(self, intent: MusicIntent) -> list[CandidateTrack]:
        labels = intent.seed_artists or intent.keywords or [intent.prompt]
        candidates: list[CandidateTrack] = []
        for index, label in enumerate(labels[: intent.count], start=1):
            candidates.append(
                CandidateTrack(
                    name=f"Intent Seed {index}: {label}",
                    artist=None,
                    uri=None,
                    provider="dry_run",
                    available=False,
                    score=max(0.0, 1 - index * 0.05),
                    metadata={"query": label},
                )
            )
        return candidates
