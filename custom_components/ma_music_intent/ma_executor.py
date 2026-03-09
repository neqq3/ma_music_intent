from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .models import CandidateTrack, QueueBuildResult

LOGGER = logging.getLogger(__name__)


class MAExecutor:
    async def execute(self, hass: HomeAssistant, result: QueueBuildResult) -> QueueBuildResult:
        target_player = result.intent.target_player
        domain = result.environment.music_assistant_domain
        playable_tracks = [track for track in result.matched_tracks if track.available and (track.uri or track.item_id)]

        if not domain or not target_player or not playable_tracks:
            result.executed = False
            if not target_player:
                result.message = "Queue built as preview only because no target_player was provided."
            elif not playable_tracks:
                result.message = "No playable URIs were found; returning preview only."
            else:
                result.message = "Music Assistant service domain not detected; returning preview only."
            return result

        playable_track = playable_tracks[0]
        media_id = self._build_media_id(playable_track)
        if media_id is None:
            result.executed = False
            result.message = "No playable identifier could be built from the matched track."
            result.debug["playback_payload"] = None
            return result

        payload = {
            "entity_id": target_player,
            "media_id": media_id,
            "enqueue": "replace",
        }
        result.debug["playback_payload"] = payload
        LOGGER.debug("Music Assistant play_media payload: %s", payload)

        try:
            await hass.services.async_call(domain, "play_media", payload, blocking=True)
            result.executed = True
            result.message = f"Started playback on {target_player} using {playable_track.name}."
            return result
        except Exception as err:
            result.executed = False
            result.message = f"Queue preview built, but play_media failed: {err}"
            return result

    def _build_media_id(self, track: CandidateTrack) -> str | dict[str, str] | None:
        if track.uri:
            return track.uri
        if not track.item_id:
            return None
        media_id = {
            "media_type": track.media_type,
            "item_id": track.item_id,
        }
        if track.provider:
            media_id["provider"] = track.provider
        return media_id
