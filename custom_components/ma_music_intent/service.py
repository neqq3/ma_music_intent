from __future__ import annotations

from homeassistant.components.assist_pipeline.pipeline import async_get_pipeline
from homeassistant.core import HomeAssistant

from .arranger import Arranger
from .candidate_builder import CandidateBuilder
from .environment_analyzer import EnvironmentAnalyzer
from .execution_planner import ExecutionPlanner
from .intent_parser import IntentParser
from .ma_executor import MAExecutor
from .models import QueueBuildResult


class MusicIntentService:
    def __init__(self) -> None:
        self._parser = IntentParser()
        self._environment_analyzer = EnvironmentAnalyzer()
        self._planner = ExecutionPlanner()
        self._candidate_builder = CandidateBuilder()
        self._arranger = Arranger()
        self._executor = MAExecutor()

    async def build_queue(
        self,
        hass: HomeAssistant,
        *,
        prompt: str,
        count: int | None,
        target_player: str | None,
        mode: str | None,
    ) -> dict[str, object]:
        environment = await self._environment_analyzer.analyze(hass)
        intent, parser_debug = await self._parser.parse(
            hass,
            prompt=prompt,
            environment=environment,
            count=count,
            target_player=target_player,
            mode=mode,
        )
        plan = self._planner.build_plan(intent, environment)
        candidates, search_debug = await self._candidate_builder.build(hass, intent, environment, plan)
        arranged = self._arranger.arrange(candidates, intent)
        result = QueueBuildResult(
            matched_tracks=arranged,
            plan=plan,
            environment=environment,
            intent=intent,
            executed=False,
            message="Queue preview built.",
            raw_candidates=len(candidates),
            debug={"parser": parser_debug, "search": search_debug},
        )
        result = await self._executor.execute(hass, result)
        return self._serialize_result(hass, result)

    def _serialize_result(self, hass: HomeAssistant, result: QueueBuildResult) -> dict[str, object]:
        ai_agent = self._serialize_ai_agent(hass, result.debug.get("parser", {}))
        return {
            "executed": result.executed,
            "message": result.message,
            "ai_agent": ai_agent,
            "strategy": result.plan.strategy,
            "reason": result.plan.reason,
            "primary_provider": result.plan.primary_provider,
            "allow_multi_source": result.plan.allow_multi_source,
            "needs_provider_expansion": result.plan.needs_provider_expansion,
            "raw_candidates": result.raw_candidates,
            "matched_count": len(result.matched_tracks),
            "tracks": [
                {
                    "name": track.name,
                    "artist": track.artist,
                    "item_id": track.item_id,
                    "uri": track.uri,
                    "media_type": track.media_type,
                    "provider": track.provider,
                    "score": track.score,
                    "available": track.available,
                }
                for track in result.matched_tracks
            ],
            "intent": {
                "prompt": result.intent.prompt,
                "query": result.intent.query,
                "count": result.intent.count,
                "mode": result.intent.mode,
                "target_player": result.intent.target_player,
                "parse_source": result.intent.parse_source,
                "source_scope": result.intent.source_scope,
                "allow_external_discovery": result.intent.allow_external_discovery,
                "language_preference": result.intent.language_preference,
                "mood": result.intent.mood,
                "atmosphere": result.intent.atmosphere,
                "energy": result.intent.energy,
                "exclude": result.intent.exclude,
                "preferred_eras": result.intent.preferred_eras,
                "preferred_artists": result.intent.preferred_artists,
                "avoided_artists": result.intent.avoided_artists,
                "seed_artists": result.intent.seed_artists,
                "seed_tracks": result.intent.seed_tracks,
                "candidate_tracks": [
                    {"name": track.name, "artist": track.artist}
                    for track in result.intent.candidate_tracks
                ],
                "candidate_artists": result.intent.candidate_artists,
                "keywords": result.intent.keywords,
                "exploration_notes": result.intent.exploration_notes,
                "provider_directions": result.intent.provider_directions,
                "continuity": result.intent.continuity,
                "freshness": result.intent.freshness,
                "familiarity": result.intent.familiarity,
                "queue_direction": result.intent.queue_direction,
                "strategy_hint": result.intent.strategy_hint,
            },
            "plan": {
                "strategy": result.plan.strategy,
                "reason": result.plan.reason,
                "allow_multi_source": result.plan.allow_multi_source,
                "allow_external_discovery": result.plan.allow_external_discovery,
                "needs_provider_expansion": result.plan.needs_provider_expansion,
                "source_mix": result.plan.source_mix,
                "planning_notes": result.plan.planning_notes,
                "queue_constraints": {
                    "language_preference": result.plan.queue_constraints.language_preference,
                    "exclude": result.plan.queue_constraints.exclude,
                    "avoided_artists": result.plan.queue_constraints.avoided_artists,
                    "preferred_eras": result.plan.queue_constraints.preferred_eras,
                    "continuity": result.plan.queue_constraints.continuity,
                    "energy": result.plan.queue_constraints.energy,
                    "freshness": result.plan.queue_constraints.freshness,
                    "familiarity": result.plan.queue_constraints.familiarity,
                    "same_artist_spacing": result.plan.queue_constraints.same_artist_spacing,
                },
                "provider_plans": [
                    {
                        "provider_domain": provider_plan.provider_domain,
                        "provider_instance": provider_plan.provider_instance,
                        "provider_name": provider_plan.provider_name,
                        "route": provider_plan.route,
                        "recommendation_service": provider_plan.recommendation_service,
                        "use_search": provider_plan.use_search,
                        "use_library_only": provider_plan.use_library_only,
                        "allow_provider_expansion": provider_plan.allow_provider_expansion,
                        "seed_tracks": provider_plan.seed_tracks,
                        "seed_artists": provider_plan.seed_artists,
                        "candidate_tracks": [
                            {"name": track.name, "artist": track.artist}
                            for track in provider_plan.candidate_tracks
                        ],
                        "candidate_artists": provider_plan.candidate_artists,
                        "keywords": provider_plan.keywords,
                        "directions": provider_plan.directions,
                        "query_hints": provider_plan.query_hints,
                        "target_share": provider_plan.target_share,
                    }
                    for provider_plan in result.plan.provider_plans
                ],
            },
            "debug": result.debug,
            "environment": {
                "music_assistant_domain": result.environment.music_assistant_domain,
                "has_recommendation_provider": result.environment.has_recommendation_provider,
                "has_streaming_provider": result.environment.has_streaming_provider,
                "providers": [
                    {
                        "domain": provider.domain,
                        "instance_id": provider.instance_id,
                        "name": provider.name,
                        "service_domain": provider.service_domain,
                        "services": sorted(provider.services),
                        "capabilities": sorted(provider.capabilities),
                    }
                    for provider in result.environment.providers
                ],
            },
        }

    def _serialize_ai_agent(self, hass: HomeAssistant, parser_debug: dict[str, object]) -> dict[str, object]:
        agent_id = parser_debug.get("agent_id")
        resolved_from = "override"
        configured_default = None
        configured_default_name = None

        try:
            pipeline = async_get_pipeline(hass)
            configured_default = pipeline.conversation_engine
            configured_default_name = pipeline.name
        except Exception:
            pipeline = None

        if not agent_id:
            agent_id = configured_default
            resolved_from = "assist_default_fallback"
        elif agent_id == configured_default:
            resolved_from = "assist_default"

        label = None
        if isinstance(agent_id, str):
            state = hass.states.get(agent_id)
            if state:
                label = state.attributes.get("friendly_name") or state.name
            label = label or agent_id

        return {
            "agent_id": agent_id,
            "name": label,
            "resolved_from": resolved_from,
            "assist_default_agent_id": configured_default,
            "assist_default_name": configured_default_name,
        }
