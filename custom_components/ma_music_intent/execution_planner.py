from __future__ import annotations

from .models import EnvironmentSnapshot, ExecutionPlan, MusicIntent


class ExecutionPlanner:
    def build_plan(self, intent: MusicIntent, environment: EnvironmentSnapshot) -> ExecutionPlan:
        if environment.has_recommendation_provider:
            primary = self._pick_primary_provider(environment)
            return ExecutionPlan(
                strategy="direct_track_search",
                reason="Recommendation-capable provider found; deterministic MVP still uses direct track search first.",
                primary_provider=primary,
                should_use_ai=False,
            )

        if environment.has_streaming_provider:
            primary = self._pick_primary_provider(environment)
            return ExecutionPlan(
                strategy="search_match",
                reason="Streaming/search provider found; issue a direct deterministic track search.",
                primary_provider=primary,
                should_use_ai=False,
            )

        return ExecutionPlan(
            strategy="library_fallback",
            reason="No Music Assistant search service detected; return a dry-run preview only.",
            primary_provider=None,
            should_use_ai=False,
        )

    def _pick_primary_provider(self, environment: EnvironmentSnapshot) -> str | None:
        if not environment.providers:
            return None
        ranked = sorted(
            environment.providers,
            key=lambda provider: (
                "recommendations" in provider.capabilities,
                "radio" in provider.capabilities,
                "search" in provider.capabilities,
            ),
            reverse=True,
        )
        return ranked[0].domain
