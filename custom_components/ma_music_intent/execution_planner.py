from __future__ import annotations

from .models import EnvironmentSnapshot, ExecutionPlan, MusicIntent


class ExecutionPlanner:
    def build_plan(self, intent: MusicIntent, environment: EnvironmentSnapshot) -> ExecutionPlan:
        if environment.has_recommendation_provider and intent.mode != "ai":
            primary = self._pick_primary_provider(environment)
            return ExecutionPlan(
                strategy="provider_expand",
                reason="Found recommendation-capable provider; use AI for seed selection and provider for expansion.",
                primary_provider=primary,
                should_use_ai=True,
            )

        if environment.has_streaming_provider:
            primary = self._pick_primary_provider(environment)
            return ExecutionPlan(
                strategy="search_match",
                reason="Streaming/search provider found without recommendation features; use AI/query expansion with search.",
                primary_provider=primary,
                should_use_ai=True,
            )

        return ExecutionPlan(
            strategy="library_fallback",
            reason="No Music Assistant provider services detected; build a dry-run result from parsed intent only.",
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
