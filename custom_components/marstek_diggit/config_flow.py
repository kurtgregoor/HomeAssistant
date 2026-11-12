"""Set up the battery through Home Assistant."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT

from . import DOMAIN
from .client import MarstekClient, MarstekError


class MarstekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip().lower()
            port = user_input[CONF_PORT]
            self._async_abort_entries_match({CONF_HOST: host, CONF_PORT: port})
            try:
                await MarstekClient(host, port).get_status()
            except MarstekError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"Marstek ({host}:{port})",
                    data={CONF_HOST: host, CONF_PORT: port},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): vol.All(str, str.strip, vol.Length(min=1)),
                vol.Required(CONF_PORT, default=30000): vol.All(int, vol.Range(min=1, max=65535)),
            }),
            errors=errors,
        )
