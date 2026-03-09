from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MusicIntent:
    prompt: str
    count: int
    mode: str
    target_player: str | None = None
    language_preference: list[str] = field(default_factory=list)
    mood: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    seed_artists: list[str] = field(default_factory=list)
    seed_tracks: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    freshness: float | None = None
    familiarity: float | None = None
    allow_external_discovery: bool = True
    source_scope: str = "any"


@dataclass(slots=True)
class ProviderSnapshot:
    domain: str
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
    provider: str | None = None
    available: bool = True
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionPlan:
    strategy: str
    reason: str
    primary_provider: str | None = None
    should_use_ai: bool = True


@dataclass(slots=True)
class QueueBuildResult:
    matched_tracks: list[CandidateTrack]
    plan: ExecutionPlan
    environment: EnvironmentSnapshot
    intent: MusicIntent
    executed: bool
    message: str
    raw_candidates: int
