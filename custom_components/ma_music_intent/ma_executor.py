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

        playable_payloads = [
            payload for track in playable_tracks if (payload := self._build_play_media_payload(track, target_player)) is not None
        ]
        if not playable_payloads:
            result.executed = False
            result.message = "No playable identifier could be built from the matched track."
            result.debug["playback_payload"] = None
            return result

        first_payload = {**playable_payloads[0], "enqueue": "replace"}
        queue_payloads = [{**payload, "enqueue": "add"} for payload in playable_payloads[1:]]
        result.debug["playback_payload"] = first_payload
        result.debug["queue_payloads"] = queue_payloads
        LOGGER.debug("Music Assistant play_media first payload: %s", first_payload)

        try:
            await hass.services.async_call(domain, "play_media", first_payload, blocking=True)
            for payload in queue_payloads:
                await hass.services.async_call(domain, "play_media", payload, blocking=True)
        except Exception as err:
            result.executed = False
            result.message = f"Queue preview built, but play_media failed: {err}"
            return result

        playable_track = playable_tracks[0]
        result.debug["queue_payloads"] = [
            {**payload, "queued_via": "play_media_add"}
            for payload in queue_payloads
        ]
        result.executed = True
        queued_count = max(0, len(playable_payloads) - 1)
        if queued_count:
            result.message = f"Started playback on {target_player} using {playable_track.name} and queued {queued_count} more tracks."
        else:
            result.message = f"Started playback on {target_player} using {playable_track.name}."
        return result

    def _build_play_media_payload(
        self,
        track: CandidateTrack,
        target_player: str,
    ) -> dict[str, str] | None:
        media_id = track.uri or track.item_id
        if not media_id:
            return None
        payload = {
            "entity_id": target_player,
            "media_id": media_id,
            "media_type": track.media_type or "track",
        }
        if not track.uri and track.provider:
            payload["provider"] = track.provider
        return payload
