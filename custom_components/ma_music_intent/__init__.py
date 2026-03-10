from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MODE
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv

from .const import DEFAULT_CURATION_MODE, DEFAULT_MODE, DOMAIN, SERVICE_BUILD_QUEUE, SUPPORTED_CURATION_MODES
from .service import MusicIntentService

DATA_SERVICE_REGISTERED = "service_registered"

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("prompt"): cv.string,
        vol.Optional("count"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        vol.Optional("target_player"): cv.string,
        vol.Optional(CONF_MODE, default=DEFAULT_MODE): cv.string,
        vol.Optional("curation_mode", default=DEFAULT_CURATION_MODE): vol.In(SUPPORTED_CURATION_MODES),
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    await _async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True


async def _async_register_services(hass: HomeAssistant) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_SERVICE_REGISTERED):
        return

    service = MusicIntentService()

    async def handle_build_queue(call: ServiceCall) -> dict[str, object]:
        data = call.data
        return await service.build_queue(
            hass,
            prompt=data["prompt"],
            count=data.get("count"),
            target_player=data.get("target_player"),
            mode=data.get(CONF_MODE),
            curation_mode=data.get("curation_mode"),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_BUILD_QUEUE,
        handle_build_queue,
        schema=SERVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    domain_data[DATA_SERVICE_REGISTERED] = True
