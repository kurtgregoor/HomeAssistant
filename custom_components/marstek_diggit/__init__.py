"""Home Assistant actions for the Marstek battery."""

import voluptuous as vol

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .client import DAY_BITS, MODE_CONFIG, MarstekClient, MarstekError

DOMAIN = "marstek_diggit"
TARGET = vol.Optional("config_entry_id")
SLOT = vol.All(int, vol.Range(min=1, max=9))
POWER = vol.All(int, vol.Range(min=-2500, max=2500))
TIME = vol.Match(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
ACTIVATE = vol.Optional("activate_manual", default=False)

SCHEMAS = {
    "get_status": vol.Schema({TARGET: str}),
    "set_mode": vol.Schema({TARGET: str, vol.Required("mode"): vol.In(MODE_CONFIG)}),
    "set_passive": vol.Schema({
        TARGET: str,
        vol.Required("power"): POWER,
        vol.Required("duration_seconds"): vol.All(int, vol.Range(min=60, max=86400)),
    }),
    "set_slot": vol.Schema({
        TARGET: str,
        vol.Required("slot"): SLOT,
        vol.Required("start_time"): TIME,
        vol.Required("end_time"): TIME,
        vol.Optional("days", default=list(DAY_BITS)): vol.All(
            [vol.In(DAY_BITS)], vol.Length(min=1), vol.Unique()
        ),
        vol.Required("power"): POWER,
        vol.Optional("action"): vol.In(("charge", "discharge", "auto")),
        vol.Optional("enabled", default=True): cv.boolean,
        ACTIVATE: cv.boolean,
    }),
    "disable_slot": vol.Schema({TARGET: str, vol.Required("slot"): SLOT, ACTIVATE: cv.boolean}),
}


def _slot_payload(data):
    if "start_time" not in data:
        return {
            "time_num": data["slot"], "start_time": "00:00", "end_time": "00:00",
            "week_set": 127, "power": 0, "enable": 0,
        }

    power = data["power"]
    action = data.get("action")
    if action == "charge":
        power = -abs(power)
    elif action == "discharge":
        power = abs(power)
    elif action == "auto" or (action is None and power == 0):
        power = -1

    return {
        "time_num": data["slot"],
        "start_time": data["start_time"],
        "end_time": data["end_time"],
        "week_set": sum(DAY_BITS[day] for day in data["days"]),
        "power": power,
        "enable": int(data["enabled"]),
    }


async def async_setup(hass, config):
    async def handle(call):
        clients = hass.data[DOMAIN]
        data = call.data
        entry_id = data.get("config_entry_id")
        if entry_id is None and len(clients) == 1:
            entry_id = next(iter(clients))
        if entry_id not in clients:
            raise HomeAssistantError("Selecteer een geconfigureerde Marstek-batterij.")

        client = clients[entry_id]
        try:
            if call.service == "get_status":
                return await client.get_status()
            if call.service == "set_mode":
                await client.set_mode(data["mode"])
            elif call.service == "set_passive":
                await client.set_passive(data["power"], data["duration_seconds"])
            else:
                await client.write_slot(_slot_payload(data), data["activate_manual"])
        except MarstekError as exc:
            raise HomeAssistantError(str(exc)) from exc

    hass.data.setdefault(DOMAIN, {})
    for action, schema in SCHEMAS.items():
        hass.services.async_register(
            DOMAIN, action, handle, schema=schema,
            supports_response=SupportsResponse.ONLY if action == "get_status" else SupportsResponse.NONE,
        )
    return True


async def async_setup_entry(hass, entry):
    hass.data[DOMAIN][entry.entry_id] = MarstekClient(entry.data[CONF_HOST], entry.data[CONF_PORT])
    return True


async def async_unload_entry(hass, entry):
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
