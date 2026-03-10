from __future__ import annotations

from .models import EnvironmentSnapshot, ExecutionPlan, MusicIntent, ProviderPlan, QueueConstraints


class ExecutionPlanner:
    def build_plan(self, intent: MusicIntent, environment: EnvironmentSnapshot) -> ExecutionPlan:
        eligible = self._eligible_providers(intent, environment)
        has_recommendation_seeds = self._has_recommendation_seed_hints(intent)
        recommendation_capable = [
            provider
            for provider in eligible
            if self._pick_recommendation_service(provider.capabilities) and has_recommendation_seeds
        ]
        search_capable = [provider for provider in eligible if "search" in provider.capabilities]
        library_capable = [provider for provider in eligible if "library" in provider.capabilities]

        recommendation_provider_exists = any(self._pick_recommendation_service(provider.capabilities) for provider in eligible)
        allow_multi_source = self._should_blend_sources(intent, eligible, has_recommendation_seeds)
        constraints = QueueConstraints(
            language_preference=intent.language_preference,
            exclude=intent.exclude,
            avoided_artists=intent.avoided_artists,
            preferred_eras=intent.preferred_eras,
            continuity=intent.continuity or intent.queue_direction,
            energy=intent.energy,
            freshness=intent.freshness,
            familiarity=intent.familiarity,
        )

        if allow_multi_source and recommendation_capable:
            blendable_providers = [
                provider
                for provider in eligible
                if self._pick_recommendation_service(provider.capabilities)
            ]
            provider_plans = [
                self._build_provider_plan(
                    intent,
                    provider,
                    allow_external=intent.allow_external_discovery,
                    target_share=1 / len(blendable_providers),
                )
                for provider in blendable_providers
            ]
            if provider_plans:
                return ExecutionPlan(
                    strategy="multi_provider_blend",
                    reason="Multiple providers are available; blend provider-native expansion and search across sources.",
                    primary_provider=provider_plans[0].provider_domain,
                    provider_plans=provider_plans,
                    allow_multi_source=True,
                    allow_external_discovery=intent.allow_external_discovery,
                    needs_provider_expansion=any(plan.allow_provider_expansion for plan in provider_plans),
                    source_mix={plan.provider_domain: plan.target_share for plan in provider_plans},
                    queue_constraints=constraints,
                    planning_notes=[
                        "AI intent remains an intermediate representation for planning.",
                        "Candidate builder should merge candidate pools across providers before arranging.",
                    ],
                )

        if recommendation_capable and intent.source_scope != "library_only":
            provider = recommendation_capable[0]
            provider_plan = self._build_provider_plan(intent, provider, allow_external=intent.allow_external_discovery)
            return ExecutionPlan(
                strategy="recommendation_expand",
                reason="Recommendation-capable provider is available; use AI seeds and let the provider expand the pool.",
                primary_provider=provider.domain,
                provider_plans=[provider_plan],
                allow_external_discovery=intent.allow_external_discovery,
                needs_provider_expansion=True,
                source_mix={provider.domain: 1.0},
                queue_constraints=constraints,
                planning_notes=["Prefer provider-native expansion, then fill gaps with search if needed."],
            )

        if search_capable and intent.source_scope != "library_only":
            provider_plans = [self._build_provider_plan(intent, search_capable[0], allow_external=intent.allow_external_discovery)]
            reason = "Search-capable provider is available without a stronger recommendation path; use AI hints to form a broad candidate pool."
            if recommendation_provider_exists and not has_recommendation_seeds:
                reason = (
                    "Recommendation provider exists but no resolved seed is available; "
                    "degrade to search_expand with sanitized AI hints."
                )
            return ExecutionPlan(
                strategy="search_expand",
                reason=reason,
                primary_provider=provider_plans[0].provider_domain,
                provider_plans=provider_plans,
                allow_external_discovery=intent.allow_external_discovery,
                needs_provider_expansion=False,
                source_mix={provider_plans[0].provider_domain: 1.0},
                queue_constraints=constraints,
                planning_notes=["Search should consume AI seeds, candidate hints, keywords, and direction cues."],
            )

        provider_plans = []
        if library_capable:
            provider_plans.append(self._build_provider_plan(intent, library_capable[0], allow_external=False, force_library_only=True))
        elif environment.providers:
            provider_plans.append(self._build_provider_plan(intent, environment.providers[0], allow_external=False, force_library_only=True))

        primary_provider = provider_plans[0].provider_domain if provider_plans else None
        return ExecutionPlan(
            strategy="library_explore",
            reason="No external recommendation/search path is reliable in the current environment; explore only what the local library can satisfy.",
            primary_provider=primary_provider,
            provider_plans=provider_plans,
            allow_external_discovery=False,
            needs_provider_expansion=False,
            source_mix={primary_provider: 1.0} if primary_provider else {},
            queue_constraints=constraints,
            planning_notes=["Be explicit about library-only degradation and do not promise external discovery."],
        )

    def _eligible_providers(self, intent: MusicIntent, environment: EnvironmentSnapshot):
        providers = list(environment.providers)
        if intent.source_scope == "library_only":
            return [provider for provider in providers if "library" in provider.capabilities]
        if intent.source_scope == "provider_preferred":
            return [
                provider
                for provider in providers
                if {"search", "recommendations", "radio", "similar_tracks", "dynamic_tracks"} & provider.capabilities
            ]
        return providers

    def _should_blend_sources(self, intent: MusicIntent, providers: list, has_recommendation_seeds: bool) -> bool:
        if intent.source_scope == "mixed":
            return len(providers) > 1 and has_recommendation_seeds
        if intent.source_scope != "auto":
            return False
        if not has_recommendation_seeds:
            return False
        capable = [
            provider
            for provider in providers
            if self._pick_recommendation_service(provider.capabilities)
        ]
        return len(capable) > 1 and intent.allow_external_discovery

    def _build_provider_plan(
        self,
        intent: MusicIntent,
        provider,
        *,
        allow_external: bool,
        force_library_only: bool = False,
        target_share: float = 1.0,
    ) -> ProviderPlan:
        recommendation_service = self._pick_recommendation_service(provider.capabilities)
        route = "library" if force_library_only else "search"
        if recommendation_service and allow_external and not force_library_only and self._has_recommendation_seed_hints(intent):
            route = "recommendation"

        query_hints = self._build_query_hints(intent, route)
        return ProviderPlan(
            provider_domain=provider.service_domain or provider.domain,
            provider_instance=provider.instance_id,
            provider_name=provider.name,
            route=route,
            recommendation_service=recommendation_service if route == "recommendation" else None,
            use_search="search" in provider.capabilities,
            use_library_only=force_library_only,
            allow_provider_expansion=route == "recommendation",
            seed_tracks=intent.seed_tracks[:6],
            seed_artists=intent.seed_artists[:6],
            candidate_tracks=intent.candidate_tracks[:10],
            candidate_artists=(intent.candidate_artists + intent.preferred_artists)[:10],
            keywords=intent.keywords[:12],
            directions=self._build_directions(intent),
            query_hints=query_hints[:16],
            target_share=target_share,
        )

    def _pick_recommendation_service(self, capabilities: set[str]) -> str | None:
        if "recommendations" in capabilities:
            return "recommendations"
        if "similar_tracks" in capabilities:
            return "similar_tracks"
        if "dynamic_tracks" in capabilities:
            return "similar_tracks"
        if "radio" in capabilities:
            return "radio_mode"
        return None

    def _has_recommendation_seed_hints(self, intent: MusicIntent) -> bool:
        if any(self._is_specific_seed_text(value) for value in intent.seed_tracks):
            return True
        if any(self._is_specific_seed_text(value) for value in intent.seed_artists):
            return True
        if any(self._is_specific_seed_text(track.name) for track in intent.candidate_tracks):
            return True
        if any(track.artist and self._is_specific_seed_text(track.artist) for track in intent.candidate_tracks):
            return True
        return False

    def _is_specific_seed_text(self, value: str | None) -> bool:
        if not value:
            return False
        normalized = value.strip()
        if not normalized:
            return False
        generic_terms = {
            "晚上",
            "夜晚",
            "深夜",
            "中文",
            "写代码",
            "新鲜",
            "熟悉",
            "别太吵",
            "安静",
            "专注",
        }
        if normalized in generic_terms:
            return False
        if any(token in normalized for token in ("给我来", "来20首", "来 20 首", "七成新鲜", "三成熟悉", "别太吵")):
            return False
        return True

    def _build_query_hints(self, intent: MusicIntent, route: str) -> list[str]:
        hints: list[str] = []
        if route == "recommendation":
            hints.extend(intent.seed_tracks)
            hints.extend(intent.seed_artists)
            hints.extend(intent.provider_directions)
        else:
            hints.extend(
                f"{track.name} {track.artist}".strip() if track.artist else track.name
                for track in intent.candidate_tracks
            )
            hints.extend(intent.seed_tracks)
            hints.extend(intent.seed_artists)
            hints.extend(intent.candidate_artists)
            hints.extend(intent.preferred_artists)
            hints.extend(intent.keywords)
            hints.extend(intent.provider_directions)
        if intent.queue_direction:
            hints.append(intent.queue_direction)
        hints.append(intent.query)

        seen: set[str] = set()
        deduped: list[str] = []
        for hint in hints:
            normalized = hint.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _build_directions(self, intent: MusicIntent) -> list[str]:
        directions = [
            *intent.provider_directions,
            *(intent.mood or []),
            *(intent.atmosphere or []),
        ]
        if intent.continuity:
            directions.append(intent.continuity)
        if intent.queue_direction:
            directions.append(intent.queue_direction)

        seen: set[str] = set()
        deduped: list[str] = []
        for value in directions:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped
