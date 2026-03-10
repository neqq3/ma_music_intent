from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.assist_pipeline.pipeline import async_get_pipeline
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    BooleanSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_AGENT_ID, CONF_USE_CUSTOM_AGENT, DOMAIN


class MaMusicIntentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MA Music Intent."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return self.async_create_entry(title="MA Music Intent", data={})

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MaMusicIntentOptionsFlow(config_entry)


class MaMusicIntentOptionsFlow(OptionsFlow):
    """Options flow for MA Music Intent."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            use_custom_agent = bool(user_input.get(CONF_USE_CUSTOM_AGENT, False))
            agent_id = user_input.get(CONF_AGENT_ID) or ""

            if use_custom_agent and not agent_id:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._build_schema(user_input),
                    errors={CONF_AGENT_ID: "required"},
                )

            return self.async_create_entry(
                title="",
                data={
                    CONF_USE_CUSTOM_AGENT: use_custom_agent,
                    CONF_AGENT_ID: agent_id if use_custom_agent else "",
                },
            )

        suggested = {
            CONF_USE_CUSTOM_AGENT: self._config_entry.options.get(CONF_USE_CUSTOM_AGENT, False),
            CONF_AGENT_ID: self._config_entry.options.get(CONF_AGENT_ID, ""),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self._build_schema(suggested),
        )

    def _build_schema(self, suggested_values: dict[str, Any]) -> vol.Schema:
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Optional(CONF_USE_CUSTOM_AGENT, default=False): BooleanSelector(
                        BooleanSelectorConfig()
                    ),
                    vol.Optional(CONF_AGENT_ID, default=""): SelectSelector(
                        SelectSelectorConfig(
                            options=self._agent_options(),
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=False,
                            sort=True,
                        )
                    ),
                }
            ),
            suggested_values,
        )

    def _agent_options(self) -> list[SelectOptionDict]:
        options = [SelectOptionDict(label=self._inherit_default_label(), value="")]
        registry = er.async_get(self.hass)
        entries = sorted(
            (
                entry
                for entry in registry.entities.values()
                if entry.entity_id.startswith("conversation.") and not entry.disabled_by
            ),
            key=lambda entry: entry.entity_id,
        )
        for entry in entries:
            state = self.hass.states.get(entry.entity_id)
            label = (
                (state.attributes.get("friendly_name") if state else None)
                or entry.name
                or entry.original_name
                or entry.entity_id
            )
            options.append(SelectOptionDict(label=f"{label} ({entry.entity_id})", value=entry.entity_id))
        return options

    def _inherit_default_label(self) -> str:
        try:
            pipeline = async_get_pipeline(self.hass)
            engine = pipeline.conversation_engine
            if engine and engine != "conversation.home_assistant":
                return f"Inherit Assist default: {pipeline.name} ({engine})"
            return "Inherit Assist default: Home Assistant"
        except Exception:
            return "Inherit Assist default"
