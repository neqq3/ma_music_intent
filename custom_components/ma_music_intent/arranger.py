from __future__ import annotations

from collections import Counter

from .models import CandidateTrack, MusicIntent


class Arranger:
    def arrange(self, candidates: list[CandidateTrack], intent: MusicIntent) -> list[CandidateTrack]:
        ranked = sorted(candidates, key=self._sort_key, reverse=True)
        prioritized_candidates = self._prioritize_anchor_coverage(ranked)
        deduped: list[CandidateTrack] = []
        seen: set[str] = set()
        canonical_titles: set[str] = set()
        recent_artists: list[str] = []
        artist_counts: Counter[str] = Counter()
        max_artist_share = self._max_artist_share(intent.count)

        deferred: list[CandidateTrack] = []
        for candidate in prioritized_candidates:
            dedupe_key = self._dedupe_key(candidate)
            if dedupe_key in seen:
                continue
            canonical_title = self._canonical_title(candidate)
            if canonical_title and canonical_title in canonical_titles:
                continue
            seen.add(dedupe_key)
            if not candidate.available and candidate.provider != "dry_run":
                continue
            artist_key = self._artist_key(candidate)
            if artist_key and artist_key in recent_artists[-2:]:
                deferred.append(candidate)
                continue
            if artist_key and artist_counts[artist_key] >= max_artist_share:
                deferred.append(candidate)
                continue
            deduped.append(candidate)
            if canonical_title:
                canonical_titles.add(canonical_title)
            if artist_key:
                recent_artists.append(artist_key)
                artist_counts[artist_key] += 1
            if len(deduped) >= intent.count:
                return deduped

        for candidate in deferred:
            if len(deduped) >= intent.count:
                break
            canonical_title = self._canonical_title(candidate)
            if canonical_title and canonical_title in canonical_titles:
                continue
            artist_key = self._artist_key(candidate)
            if artist_key and artist_key in recent_artists[-1:]:
                continue
            deduped.append(candidate)
            if canonical_title:
                canonical_titles.add(canonical_title)
            if artist_key:
                recent_artists.append(artist_key)
                artist_counts[artist_key] += 1
        return deduped[: intent.count]

    def _dedupe_key(self, candidate: CandidateTrack) -> str:
        if candidate.uri:
            return candidate.uri
        artist = candidate.artist or ""
        return f"{candidate.name.lower()}::{artist.lower()}"

    def _sort_key(self, candidate: CandidateTrack) -> tuple[float, int]:
        provider_bonus = 0.2 if candidate.provider not in {None, "dry_run"} else 0.0
        availability_bonus = 0.2 if candidate.available else -1.0
        return candidate.score + provider_bonus + availability_bonus, int(candidate.available)

    def _artist_key(self, candidate: CandidateTrack) -> str | None:
        artist = (candidate.artist or "").strip().lower()
        return artist or None

    def _max_artist_share(self, queue_size: int) -> int:
        if queue_size <= 4:
            return 2
        return max(2, queue_size // 4)

    def _canonical_title(self, candidate: CandidateTrack) -> str | None:
        value = candidate.metadata.get("canonical_title")
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
        title = candidate.name.strip().lower() if candidate.name else ""
        return title or None

    def _prioritize_anchor_coverage(self, ranked: list[CandidateTrack]) -> list[CandidateTrack]:
        covered: set[str] = set()
        priority: list[CandidateTrack] = []
        remainder: list[CandidateTrack] = []

        for candidate in ranked:
            anchor_key = candidate.metadata.get("intent_anchor_key")
            if isinstance(anchor_key, str) and anchor_key and anchor_key not in covered:
                priority.append(candidate)
                covered.add(anchor_key)
            else:
                remainder.append(candidate)
        return priority + remainder
