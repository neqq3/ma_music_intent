from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SuggestedTrack:
    name: str
    artist: str | None = None


@dataclass(slots=True)
class MusicIntent:
    prompt: str
    query: str
    count: int
    mode: str
    target_player: str | None = None
    source_scope: str = "auto"
    allow_external_discovery: bool = True
    language_preference: list[str] = field(default_factory=list)
    mood: list[str] = field(default_factory=list)
    atmosphere: list[str] = field(default_factory=list)
    energy: float | None = None
    freshness: float | None = None
    familiarity: float | None = None
    exclude: list[str] = field(default_factory=list)
    preferred_eras: list[str] = field(default_factory=list)
    preferred_artists: list[str] = field(default_factory=list)
    avoided_artists: list[str] = field(default_factory=list)
    seed_artists: list[str] = field(default_factory=list)
    seed_tracks: list[str] = field(default_factory=list)
    candidate_tracks: list[SuggestedTrack] = field(default_factory=list)
    candidate_artists: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    exploration_notes: list[str] = field(default_factory=list)
    provider_directions: list[str] = field(default_factory=list)
    continuity: str | None = None
    queue_direction: str | None = None
    strategy_hint: str | None = None
    parse_source: str = "fallback"


@dataclass(slots=True)
class ProviderSnapshot:
    domain: str
    instance_id: str | None = None
    name: str | None = None
    service_domain: str | None = None
    services: set[str] = field(default_factory=set)
    capabilities: set[str] = field(default_factory=set)


@dataclass(slots=True)
class EnvironmentSnapshot:
    providers: list[ProviderSnapshot] = field(default_factory=list)
    has_recommendation_provider: bool = False
    has_streaming_provider: bool = False
    music_assistant_domain: str | None = None


@dataclass(slots=True)
class CandidateTrack:
    name: str
    artist: str | None = None
    uri: str | None = None
    item_id: str | None = None
    media_type: str = "track"
    provider: str | None = None
    available: bool = True
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class QueueConstraints:
    language_preference: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    avoided_artists: list[str] = field(default_factory=list)
    preferred_eras: list[str] = field(default_factory=list)
    continuity: str | None = None
    energy: float | None = None
    freshness: float | None = None
    familiarity: float | None = None
    same_artist_spacing: int = 2


@dataclass(slots=True)
class ProviderPlan:
    provider_domain: str
    route: str
    provider_instance: str | None = None
    provider_name: str | None = None
    recommendation_service: str | None = None
    use_search: bool = False
    use_library_only: bool = False
    allow_provider_expansion: bool = False
    seed_tracks: list[str] = field(default_factory=list)
    seed_artists: list[str] = field(default_factory=list)
    candidate_tracks: list[SuggestedTrack] = field(default_factory=list)
    candidate_artists: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    directions: list[str] = field(default_factory=list)
    query_hints: list[str] = field(default_factory=list)
    target_share: float = 1.0


@dataclass(slots=True)
class ExecutionPlan:
    strategy: str
    reason: str
    primary_provider: str | None = None
    should_use_ai: bool = True
    provider_plans: list[ProviderPlan] = field(default_factory=list)
    allow_multi_source: bool = False
    allow_external_discovery: bool = True
    needs_provider_expansion: bool = False
    source_mix: dict[str, float] = field(default_factory=dict)
    queue_constraints: QueueConstraints = field(default_factory=QueueConstraints)
    planning_notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QueueBuildResult:
    matched_tracks: list[CandidateTrack]
    plan: ExecutionPlan
    environment: EnvironmentSnapshot
    intent: MusicIntent
    executed: bool
    message: str
    raw_candidates: int
    debug: dict[str, Any] = field(default_factory=dict)
