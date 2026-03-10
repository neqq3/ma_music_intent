from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from music_assistant_models.enums import QueueOption

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
            payload
            for track in playable_tracks
            if (payload := self._build_play_media_payloads(track, target_player))
        ]
        if not playable_payloads:
            result.executed = False
            result.message = "No playable identifier could be built from the matched track."
            result.debug["playback_payload"] = None
            return result

        first_attempts = [{**payload, "enqueue": "replace"} for payload in playable_payloads[0]]
        queue_attempts = [[{**payload, "enqueue": "add"} for payload in payload_group] for payload_group in playable_payloads[1:]]
        result.debug["playback_payload"] = first_attempts[0] if first_attempts else None
        result.debug["queue_payloads"] = [attempts[0] for attempts in queue_attempts if attempts]
        result.debug["playback_attempts"] = []
        result.debug["queue_errors"] = []
        result.debug["playback_path"] = "service_play_media"

        LOGGER.debug("Music Assistant play_media first payload attempts: %s", first_attempts)

        first_error: Exception | None = None
        try:
            await self._play_track(
                hass,
                domain=domain,
                target_player=target_player,
                track=playable_tracks[0],
                service_payload_attempts=first_attempts,
                debug_attempts=result.debug["playback_attempts"],
                operation="playback_start",
                queue_option=QueueOption.REPLACE,
            )
        except Exception as err:
            first_error = err

        if first_error is not None:
            result.executed = False
            result.message = f"Queue preview built, but play_media failed: {first_error}"
            return result

        playable_track = playable_tracks[0]
        queued_count = 0
        for index, payload_attempt_group in enumerate(queue_attempts, start=1):
            try:
                await self._play_track(
                    hass,
                    domain=domain,
                    target_player=target_player,
                    track=playable_tracks[index],
                    service_payload_attempts=payload_attempt_group,
                    debug_attempts=result.debug["playback_attempts"],
                    operation=f"queue_add_{index}",
                    queue_option=QueueOption.ADD,
                )
                queued_count += 1
            except Exception as err:
                result.debug["queue_errors"].append(
                    {
                        "track": playable_tracks[index].name,
                        "error": str(err),
                        "attempted_payloads": payload_attempt_group,
                    }
                )

        result.debug["queue_payloads"] = [
            {**attempts[0], "queued_via": "play_media_add"}
            for attempts in queue_attempts
            if attempts
        ]
        result.executed = True
        if queued_count:
            result.message = f"Started playback on {target_player} using {playable_track.name} and queued {queued_count} more tracks."
        elif len(playable_tracks) > 1:
            result.message = f"Started playback on {target_player} using {playable_track.name}, but additional queueing was skipped."
        else:
            result.message = f"Started playback on {target_player} using {playable_track.name}."
        return result

    async def _play_track(
        self,
        hass: HomeAssistant,
        *,
        domain: str,
        target_player: str,
        track: CandidateTrack,
        service_payload_attempts: list[dict[str, str]],
        debug_attempts: list[dict[str, str | bool]],
        operation: str,
        queue_option: QueueOption,
    ) -> None:
        direct_mass_error: Exception | None = None
        try:
            if await self._call_direct_mass_play_media(
                hass,
                target_player=target_player,
                track=track,
                queue_option=queue_option,
                debug_attempts=debug_attempts,
                operation=operation,
            ):
                return
        except Exception as err:
            direct_mass_error = err

        if direct_mass_error is not None:
            debug_attempts.append(
                {
                    "operation": operation,
                    "success": False,
                    "path": "direct_mass",
                    "track": track.name,
                    "error": str(direct_mass_error),
                }
            )

        await self._call_play_media_with_fallbacks(
            hass,
            domain=domain,
            payload_attempts=service_payload_attempts,
            debug_attempts=debug_attempts,
            operation=operation,
        )

    async def _call_direct_mass_play_media(
        self,
        hass: HomeAssistant,
        *,
        target_player: str,
        track: CandidateTrack,
        queue_option: QueueOption,
        debug_attempts: list[dict[str, str | bool]],
        operation: str,
    ) -> bool:
        mass = self._resolve_mass_client(hass)
        if mass is None:
            return False
        queue_id = self._resolve_queue_id(hass, mass, target_player)
        if queue_id is None:
            return False
        media_item = self._build_mass_media_item(track)
        if media_item is None:
            return False
        await mass.player_queues.play_media(queue_id, media=[media_item], option=queue_option)
        debug_attempts.append(
            {
                "operation": operation,
                "success": True,
                "path": "direct_mass",
                "queue_id": queue_id,
                "payload": media_item,
            }
        )
        return True

    def _resolve_mass_client(self, hass: HomeAssistant):
        mass_entry = next(
            (
                entry
                for entry in hass.config_entries.async_entries("music_assistant")
                if entry.state is ConfigEntryState.LOADED and getattr(entry, "runtime_data", None) is not None
            ),
            None,
        )
        return getattr(getattr(mass_entry, "runtime_data", None), "mass", None)

    def _resolve_queue_id(self, hass: HomeAssistant, mass, target_player: str) -> str | None:
        entity_registry = er.async_get(hass)
        entity_entry = entity_registry.async_get(target_player)
        if entity_entry is None or not entity_entry.unique_id:
            return None

        player_id = entity_entry.unique_id
        player = mass.players.get(player_id)
        if player is None:
            return None
        active_source = getattr(player, "active_source", None)
        if active_source and (queue := mass.player_queues.get(active_source)):
            return queue.queue_id
        return player_id

    def _build_mass_media_item(self, track: CandidateTrack) -> dict[str, object] | None:
        provider_instance = track.provider or self._provider_from_uri(track.uri)
        item_id = track.item_id or self._item_id_from_uri(track.uri)
        media_type = track.media_type or "track"
        if not provider_instance or not item_id:
            return None

        provider_domain = provider_instance.split("--", 1)[0]
        media_item: dict[str, object] = {
            "media_type": media_type,
            "item_id": item_id,
            "provider": provider_instance,
            "uri": track.uri or f"{provider_instance}://{media_type}/{item_id}",
            "name": track.name,
            "version": str(track.metadata.get("version") or ""),
            "image": track.metadata.get("image"),
            "provider_mappings": [
                {
                    "item_id": item_id,
                    "provider_domain": provider_domain,
                    "provider_instance": provider_instance,
                    "available": bool(track.available),
                }
            ],
        }
        return media_item

    async def _call_play_media_with_fallbacks(
        self,
        hass: HomeAssistant,
        *,
        domain: str,
        payload_attempts: list[dict[str, str]],
        debug_attempts: list[dict[str, str | bool]],
        operation: str,
    ) -> None:
        last_error: Exception | None = None
        for payload in payload_attempts:
            try:
                await hass.services.async_call(domain, "play_media", payload, blocking=True)
                debug_attempts.append(
                    {
                        "operation": operation,
                        "success": True,
                        "path": "service_play_media",
                        "payload": payload,
                    }
                )
                return
            except Exception as err:
                last_error = err
                debug_attempts.append(
                    {
                        "operation": operation,
                        "success": False,
                        "path": "service_play_media",
                        "payload": payload,
                        "error": str(err),
                    }
                )
        if last_error is not None:
            raise last_error

    def _build_play_media_payloads(
        self,
        track: CandidateTrack,
        target_player: str,
    ) -> list[dict[str, str]]:
        payloads: list[dict[str, str]] = []
        media_type = track.media_type or "track"

        if track.uri:
            payloads.append(
                {
                    "entity_id": target_player,
                    "media_id": track.uri,
                    "media_type": media_type,
                }
            )
            payloads.append(
                {
                    "entity_id": target_player,
                    "media_id": track.uri,
                }
            )

        if track.item_id:
            payload = {
                "entity_id": target_player,
                "media_id": track.item_id,
                "media_type": media_type,
            }
            if track.provider:
                payload["provider"] = track.provider
            payloads.append(payload)

            fallback_payload = {
                "entity_id": target_player,
                "media_id": track.item_id,
            }
            if track.provider:
                fallback_payload["provider"] = track.provider
            payloads.append(fallback_payload)

        deduped: list[dict[str, str]] = []
        seen: set[tuple[tuple[str, str], ...]] = set()
        for payload in payloads:
            key = tuple(sorted(payload.items()))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(payload)
        return deduped

    def _provider_from_uri(self, uri: str | None) -> str | None:
        if not uri or "://" not in uri:
            return None
        return uri.split("://", 1)[0] or None

    def _item_id_from_uri(self, uri: str | None) -> str | None:
        if not uri or "://" not in uri:
            return None
        try:
            return uri.split("://", 1)[1].split("/", 1)[1]
        except IndexError:
            return None
