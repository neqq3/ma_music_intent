from __future__ import annotations

import json

from .models import EnvironmentSnapshot

INTENT_TASK_RULES = [
    "You are creating a music proposal for a downstream queue builder.",
    "This task is not playback control.",
    "Never refuse because you cannot directly control playback.",
    "Always provide a best-effort music proposal as JSON.",
    "Do not call Home Assistant actions, tools, intents, or target entities.",
    "Do not explain limitations.",
    "Do not apologize.",
    "Do not say you cannot access music services.",
    "Do not say you cannot control playback.",
    "Just return the best-effort music proposal JSON.",
]

INTENT_OUTPUT_RULES = [
    "Return exactly one JSON object.",
    "No markdown fences.",
    "No commentary before or after JSON.",
    "At least one of seed_artists, seed_tracks, candidate_tracks, candidate_artists must be non-empty.",
    "candidate_tracks may be either ['Song - Artist'] or [{'name':'Song','artist':'Artist'}].",
    "Use concrete music anchors for broad requests. Do not return only abstract mood words.",
    "Optional fields may be null, missing, or empty arrays if unknown.",
]

INTENT_CORE_FIELDS = {
    "count": "integer",
    "allow_external_discovery": True,
    "language_preference": ["zh"],
    "mood": ["calm", "focused"],
    "atmosphere": ["late_night", "immersive"],
    "exclude": ["too_noisy"],
    "seed_artists": ["artist names"],
    "seed_tracks": ["track names"],
    "candidate_tracks": ["Song - Artist", {"name": "track name", "artist": "artist name"}],
    "candidate_artists": ["artist names"],
    "keywords": ["searchable music hints"],
}

INTENT_OPTIONAL_FIELDS = {
    "source_scope": "auto",
    "preferred_eras": ["2010s"],
    "energy": 0.35,
    "freshness": 0.7,
    "familiarity": 0.3,
    "provider_directions": ["one short provider hint"],
    "continuity": "optional short continuity hint",
    "queue_direction": "optional short queue arc hint",
    "strategy_hint": "search_expand",
}

INTENT_SCHEMA_EXAMPLE = {
    "count": 20,
    "allow_external_discovery": True,
    "language_preference": ["zh"],
    "mood": ["calm", "focused"],
    "atmosphere": ["late_night"],
    "exclude": ["too_noisy"],
    "seed_artists": ["陈绮贞"],
    "seed_tracks": [],
    "candidate_tracks": [
        {"name": "私奔到月球", "artist": "五月天 / 陈绮贞"},
        "小步舞曲 - 陈绮贞",
    ],
    "candidate_artists": ["万青"],
    "keywords": ["中文 夜晚 写代码"],
    "freshness": 0.7,
    "familiarity": 0.3,
}


def build_ai_system_prompt(
    *,
    prompt: str,
    environment: EnvironmentSnapshot,
    count: int | None,
    target_player: str | None,
    mode: str | None,
) -> str:
    sections = [
        "\n".join(INTENT_TASK_RULES),
        "Output rules:\n" + "\n".join(f"- {rule}" for rule in INTENT_OUTPUT_RULES),
        "Core fields:\n" + json.dumps(INTENT_CORE_FIELDS, ensure_ascii=False, indent=2),
        "Optional fields:\n" + json.dumps(INTENT_OPTIONAL_FIELDS, ensure_ascii=False, indent=2),
        "Example JSON:\n" + json.dumps(INTENT_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2),
        "Request context:\n"
        + json.dumps(
            {
                "user_request": prompt,
                "count_override": count,
                "target_player_context_only": target_player,
                "mode": mode,
                "environment": _summarize_environment(environment),
            },
            ensure_ascii=False,
            indent=2,
        ),
    ]
    return "\n\n".join(sections)


def _summarize_environment(environment: EnvironmentSnapshot) -> dict[str, object]:
    return {
        "has_recommendation_provider": environment.has_recommendation_provider,
        "has_streaming_provider": environment.has_streaming_provider,
    }
