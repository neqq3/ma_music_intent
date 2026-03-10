from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any

from homeassistant.components.conversation.agent_manager import async_converse
from homeassistant.core import Context, HomeAssistant

from .ai_prompt import build_ai_system_prompt
from .const import DEFAULT_COUNT, DEFAULT_MODE, SUPPORTED_MODES
from .models import EnvironmentSnapshot, MusicIntent, SuggestedTrack

LOGGER = logging.getLogger(__name__)


class AIIntentParser:
    """AI-first intent parser using Home Assistant conversation agents."""

    async def parse(
        self,
        hass: HomeAssistant,
        *,
        prompt: str,
        environment: EnvironmentSnapshot,
        count: int | None = None,
        target_player: str | None = None,
        mode: str | None = None,
        agent_id: str | None = None,
    ) -> tuple[MusicIntent, dict[str, Any]]:
        system_prompt = build_ai_system_prompt(
            prompt=prompt,
            environment=environment,
            count=count,
            target_player=target_player,
            mode=mode,
        )
        decision_trace: list[dict[str, str]] = []
        enrich_trigger_reason: str | None = None
        enrich_result: str | None = None
        final_failure_reason: str | None = None

        initial_response = await self._run_attempt(
            hass,
            prompt=prompt,
            system_prompt=system_prompt,
            agent_id=agent_id,
        )
        conversation_error_code = self._extract_conversation_error_code(initial_response)
        initial_texts = self._collect_text_candidates(initial_response)
        initial_payload_raw = self._extract_json_payload(initial_response)
        initial_payload = self._normalize_payload(initial_payload_raw) if initial_payload_raw is not None else None
        ignored_conversation_error = bool(conversation_error_code and initial_payload is not None)

        decision_trace.append(
            {
                "step": "initial_attempt",
                "result": "json_present" if initial_payload is not None else "json_missing",
                "reason": (
                    "Parsed AI JSON from conversation response."
                    if initial_payload is not None
                    else "No parseable AI JSON found in conversation response."
                ),
            }
        )

        payload = initial_payload
        parse_stage = "direct" if payload is not None else "repair"
        response_dict = initial_response
        response_text = initial_texts[0] if initial_texts else None

        if payload is not None and self._has_sufficient_proposal(payload):
            decision_trace.append(
                {
                    "step": "proposal_gate",
                    "result": "accepted",
                    "reason": "Initial AI JSON contained sufficient concrete proposal entities.",
                }
            )
        else:
            if payload is None:
                decision_trace.append(
                    {
                        "step": "proposal_gate",
                        "result": "repair_needed",
                        "reason": "Initial AI response had no parseable JSON payload.",
                    }
                )
            else:
                enrich_trigger_reason = "initial_json_weak_proposal"
                decision_trace.append(
                    {
                        "step": "proposal_gate",
                        "result": "enrich_needed",
                        "reason": "Initial AI JSON parsed, but concrete seeds/candidates were insufficient.",
                    }
                )

            if payload is None and response_text:
                repair_response = await self._run_attempt(
                    hass,
                    prompt=(
                        "Convert the following music recommendation proposal into one JSON object only. "
                        "Keep any concrete artists/tracks if present. Do not add explanations.\n\n"
                        f"Original user request:\n{prompt}\n\n"
                        f"Previous AI text:\n{response_text}"
                    ),
                    system_prompt=system_prompt,
                    agent_id=agent_id,
                )
                repair_payload_raw = self._extract_json_payload(repair_response)
                repair_payload = self._normalize_payload(repair_payload_raw) if repair_payload_raw is not None else None
                response_dict = repair_response
                repair_texts = self._collect_text_candidates(repair_response)
                response_text = repair_texts[0] if repair_texts else response_text
                if repair_payload is not None:
                    payload = repair_payload
                    parse_stage = "repair"
                    decision_trace.append(
                        {
                            "step": "repair_attempt",
                            "result": "json_present",
                            "reason": "Repair attempt produced parseable AI JSON.",
                        }
                    )
                else:
                    decision_trace.append(
                        {
                            "step": "repair_attempt",
                            "result": "json_missing",
                            "reason": "Repair attempt still did not return parseable AI JSON.",
                        }
                    )

            if payload is not None and not self._has_sufficient_proposal(payload):
                enrich_trigger_reason = enrich_trigger_reason or "repair_json_weak_proposal"
                enrich_response = await self._run_attempt(
                    hass,
                    prompt=(
                        "Your previous JSON is too abstract. Return one JSON object only and enrich it with concrete music proposals.\n\n"
                        "Requirements:\n"
                        "- include at least 2 seed_artists or at least 3 candidate_tracks\n"
                        "- keep intent constraints aligned with the request\n"
                        "- do not call Home Assistant actions, tools, intents, or target entities\n"
                        "- do not add explanations\n\n"
                        f"Original user request:\n{prompt}\n\n"
                        f"Previous JSON:\n{json.dumps(payload, ensure_ascii=False)}"
                    ),
                    system_prompt=system_prompt,
                    agent_id=agent_id,
                )
                enrich_payload_raw = self._extract_json_payload(enrich_response)
                enrich_payload = self._normalize_payload(enrich_payload_raw) if enrich_payload_raw is not None else None
                response_dict = enrich_response
                enrich_texts = self._collect_text_candidates(enrich_response)
                response_text = enrich_texts[0] if enrich_texts else response_text
                if enrich_payload is not None and self._has_sufficient_proposal(enrich_payload):
                    payload = enrich_payload
                    parse_stage = "enrich"
                    enrich_result = "accepted"
                    decision_trace.append(
                        {
                            "step": "enrich_attempt",
                            "result": "accepted",
                            "reason": "Enrich attempt returned parseable AI JSON with sufficient concrete proposal entities.",
                        }
                    )
                elif enrich_payload is not None:
                    payload = enrich_payload
                    parse_stage = "weak_proposal"
                    enrich_result = "weak_proposal"
                    final_failure_reason = "enrich_json_still_too_abstract"
                    decision_trace.append(
                        {
                            "step": "enrich_attempt",
                            "result": "weak_proposal",
                            "reason": "Enrich attempt returned JSON, but proposal remained too abstract.",
                        }
                    )
                else:
                    parse_stage = "salvaged"
                    enrich_result = "json_missing"
                    final_failure_reason = "enrich_no_parseable_json"
                    decision_trace.append(
                        {
                            "step": "enrich_attempt",
                            "result": "json_missing",
                            "reason": "Enrich attempt did not return parseable AI JSON.",
                        }
                    )

        if payload is None or parse_stage == "salvaged":
            payload = self._infer_payload_from_prompt(prompt, count=count)
            parse_stage = "salvaged"
            final_failure_reason = final_failure_reason or "no_parseable_ai_json"
            decision_trace.append(
                {
                    "step": "salvage_fallback",
                    "result": "used_prompt_salvage",
                    "reason": "Fell back to prompt-based salvage because AI-origin proposal could not be accepted.",
                }
            )

        payload = self._normalize_payload(payload)
        intent = self._build_intent(
            prompt=prompt,
            payload=payload,
            count=count,
            target_player=target_player,
            mode=mode,
            parse_source=self._resolve_parse_source(parse_stage),
        )
        debug = {
            "agent_id": agent_id,
            "conversation_response": response_dict,
            "response_text": response_text,
            "parsed_payload": payload,
            "input_source": {
                "prompt": prompt,
                "conversation_used": True,
                "raw_ai_text_present": bool(initial_texts),
                "raw_ai_json_present": initial_payload is not None,
            },
            "decision_trace": decision_trace,
            "parse_stage": parse_stage,
            "parse_source": self._resolve_parse_source(parse_stage),
            "proposal_quality": self._proposal_quality_summary(payload),
            "conversation_error_code": conversation_error_code,
            "ignored_conversation_error": ignored_conversation_error,
            "enrich_trigger_reason": enrich_trigger_reason,
            "enrich_result": enrich_result,
            "final_failure_reason": final_failure_reason,
        }
        return intent, debug

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

    def _build_intent(
        self,
        *,
        prompt: str,
        payload: dict[str, Any],
        count: int | None,
        target_player: str | None,
        mode: str | None,
        parse_source: str,
    ) -> MusicIntent:
        normalized_mode = mode or DEFAULT_MODE
        if normalized_mode not in SUPPORTED_MODES:
            normalized_mode = DEFAULT_MODE

        normalized_payload = self._normalize_payload(payload)
        intent = MusicIntent(
            prompt=prompt,
            query=self._resolve_query(prompt, normalized_payload),
            count=self._coerce_count(normalized_payload.get("count"), count or DEFAULT_COUNT),
            mode=normalized_mode,
            target_player=target_player,
            source_scope=self._coerce_source_scope(normalized_payload.get("source_scope")),
            allow_external_discovery=bool(normalized_payload.get("allow_external_discovery", True)),
            language_preference=self._coerce_string_list(normalized_payload.get("language_preference")),
            mood=self._coerce_string_list(normalized_payload.get("mood")),
            atmosphere=self._coerce_string_list(normalized_payload.get("atmosphere")),
            energy=self._coerce_ratio(normalized_payload.get("energy")),
            freshness=self._coerce_ratio(normalized_payload.get("freshness")),
            familiarity=self._coerce_ratio(normalized_payload.get("familiarity")),
            exclude=self._coerce_string_list(normalized_payload.get("exclude")),
            preferred_eras=self._coerce_string_list(normalized_payload.get("preferred_eras")),
            preferred_artists=self._coerce_string_list(normalized_payload.get("preferred_artists")),
            avoided_artists=self._coerce_string_list(normalized_payload.get("avoided_artists")),
            seed_artists=self._coerce_string_list(normalized_payload.get("seed_artists")),
            seed_tracks=self._coerce_string_list(normalized_payload.get("seed_tracks")),
            candidate_tracks=self._coerce_tracks(normalized_payload.get("candidate_tracks")),
            candidate_artists=self._coerce_string_list(normalized_payload.get("candidate_artists")),
            keywords=self._coerce_string_list(normalized_payload.get("keywords")),
            exploration_notes=self._coerce_string_list(normalized_payload.get("exploration_notes")),
            provider_directions=self._coerce_string_list(normalized_payload.get("provider_directions")),
            continuity=self._coerce_optional_string(normalized_payload.get("continuity")),
            queue_direction=self._coerce_optional_string(normalized_payload.get("queue_direction")),
            strategy_hint=self._coerce_optional_string(normalized_payload.get("strategy_hint")),
            parse_source=parse_source,
        )
        if not intent.keywords:
            intent.keywords = [intent.query]
        return intent

    def _extract_json_payload(self, response_dict: dict[str, Any]) -> dict[str, Any] | None:
        for response_text in self._collect_text_candidates(response_dict):
            candidate = self._extract_json_object_text(response_text)
            if candidate is None:
                continue
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

    def _resolve_query(self, prompt: str, payload: dict[str, Any]) -> str:
        queries = [
            *[
                f"{track.name} {track.artist}".strip() if track.artist else track.name
                for track in self._coerce_tracks(payload.get("candidate_tracks"))
            ],
            *self._coerce_string_list(payload.get("seed_tracks")),
            *self._coerce_string_list(payload.get("keywords")),
            self._coerce_optional_string(payload.get("queue_direction")) or "",
            prompt,
        ]
        for query in queries:
            if query and query.strip():
                return query.strip()
        return prompt

    def _coerce_tracks(self, value: Any) -> list[SuggestedTrack]:
        if not isinstance(value, list):
            return []
        tracks: list[SuggestedTrack] = []
        for row in value:
            if isinstance(row, str):
                name, artist = self._split_track_string(row)
                if name:
                    tracks.append(SuggestedTrack(name=name, artist=artist))
                continue
            if not isinstance(row, dict):
                continue
            name = self._coerce_optional_string(row.get("name") or row.get("title"))
            if not name:
                continue
            artist = self._coerce_optional_string(row.get("artist") or row.get("subtitle"))
            tracks.append(SuggestedTrack(name=name, artist=artist))
        return tracks

    def _coerce_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                items.append(item.strip())
                continue
            if isinstance(item, dict):
                candidate = self._coerce_optional_string(
                    item.get("name") or item.get("title") or item.get("artist") or item.get("value")
                )
                if candidate:
                    items.append(candidate)
        return items

    def _coerce_count(self, value: Any, default: int) -> int:
        try:
            return max(1, min(100, int(value)))
        except (TypeError, ValueError):
            return default

    def _coerce_ratio(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, numeric))

    def _coerce_optional_string(self, value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _coerce_source_scope(self, value: Any) -> str:
        allowed = {"library_only", "provider_preferred", "auto", "mixed"}
        if isinstance(value, str):
            normalized = value.strip()
            if normalized in allowed:
                return normalized
        return "auto"

    def _resolve_parse_source(self, parse_stage: str) -> str:
        if parse_stage == "salvaged":
            return "ai_salvaged"
        if parse_stage == "weak_proposal":
            return "ai_weak"
        return "ai"

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

        visit(value)
        seen: set[str] = set()
        deduped: list[str] = []
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            deduped.append(candidate)
        return deduped

    def _extract_json_object_text(self, response_text: str) -> str | None:
        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if fenced_match:
            return fenced_match.group(1)

        start = response_text.find("{")
        if start == -1:
            return None

        depth = 0
        for index in range(start, len(response_text)):
            char = response_text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return response_text[start : index + 1]
        return None

    def _extract_conversation_error_code(self, response_dict: dict[str, Any]) -> str | None:
        error = response_dict.get("error")
        if isinstance(error, dict):
            code = error.get("code") or error.get("error_code")
            if isinstance(code, str) and code.strip():
                return code.strip()
        if isinstance(error, str) and error.strip():
            return error.strip()
        return None

    def _infer_payload_from_prompt(self, prompt: str, count: int | None) -> dict[str, Any]:
        normalized_prompt = prompt.strip()
        lowered = normalized_prompt.lower()
        payload: dict[str, Any] = {
            "count": count or self._extract_count_from_prompt(normalized_prompt) or DEFAULT_COUNT,
            "source_scope": "auto",
            "allow_external_discovery": True,
            "language_preference": [],
            "mood": [],
            "atmosphere": [],
            "energy": None,
            "freshness": None,
            "familiarity": None,
            "exclude": [],
            "seed_artists": [],
            "seed_tracks": [],
            "candidate_tracks": [],
            "candidate_artists": [],
            "keywords": self._build_prompt_keywords(normalized_prompt),
            "exploration_notes": ["Prompt-only salvage because no acceptable AI proposal was retained."],
            "queue_direction": normalized_prompt,
            "strategy_hint": "search_expand",
        }
        if "中文" in normalized_prompt or "chinese" in lowered:
            payload["language_preference"] = ["zh"]
        if any(token in normalized_prompt for token in ("写代码", "coding", "code", "专注")):
            payload["mood"].append("focused")
            payload["atmosphere"].append("coding")
        if any(token in normalized_prompt for token in ("晚上", "深夜", "夜里", "late night", "night")):
            payload["atmosphere"].append("late_night")
        if any(token in normalized_prompt for token in ("别太吵", "不要太吵", "安静", "轻一点")):
            payload["mood"].append("calm")
            payload["energy"] = 0.35
            payload["exclude"].append("too_noisy")

        freshness, familiarity = self._extract_freshness_pair(normalized_prompt)
        if freshness is not None:
            payload["freshness"] = freshness
        if familiarity is not None:
            payload["familiarity"] = familiarity

        return payload

    def _extract_count_from_prompt(self, prompt: str) -> int | None:
        match = re.search(r"(\d{1,3})\s*首", prompt)
        if not match:
            return None
        return self._coerce_count(match.group(1), DEFAULT_COUNT)

    def _extract_freshness_pair(self, prompt: str) -> tuple[float | None, float | None]:
        match = re.search(r"([一二两三四五六七八九十\d])成新鲜([一二两三四五六七八九十\d])成熟悉", prompt)
        if match:
            return self._coerce_chinese_ratio(match.group(1)), self._coerce_chinese_ratio(match.group(2))

        freshness_match = re.search(r"([一二两三四五六七八九十\d])成新鲜", prompt)
        familiarity_match = re.search(r"([一二两三四五六七八九十\d])成熟悉", prompt)
        return (
            self._coerce_chinese_ratio(freshness_match.group(1)) if freshness_match else None,
            self._coerce_chinese_ratio(familiarity_match.group(1)) if familiarity_match else None,
        )

    def _coerce_chinese_ratio(self, value: str) -> float | None:
        mapping = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        if value.isdigit():
            number = int(value)
        else:
            number = mapping.get(value)
        if number is None:
            return None
        return max(0.0, min(1.0, number / 10))

    def _build_prompt_keywords(self, prompt: str) -> list[str]:
        keywords: list[str] = []
        for token in ("晚上", "深夜", "写代码", "中文", "安静", "别太吵", "新鲜", "熟悉"):
            if token in prompt:
                keywords.append(token)
        return keywords or [prompt]

    def _has_sufficient_proposal(self, payload: dict[str, Any]) -> bool:
        normalized = self._normalize_payload(payload)
        seed_artists = self._coerce_string_list(normalized.get("seed_artists"))
        seed_tracks = self._coerce_string_list(normalized.get("seed_tracks"))
        candidate_tracks = self._coerce_tracks(normalized.get("candidate_tracks"))
        candidate_artists = self._coerce_string_list(normalized.get("candidate_artists"))
        return bool(
            len(seed_artists) >= 2
            or len(candidate_tracks) >= 3
            or len(seed_tracks) >= 1
            or len(candidate_artists) >= 2
            or (len(seed_artists) >= 1 and len(candidate_tracks) >= 1)
        )

    def _proposal_quality_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_payload(payload)
        return {
            "seed_artists": len(self._coerce_string_list(normalized.get("seed_artists"))),
            "seed_tracks": len(self._coerce_string_list(normalized.get("seed_tracks"))),
            "candidate_tracks": len(self._coerce_tracks(normalized.get("candidate_tracks"))),
            "candidate_artists": len(self._coerce_string_list(normalized.get("candidate_artists"))),
            "keywords": self._coerce_string_list(normalized.get("keywords")),
            "sufficient": self._has_sufficient_proposal(normalized),
        }

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        request = payload.get("recommendation_request")
        recommendations = payload.get("concrete_recommendations")

        if isinstance(request, dict):
            normalized.setdefault("count", request.get("count"))
            normalized.setdefault("freshness", request.get("fresh_songs_ratio"))
            normalized.setdefault("familiarity", request.get("familiar_songs_ratio"))
            normalized.setdefault("energy", self._map_energy_level(request.get("energy_level")))
            normalized.setdefault(
                "language_preference",
                self._normalize_language_preference(request.get("language_priority")),
            )
            context = self._coerce_optional_string(request.get("context"))
            if context:
                normalized.setdefault("provider_directions", self._map_context_directions(context))
                mood, atmosphere = self._map_context_to_intent(context)
                if mood:
                    normalized.setdefault("mood", mood)
                if atmosphere:
                    normalized.setdefault("atmosphere", atmosphere)

        if isinstance(recommendations, dict):
            for field in (
                "seed_artists",
                "seed_tracks",
                "candidate_tracks",
                "candidate_artists",
                "keywords",
                "exploration_notes",
                "provider_directions",
            ):
                if field not in normalized and field in recommendations:
                    normalized[field] = recommendations[field]

        normalized["seed_artists"] = self._normalize_named_list(normalized.get("seed_artists"))
        normalized["seed_tracks"] = self._normalize_track_name_list(normalized.get("seed_tracks"))
        normalized["candidate_artists"] = self._normalize_named_list(normalized.get("candidate_artists"))
        normalized["candidate_tracks"] = self._normalize_track_objects(normalized.get("candidate_tracks"))
        normalized["preferred_artists"] = self._normalize_named_list(normalized.get("preferred_artists"))
        normalized["avoided_artists"] = self._normalize_named_list(normalized.get("avoided_artists"))
        normalized["keywords"] = self._normalize_named_list(normalized.get("keywords"))
        normalized["exploration_notes"] = self._normalize_named_list(normalized.get("exploration_notes"))
        normalized["provider_directions"] = self._normalize_named_list(normalized.get("provider_directions"))
        normalized["mood"] = self._normalize_named_list(normalized.get("mood"))
        normalized["atmosphere"] = self._normalize_named_list(normalized.get("atmosphere"))
        normalized["exclude"] = self._normalize_named_list(normalized.get("exclude"))
        normalized["preferred_eras"] = self._normalize_named_list(normalized.get("preferred_eras"))
        if isinstance(normalized.get("language_preference"), str):
            normalized["language_preference"] = self._normalize_language_preference(normalized.get("language_preference"))
        return normalized

    def _normalize_named_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                items.append(item.strip())
            elif isinstance(item, dict):
                candidate = self._coerce_optional_string(
                    item.get("name") or item.get("title") or item.get("artist") or item.get("value")
                )
                if candidate:
                    items.append(candidate)
        return items

    def _normalize_track_name_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        names: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                names.append(item.strip())
            elif isinstance(item, dict):
                candidate = self._coerce_optional_string(item.get("name") or item.get("title"))
                if candidate:
                    names.append(candidate)
        return names

    def _normalize_track_objects(self, value: Any) -> list[dict[str, str | None]]:
        if not isinstance(value, list):
            return []
        tracks: list[dict[str, str | None]] = []
        for item in value:
            if isinstance(item, str):
                name, artist = self._split_track_string(item)
                if name:
                    tracks.append({"name": name, "artist": artist})
                continue
            if not isinstance(item, dict):
                continue
            name = self._coerce_optional_string(item.get("name") or item.get("title"))
            if not name:
                continue
            artist = self._coerce_optional_string(item.get("artist") or item.get("subtitle"))
            tracks.append({"name": name, "artist": artist})
        return tracks

    def _split_track_string(self, value: str) -> tuple[str | None, str | None]:
        normalized = value.strip()
        if not normalized:
            return None, None
        for separator in (" - ", " – ", " — "):
            if separator in normalized:
                name, artist = normalized.split(separator, 1)
                return name.strip() or None, artist.strip() or None
        return normalized, None

    def _map_energy_level(self, value: Any) -> float | None:
        if not isinstance(value, str):
            return self._coerce_ratio(value)
        mapping = {"low": 0.3, "medium": 0.55, "high": 0.8}
        return mapping.get(value.strip().lower())

    def _normalize_language_preference(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return self._normalize_named_list(value)
        if not isinstance(value, str):
            return []
        lowered = value.strip().lower()
        if lowered in {"chinese", "zh", "zh-cn", "mandarin"}:
            return ["zh"]
        if lowered:
            return [lowered]
        return []

    def _map_context_directions(self, value: str) -> list[str]:
        mapping = {
            "coding_at_night": ["coding", "late_night"],
            "night_coding": ["coding", "late_night"],
        }
        return mapping.get(value.strip().lower(), [value.strip()])

    def _map_context_to_intent(self, value: str) -> tuple[list[str], list[str]]:
        lowered = value.strip().lower()
        if lowered in {"coding_at_night", "night_coding"}:
            return ["focused"], ["coding", "late_night"]
        return [], []
