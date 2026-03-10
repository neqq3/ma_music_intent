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
        media_ids = [media_id for track in playable_tracks if (media_id := self._build_media_id(track)) is not None]
        if not media_ids:
            result.executed = False
            result.message = "No playable identifier could be built from the matched track."
            result.debug["playback_payload"] = None
            return result

        playback_payload = {
            "entity_id": target_player,
            "media_id": media_ids if len(media_ids) > 1 else media_ids[0],
            "enqueue": "replace",
        }
        result.debug["playback_payload"] = playback_payload
        LOGGER.debug("Music Assistant play_media payload: %s", playback_payload)

        try:
            await hass.services.async_call(domain, "play_media", playback_payload, blocking=True)
        except Exception as err:
            result.executed = False
            result.message = f"Queue preview built, but play_media failed: {err}"
            return result

        result.debug["queue_payloads"] = [
            {"track": track.name, "queued_via": "play_media_batch"}
            for track in playable_tracks[1:]
        ]
        result.executed = True
        queued_count = max(0, len(media_ids) - 1)
        if queued_count:
            result.message = f"Started playback on {target_player} using {playable_track.name} and queued {queued_count} more tracks."
        else:
            result.message = f"Started playback on {target_player} using {playable_track.name}."
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
