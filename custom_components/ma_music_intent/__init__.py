from __future__ import annotations

import voluptuous as vol

from homeassistant.const import CONF_MODE
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv

from .const import DEFAULT_MODE, DOMAIN, SERVICE_BUILD_QUEUE
from .service import MusicIntentService

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("prompt"): cv.string,
        vol.Optional("count"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        vol.Optional("target_player"): cv.string,
        vol.Optional(CONF_MODE, default=DEFAULT_MODE): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    service = MusicIntentService()

    async def handle_build_queue(call: ServiceCall) -> dict[str, object]:
        data = call.data
        return await service.build_queue(
            hass,
            prompt=data["prompt"],
            count=data.get("count"),
            target_player=data.get("target_player"),
            mode=data.get(CONF_MODE),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_BUILD_QUEUE,
        handle_build_queue,
        schema=SERVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True
