from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import CandidateTrack

_TRACK_MEDIA_TYPES = {"track", "song"}
_GROUP_KEYS = ("tracks", "artists", "albums", "playlists", "radio")


def normalize_search_result(
    search_payload: Any,
    *,
    provider_domain: str,
    fallback_query: str,
) -> list[CandidateTrack]:
    tracks: list[CandidateTrack] = []
    for media_type, rows in _iter_result_groups(search_payload):
        if media_type not in _TRACK_MEDIA_TYPES:
            continue
        for row in rows:
            candidate = _normalize_row(
                row,
                provider_domain=provider_domain,
                fallback_query=fallback_query,
                media_type_hint=media_type,
            )
            if candidate is None:
                continue
            tracks.append(candidate)
    return tracks


def summarize_search_payload(search_payload: Any) -> dict[str, Any]:
    if search_payload is None:
        return {"kind": "none"}
    if isinstance(search_payload, list):
        return {"kind": "list", "length": len(search_payload)}
    if not isinstance(search_payload, dict):
        return {"kind": type(search_payload).__name__}

    summary: dict[str, Any] = {
        "kind": "dict",
        "keys": sorted(search_payload.keys()),
    }
    for key in _GROUP_KEYS + ("items", "result", "results"):
        value = search_payload.get(key)
        if isinstance(value, list):
            summary[f"{key}_count"] = len(value)
        elif isinstance(value, dict):
            summary[f"{key}_keys"] = sorted(value.keys())
            items = value.get("items")
            if isinstance(items, list):
                summary[f"{key}_items_count"] = len(items)
    return summary


def _iter_result_groups(search_payload: Any) -> Iterable[tuple[str, list[Any]]]:
    if search_payload is None:
        return []
    if isinstance(search_payload, list):
        return [("track", search_payload)]
    if not isinstance(search_payload, dict):
        return []

    groups: list[tuple[str, list[Any]]] = []
    if "items" in search_payload and isinstance(search_payload["items"], list):
        groups.append((str(search_payload.get("media_type") or "track"), search_payload["items"]))

    for key in _GROUP_KEYS:
        value = search_payload.get(key)
        if isinstance(value, list):
            groups.append((key.rstrip("s"), value))
        elif isinstance(value, dict):
            items = value.get("items")
            if isinstance(items, list):
                groups.append((key.rstrip("s"), items))

    for key in ("result", "results"):
        value = search_payload.get(key)
        if isinstance(value, list):
            groups.append(("track", value))
        elif isinstance(value, dict):
            groups.extend(_iter_result_groups(value))

    if groups:
        return groups
    return [("track", [search_payload])]


def _normalize_row(
    row: Any,
    *,
    provider_domain: str,
    fallback_query: str,
    media_type_hint: str,
) -> CandidateTrack | None:
    source = row.get("media_item") if isinstance(row, dict) and isinstance(row.get("media_item"), dict) else row
    if not isinstance(source, dict):
        return None

    provider = _extract_provider(source) or provider_domain
    item_id = _string_or_none(source.get("item_id") or source.get("id"))
    uri = _string_or_none(source.get("uri"))
    media_type = str(source.get("media_type") or media_type_hint or "track")
    if media_type not in _TRACK_MEDIA_TYPES:
        return None

    return CandidateTrack(
        name=str(source.get("name") or source.get("title") or fallback_query),
        artist=_extract_artist(source),
        provider=provider,
        item_id=item_id,
        uri=uri,
        media_type=media_type,
        available=bool(source.get("available", True)),
        score=float(source.get("score") or source.get("confidence") or 0.0),
        metadata=row if isinstance(row, dict) else {"value": row},
    )


def _extract_artist(row: dict[str, Any]) -> str | None:
    artists = row.get("artists")
    if isinstance(artists, list) and artists:
        first = artists[0]
        if isinstance(first, dict):
            name = first.get("name")
            return str(name) if name else None
        return str(first)
    artist = row.get("artist")
    return str(artist) if artist else None


def _extract_provider(row: dict[str, Any]) -> str | None:
    for key in ("provider", "provider_instance", "provider_domain"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            for nested_key in ("domain", "instance_id", "provider_domain"):
                nested_value = value.get(nested_key)
                if nested_value:
                    return str(nested_value)
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
