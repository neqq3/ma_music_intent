from __future__ import annotations

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
        intent = await self._parser.parse(prompt, count=count, target_player=target_player, mode=mode)
        environment = await self._environment_analyzer.analyze(hass)
        plan = self._planner.build_plan(intent, environment)
        candidates = await self._candidate_builder.build(hass, intent, environment, plan)
        arranged = self._arranger.arrange(candidates, intent)
        result = QueueBuildResult(
            matched_tracks=arranged,
            plan=plan,
            environment=environment,
            intent=intent,
            executed=False,
            message="Queue preview built.",
            raw_candidates=len(candidates),
        )
        result = await self._executor.execute(hass, result)
        return self._serialize_result(result)

    def _serialize_result(self, result: QueueBuildResult) -> dict[str, object]:
        return {
            "executed": result.executed,
            "message": result.message,
            "strategy": result.plan.strategy,
            "reason": result.plan.reason,
            "primary_provider": result.plan.primary_provider,
            "raw_candidates": result.raw_candidates,
            "matched_count": len(result.matched_tracks),
            "tracks": [
                {
                    "name": track.name,
                    "artist": track.artist,
                    "uri": track.uri,
                    "provider": track.provider,
                    "score": track.score,
                    "available": track.available,
                }
                for track in result.matched_tracks
            ],
            "intent": {
                "prompt": result.intent.prompt,
                "count": result.intent.count,
                "mode": result.intent.mode,
                "target_player": result.intent.target_player,
                "language_preference": result.intent.language_preference,
                "mood": result.intent.mood,
                "exclude": result.intent.exclude,
                "seed_artists": result.intent.seed_artists,
                "keywords": result.intent.keywords,
                "freshness": result.intent.freshness,
                "familiarity": result.intent.familiarity,
                "allow_external_discovery": result.intent.allow_external_discovery,
                "source_scope": result.intent.source_scope,
            },
            "environment": {
                "music_assistant_domain": result.environment.music_assistant_domain,
                "has_recommendation_provider": result.environment.has_recommendation_provider,
                "has_streaming_provider": result.environment.has_streaming_provider,
                "providers": [
                    {
                        "domain": provider.domain,
                        "services": sorted(provider.services),
                        "capabilities": sorted(provider.capabilities),
                    }
                    for provider in result.environment.providers
                ],
            },
        }
