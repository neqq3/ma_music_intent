from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any

from homeassistant.components.conversation.agent_manager import async_converse
from homeassistant.core import Context, HomeAssistant

from .models import CandidateTrack, MusicIntent

LOGGER = logging.getLogger(__name__)


class CandidateCurator:
    async def curate(
        self,
        hass: HomeAssistant,
        *,
        intent: MusicIntent,
        candidates: list[CandidateTrack],
        agent_id: str | None,
        mode: str,
    ) -> tuple[list[CandidateTrack], dict[str, Any]]:
        debug = {
            "mode": mode,
            "invoked": False,
            "candidate_pool_size": len(candidates),
            "input_summary_present": False,
            "ai_response_text_present": False,
            "ai_json_present": False,
            "stage": "skipped",
            "failure_reason": None,
            "dropped_indexes": [],
            "selected_indexes": [],
            "ordered_indexes": [],
            "kept_count": len(candidates),
            "final_count": len(candidates),
            "rejection_reasons": [],
            "diversity_adjustments_applied": [],
        }
        if mode == "off":
            return candidates, debug

        light_mode = "light"
        if mode == "strong":
            debug["stage"] = "fallback_light"
            debug["failure_reason"] = "strong_not_implemented_yet"
        else:
            debug["stage"] = "light"

        playable_candidates = [candidate for candidate in candidates if candidate.available and (candidate.uri or candidate.item_id)]
        candidate_summary = self._build_candidate_summary(playable_candidates)
        debug["input_summary_present"] = bool(candidate_summary)
        if not candidate_summary:
            debug["stage"] = "fallback_off"
            debug["failure_reason"] = "no_playable_candidates_for_curation"
            return candidates, debug

        debug["invoked"] = True
        prompt = self._build_user_prompt(intent, candidate_summary)
        system_prompt = self._build_system_prompt()

        try:
            response_dict = await self._run_attempt(
                hass,
                prompt=prompt,
                system_prompt=system_prompt,
                agent_id=agent_id,
            )
        except Exception as err:
            LOGGER.exception("Candidate curation failed")
            debug["stage"] = "fallback_off" if mode == "light" else "fallback_light"
            debug["failure_reason"] = f"conversation_error: {err}"
            return candidates, debug

        texts = self._collect_text_candidates(response_dict)
        payload = self._extract_json_payload(response_dict)
        debug["ai_response_text_present"] = bool(texts)
        debug["ai_json_present"] = payload is not None
        debug["response_text"] = texts[0] if texts else None
        debug["raw_response"] = response_dict

        if payload is None:
            debug["stage"] = "fallback_off" if mode == "light" else "fallback_light"
            debug["failure_reason"] = "no_parseable_curation_json"
            return candidates, debug

        curated_candidates, apply_debug = self._apply_light_curation(
            candidates=candidates,
            playable_candidates=playable_candidates,
            payload=payload,
        )
        debug.update(apply_debug)
        debug["stage"] = "accepted"
        debug["kept_count"] = len(curated_candidates)
        debug["final_count"] = len(curated_candidates)
        return curated_candidates, debug

    def _apply_light_curation(
        self,
        *,
        candidates: list[CandidateTrack],
        playable_candidates: list[CandidateTrack],
        payload: dict[str, Any],
    ) -> tuple[list[CandidateTrack], dict[str, Any]]:
        indexed_candidates = {index + 1: candidate for index, candidate in enumerate(playable_candidates)}
        drop_indexes = self._coerce_index_list(payload.get("drop"))
        maybe_downrank_indexes = self._coerce_index_list(payload.get("maybe_downrank"))
        keep_indexes = self._coerce_index_list(payload.get("keep"))
        rejection_reasons = self._coerce_string_list(payload.get("reasons"))

        dropped_keys = {
            self._candidate_identity(indexed_candidates[index])
            for index in drop_indexes
            if index in indexed_candidates
        }
        maybe_downrank_keys = {
            self._candidate_identity(indexed_candidates[index])
            for index in maybe_downrank_indexes
            if index in indexed_candidates
        }
        keep_keys = {
            self._candidate_identity(indexed_candidates[index])
            for index in keep_indexes
            if index in indexed_candidates
        }

        curated_candidates: list[CandidateTrack] = []
        diversity_adjustments: list[str] = []
        for candidate in candidates:
            identity = self._candidate_identity(candidate)
            if identity in dropped_keys:
                continue
            if identity in maybe_downrank_keys:
                candidate.score -= 0.35
                candidate.metadata["curation_downranked"] = True
                diversity_adjustments.append(f"downrank:{candidate.name}")
            if keep_keys and identity in keep_keys:
                candidate.score += 0.12
                candidate.metadata["curation_keep"] = True
            curated_candidates.append(candidate)

        return curated_candidates, {
            "dropped_indexes": drop_indexes,
            "selected_indexes": keep_indexes,
            "ordered_indexes": [],
            "rejection_reasons": rejection_reasons,
            "diversity_adjustments_applied": diversity_adjustments,
            "failure_reason": None,
        }

    def _build_candidate_summary(self, candidates: list[CandidateTrack]) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates[:40], start=1):
            summary.append(
                {
                    "index": index,
                    "title": candidate.name,
                    "artist": candidate.artist,
                    "source": candidate.provider,
                    "matched_from": candidate.metadata.get("intent_anchor")
                    or candidate.metadata.get("source_operation")
                    or "search_query",
                    "score": round(candidate.score, 3),
                    "flags": self._infer_flags(candidate),
                }
            )
        return summary

    def _infer_flags(self, candidate: CandidateTrack) -> list[str]:
        name = candidate.name.lower()
        flags: list[str] = []
        for token, label in (
            ("remix", "remix"),
            ("live", "live"),
            ("cover", "cover"),
            ("acoustic", "acoustic"),
            ("instrumental", "instrumental"),
            ("伴奏", "instrumental"),
            ("翻唱", "cover"),
            ("慢放", "slowed"),
            ("slowed", "slowed"),
            ("reverb", "reverb"),
        ):
            if token in name and label not in flags:
                flags.append(label)
        return flags

    def _build_system_prompt(self) -> str:
        return (
            "You are reviewing a candidate music queue, not parsing intent.\n"
            "Return one JSON object only.\n"
            "In light mode, remove obviously bad matches, noisy or off-topic tracks, duplicate versions, remix/live/cover clutter,\n"
            "and tracks that make the queue too repetitive.\n"
            "Do not recommend songs outside the provided candidate list.\n"
            'JSON schema: {"keep":[1,2], "drop":[3], "maybe_downrank":[4], "reasons":["short reason"]}'
        )

    def _build_user_prompt(self, intent: MusicIntent, candidate_summary: list[dict[str, Any]]) -> str:
        return json.dumps(
            {
                "task": "light_queue_curation",
                "user_request": intent.prompt,
                "intent_summary": {
                    "count": intent.count,
                    "mood": intent.mood,
                    "atmosphere": intent.atmosphere,
                    "exclude": intent.exclude,
                    "language_preference": intent.language_preference,
                    "freshness": intent.freshness,
                    "familiarity": intent.familiarity,
                    "seed_artists": intent.seed_artists[:6],
                    "candidate_tracks": [
                        {"title": track.name, "artist": track.artist}
                        for track in intent.candidate_tracks[:8]
                    ],
                },
                "candidates": candidate_summary,
            },
            ensure_ascii=False,
        )

    async def _run_attempt(
        self,
        hass: HomeAssistant,
        *,
        prompt: str,
        system_prompt: str,
        agent_id: str | None,
    ) -> dict[str, Any]:
        result = await async_converse(
            hass,
            text=prompt,
            conversation_id=None,
            context=Context(),
            language=hass.config.language,
            agent_id=agent_id,
            extra_system_prompt=system_prompt,
        )
        return result.response.as_dict()

    def _extract_json_payload(self, response_dict: dict[str, Any]) -> dict[str, Any] | None:
        for response_text in self._collect_text_candidates(response_dict):
            for candidate in self._extract_json_candidates(response_text):
                try:
                    payload = json.loads(candidate)
                except json.JSONDecodeError:
                    try:
                        payload = ast.literal_eval(candidate)
                    except (SyntaxError, ValueError):
                        continue
                if isinstance(payload, dict):
                    return payload
        return None

    def _collect_text_candidates(self, value: Any) -> list[str]:
        candidates: list[str] = []

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                speech = node.get("speech")
                if isinstance(speech, dict):
                    plain = speech.get("plain")
                    if isinstance(plain, dict):
                        plain_speech = plain.get("speech")
                        if isinstance(plain_speech, str) and plain_speech.strip():
                            candidates.append(plain_speech.strip())
                for nested_key in ("text", "response_text", "output_text", "content"):
                    nested_value = node.get(nested_key)
                    if isinstance(nested_value, str) and nested_value.strip():
                        candidates.append(nested_value.strip())
                for item in node.values():
                    visit(item)
                return
            if isinstance(node, list):
                for item in node:
                    visit(item)
                return
            if isinstance(node, str) and node.strip():
                candidates.append(node.strip())

        visit(value)
        seen: set[str] = set()
        deduped: list[str] = []
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            deduped.append(candidate)
        return deduped

    def _extract_json_candidates(self, response_text: str) -> list[str]:
        candidates: list[str] = []
        for fenced_match in re.finditer(r"```(?:json|JSON)?\s*([\s\S]*?)\s*```", response_text):
            block = fenced_match.group(1).strip()
            if block:
                candidates.append(block)
                balanced = self._extract_balanced_json_object(block)
                if balanced and balanced != block:
                    candidates.append(balanced)

        balanced_response = self._extract_balanced_json_object(response_text)
        if balanced_response:
            candidates.append(balanced_response)
        return candidates

    def _extract_balanced_json_object(self, response_text: str) -> str | None:
        start = response_text.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(response_text)):
            char = response_text[index]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return response_text[start : index + 1]
        return None

    def _coerce_index_list(self, value: Any) -> list[int]:
        if not isinstance(value, list):
            return []
        indexes: list[int] = []
        seen: set[int] = set()
        for item in value:
            try:
                index = int(item)
            except (TypeError, ValueError):
                continue
            if index <= 0 or index in seen:
                continue
            seen.add(index)
            indexes.append(index)
        return indexes

    def _coerce_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
        return result

    def _candidate_identity(self, candidate: CandidateTrack) -> str:
        if candidate.uri:
            return candidate.uri
        artist = candidate.artist or ""
        return f"{candidate.name.lower()}::{artist.lower()}"
