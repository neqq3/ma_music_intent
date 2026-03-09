from __future__ import annotations

from .models import CandidateTrack, MusicIntent


class Arranger:
    def arrange(self, candidates: list[CandidateTrack], intent: MusicIntent) -> list[CandidateTrack]:
        deduped: list[CandidateTrack] = []
        seen: set[str] = set()
        recent_artists: list[str] = []

        ranked = sorted(candidates, key=self._sort_key, reverse=True)
        deferred: list[CandidateTrack] = []
        for candidate in ranked:
            dedupe_key = self._dedupe_key(candidate)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            if not candidate.available and candidate.provider != "dry_run":
                continue
            if candidate.artist and candidate.artist in recent_artists[-2:]:
                deferred.append(candidate)
                continue
            deduped.append(candidate)
            if candidate.artist:
                recent_artists.append(candidate.artist)
            if len(deduped) >= intent.count:
                return deduped

        for candidate in deferred:
            if len(deduped) >= intent.count:
                break
            deduped.append(candidate)
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
