from __future__ import annotations

from homeassistant.core import HomeAssistant

from .models import CandidateTrack, QueueBuildResult


class MAExecutor:
    async def execute(self, hass: HomeAssistant, result: QueueBuildResult) -> QueueBuildResult:
        target_player = result.intent.target_player
        domain = result.environment.music_assistant_domain
        playable_tracks = [track for track in result.matched_tracks if track.uri]

        if not domain or not target_player or not playable_tracks:
            result.executed = False
            if not target_player:
                result.message = "Queue built as preview only because no target_player was provided."
            elif not playable_tracks:
                result.message = "No playable URIs were found; returning preview only."
            else:
                result.message = "Music Assistant service domain not detected; returning preview only."
            return result

        payload = {
            "entity_id": target_player,
            "media_id": [track.uri for track in playable_tracks],
            "enqueue": "replace",
        }

        try:
            await hass.services.async_call(domain, "play_media", payload, blocking=True)
            result.executed = True
            result.message = f"Queued {len(playable_tracks)} tracks on {target_player}."
            return result
        except Exception as err:
            result.executed = False
            result.message = f"Queue preview built, but play_media failed: {err}"
            return result
