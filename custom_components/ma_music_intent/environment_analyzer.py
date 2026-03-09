from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import MUSIC_ASSISTANT_CANDIDATE_DOMAINS
from .models import EnvironmentSnapshot, ProviderSnapshot

_CAPABILITY_MAP = {
    "search": "search",
    "get_library": "library",
    "browse": "library",
    "play_media": "playback",
    "add_to_queue": "queue",
    "get_queue": "queue",
    "radio_mode": "radio",
    "recommendations": "recommendations",
    "similar_tracks": "similar_tracks",
}


class EnvironmentAnalyzer:
    async def analyze(self, hass: HomeAssistant) -> EnvironmentSnapshot:
        providers: list[ProviderSnapshot] = []
        services = hass.services.async_services()
        for domain in MUSIC_ASSISTANT_CANDIDATE_DOMAINS:
            domain_services = services.get(domain)
            if not domain_services:
                continue
            service_names = set(domain_services)
            capabilities = {cap for service, cap in _CAPABILITY_MAP.items() if service in service_names}
            providers.append(
                ProviderSnapshot(
                    domain=domain,
                    services=service_names,
                    capabilities=capabilities,
                )
            )

        has_recommendation_provider = any(
            {"recommendations", "radio", "similar_tracks"} & provider.capabilities for provider in providers
        )
        has_streaming_provider = any("search" in provider.capabilities for provider in providers)
        return EnvironmentSnapshot(
            providers=providers,
            has_recommendation_provider=has_recommendation_provider,
            has_streaming_provider=has_streaming_provider,
            music_assistant_domain=providers[0].domain if providers else None,
        )
