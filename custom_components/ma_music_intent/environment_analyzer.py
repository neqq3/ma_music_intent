from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import MUSIC_ASSISTANT_CANDIDATE_DOMAINS
from .models import EnvironmentSnapshot, ProviderSnapshot

_HA_SERVICE_CAPABILITY_MAP = {
    "search": "search",
    "get_library": "library",
    "browse": "library",
    "play_media": "playback",
    "add_to_queue": "queue",
    "get_queue": "queue",
    "transfer_queue": "queue",
    "radio_mode": "radio",
    "recommendations": "recommendations",
    "similar_tracks": "similar_tracks",
    "dynamic_tracks": "dynamic_tracks",
}

_MA_FEATURE_CAPABILITY_MAP = {
    "search": "search",
    "browse": "library",
    "recommendations": "recommendations",
    "similar_tracks": "similar_tracks",
    "library_artists": "library",
    "library_albums": "library",
    "library_tracks": "library",
    "library_playlists": "library",
    "library_radios": "library",
}

_RECOMMENDATION_CAPABILITIES = {"recommendations", "similar_tracks", "radio", "dynamic_tracks"}


class EnvironmentAnalyzer:
    async def analyze(self, hass: HomeAssistant) -> EnvironmentSnapshot:
        services = hass.services.async_services()
        providers: list[ProviderSnapshot] = []
        aggregate_domains: dict[str, ProviderSnapshot] = {}

        for domain in MUSIC_ASSISTANT_CANDIDATE_DOMAINS:
            domain_services = services.get(domain)
            if not domain_services:
                continue
            service_names = set(domain_services)
            capabilities = {cap for service, cap in _HA_SERVICE_CAPABILITY_MAP.items() if service in service_names}
            snapshot = ProviderSnapshot(
                domain=domain,
                instance_id=domain,
                name=domain,
                service_domain=domain,
                services=service_names,
                capabilities=capabilities,
            )
            aggregate_domains[domain] = snapshot

        mass_entry = next(
            (
                entry
                for entry in hass.config_entries.async_entries("music_assistant")
                if entry.state is ConfigEntryState.LOADED and getattr(entry, "runtime_data", None) is not None
            ),
            None,
        )
        mass = getattr(getattr(mass_entry, "runtime_data", None), "mass", None)
        if mass is not None:
            service_domain = next(iter(aggregate_domains), "music_assistant")
            aggregate_snapshot = aggregate_domains.get(
                service_domain,
                ProviderSnapshot(
                    domain=service_domain,
                    instance_id=service_domain,
                    name=service_domain,
                    service_domain=service_domain,
                ),
            )
            service_names = aggregate_snapshot.services
            aggregate_capabilities = set(aggregate_snapshot.capabilities)
            for provider in mass.providers:
                if not provider.available or str(provider.type) != "music":
                    continue
                capabilities = self._map_mass_provider_capabilities(provider.supported_features)
                aggregate_capabilities.update(capabilities)
                providers.append(
                    ProviderSnapshot(
                        domain=provider.domain,
                        instance_id=provider.instance_id,
                        name=provider.name,
                        service_domain=service_domain,
                        services=set(service_names),
                        capabilities=capabilities,
                    )
                )
            aggregate_snapshot.capabilities = aggregate_capabilities
            aggregate_domains[service_domain] = aggregate_snapshot

        providers.extend(
            snapshot for snapshot in aggregate_domains.values() if snapshot.domain not in {provider.domain for provider in providers}
        )

        has_recommendation_provider = any(_RECOMMENDATION_CAPABILITIES & provider.capabilities for provider in providers)
        has_streaming_provider = any("search" in provider.capabilities for provider in providers)
        music_assistant_domain = next(iter(aggregate_domains), providers[0].service_domain if providers else None)
        return EnvironmentSnapshot(
            providers=providers,
            has_recommendation_provider=has_recommendation_provider,
            has_streaming_provider=has_streaming_provider,
            music_assistant_domain=music_assistant_domain,
        )

    def _map_mass_provider_capabilities(self, supported_features: set[object]) -> set[str]:
        feature_names = {str(feature) for feature in supported_features}
        capabilities = {cap for feature, cap in _MA_FEATURE_CAPABILITY_MAP.items() if feature in feature_names}
        if "recommendations" in feature_names:
            capabilities.add("dynamic_tracks")
        if "similar_tracks" in feature_names:
            capabilities.add("dynamic_tracks")
        return capabilities
