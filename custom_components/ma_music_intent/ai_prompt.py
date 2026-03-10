from __future__ import annotations

import json

from .models import EnvironmentSnapshot


AI_INTENT_SCHEMA = {
    "count": "integer",
    "source_scope": "library_only | provider_preferred | auto | mixed",
    "allow_external_discovery": True,
    "language_preference": ["zh"],
    "mood": ["calm", "focused"],
    "atmosphere": ["late night", "immersive"],
    "energy": 0.35,
    "freshness": 0.7,
    "familiarity": 0.3,
    "exclude": ["too_noisy"],
    "preferred_eras": ["2010s", "2020s"],
    "preferred_artists": ["artist names"],
    "avoided_artists": ["artist names"],
    "seed_artists": ["artist names"],
    "seed_tracks": ["track names"],
    "candidate_tracks": [{"name": "track name", "artist": "artist name"}],
    "candidate_artists": ["artist names"],
    "keywords": ["searchable keywords"],
    "exploration_notes": ["short exploration notes for downstream validation/expansion"],
    "provider_directions": ["one short expansion direction for providers"],
    "continuity": "keep a stable late-night coding atmosphere",
    "queue_direction": "one sentence about the desired queue arc and vibe",
    "strategy_hint": "recommendation_expand | search_expand | library_explore | multi_provider_blend"
}


def build_ai_system_prompt(
    *,
    prompt: str,
    environment: EnvironmentSnapshot,
    count: int | None,
    target_player: str | None,
    mode: str | None,
) -> str:
    return (
        "You are a music queue planner for Home Assistant + Music Assistant. "
        "Your job is not to control playback directly and not to answer conversationally. "
        "You must understand a complex music request, decide the musical direction, "
        "and produce an intermediate execution-oriented music intent for downstream planning.\n\n"
        f"User request: {prompt}\n"
        f"Requested count override: {count}\n"
        f"Playback target context only, not part of intent understanding: {target_player}\n"
        f"Mode: {mode}\n"
        f"Environment summary:\n{json.dumps(_summarize_environment(environment), ensure_ascii=False, indent=2)}\n\n"
        "Output requirements:\n"
        "1. Return exactly one JSON object only. The first character must be { and the last character must be }.\n"
        "2. Treat this as an intermediate representation for an execution planner, not as a user-facing summary.\n"
        "3. candidate_tracks should contain a handful of likely anchors, not a full queue.\n"
        "4. Use seed_tracks/seed_artists for high-confidence anchors, candidate_* and keywords for broader exploration.\n"
        "5. provider_directions should be short, provider-friendly expansion hints.\n"
        "6. strategy_hint must be one of recommendation_expand, search_expand, library_explore, multi_provider_blend.\n"
        "7. If only local/library exploration is realistic, set allow_external_discovery=false and be honest.\n"
        "8. source_scope must be one of library_only, provider_preferred, auto, mixed.\n"
        "9. energy/freshness/familiarity are floats from 0.0 to 1.0 when inferable, else null.\n"
        "10. Do not wrap JSON in markdown fences. Do not add commentary before or after the JSON.\n\n"
        "11. This is recommendation proposal work, not parameter extraction only.\n"
        "12. You must provide at least one concrete proposal group: seed_artists, seed_tracks, candidate_tracks, or candidate_artists.\n"
        "13. Prefer at least 2 seed_artists or at least 3 candidate_tracks when the request is broad.\n"
        "14. keywords should be music-searchable hints, not just raw constraints like 'freshness' or 'familiarity'.\n"
        "15. Never call Home Assistant tools, actions, intents, or target entities. Only return JSON text.\n\n"
        "16. Ignore playback target resolution entirely. Do not validate or reason about Home Assistant target entities.\n\n"
        f"JSON schema example:\n{json.dumps(AI_INTENT_SCHEMA, ensure_ascii=False, indent=2)}"
    )



def _summarize_environment(environment: EnvironmentSnapshot) -> dict[str, object]:
    return {
        "music_assistant_domain": environment.music_assistant_domain,
        "has_recommendation_provider": environment.has_recommendation_provider,
        "has_streaming_provider": environment.has_streaming_provider,
        "providers": [
            {
                "domain": provider.domain,
                "capabilities": sorted(provider.capabilities),
                "services": sorted(provider.services),
            }
            for provider in environment.providers
        ],
    }
