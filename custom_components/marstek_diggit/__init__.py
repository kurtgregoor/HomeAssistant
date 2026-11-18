"""Home Assistant actions for the Marstek battery."""

from asyncio import Lock
from pathlib import Path

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store

from .client import DAY_BITS, MODE_CONFIG, MarstekClient, MarstekError

from .passive import PassiveControl, passive_store
from .controller import register_energy_actions
from .tariffs import register_tariff_actions

DOMAIN = "marstek_diggit"
TARGET = vol.Optional("config_entry_id")
SLOT = vol.All(int, vol.Range(min=1, max=9))
POWER = vol.All(int, vol.Range(min=-2500, max=2500))
TIME = vol.Match(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
ACTIVATE = vol.Optional("activate_manual", default=False)

SCHEMAS = {
    "get_slots": vol.Schema({TARGET: str}),
    "get_status": vol.Schema({TARGET: str}),
    "get_device_info": vol.Schema({TARGET: str}),
    "set_mode": vol.Schema({TARGET: str, vol.Required("mode"): vol.In(MODE_CONFIG)}),
    "set_passive": vol.Schema({
        TARGET: str,
        vol.Optional("source"): vol.In(("energy_program",)),
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
    hass.data.setdefault(DOMAIN, {})
    load_tariffs = register_tariff_actions(hass, DOMAIN)
    energy_controller = await register_energy_actions(hass, DOMAIN, load_tariffs)
    slot_store = Store(hass, 1, f"{DOMAIN}.slots")
    slot_lock = Lock()
    card_file = str(Path(__file__).with_name("marstek-diggit-card.js"))
    await hass.http.async_register_static_paths([
        StaticPathConfig("/marstek_diggit/marstek-diggit-card.js", card_file, False),
        StaticPathConfig("/marstek_diggit/dashboard-0.1.6.js", card_file, False),
        StaticPathConfig("/marstek_diggit/dashboard-0.1.7.js", card_file, False),
        StaticPathConfig("/marstek_diggit/dashboard-0.1.8.js", card_file, False),
        StaticPathConfig("/marstek_diggit/dashboard-0.1.9.js", card_file, False),
        StaticPathConfig("/marstek_diggit/dashboard-0.1.10.js", card_file, False),
        StaticPathConfig("/marstek_diggit/dashboard-0.1.11.js", card_file, False),
        StaticPathConfig("/marstek_diggit/dashboard-0.1.12.js", card_file, False),
        StaticPathConfig("/marstek_diggit/dashboard-0.1.13.js", card_file, False),
        StaticPathConfig("/marstek_diggit/dashboard-0.1.14.js", card_file, False),
        StaticPathConfig("/marstek_diggit/dashboard-0.1.15.js", card_file, False),
        StaticPathConfig("/marstek_diggit/dashboard-0.1.16.js", card_file, False),
    ])

    async def handle(call):
        batteries = hass.data[DOMAIN]
        data = call.data
        entry_id = data.get("config_entry_id")
        if entry_id is None and len(batteries) == 1:
            entry_id = next(iter(batteries))
        if entry_id not in batteries:
            raise HomeAssistantError("Selecteer een geconfigureerde Marstek-batterij.")

        if call.service not in {"get_status", "get_device_info", "get_slots"} and energy_controller.owns(entry_id):
            raise HomeAssistantError("Schakel eerst de actieve Energy Planner uit voor deze batterij.")
        battery = batteries[entry_id]
        try:
            if call.service == "get_slots":
                async with slot_lock:
                    return {"slots": (await slot_store.async_load() or {}).get(entry_id, {})}
            if call.service == "get_status":
                return await battery.get_status()
            if call.service == "get_device_info":
                return await battery.client.get_device_info()
            if call.service == "set_mode":
                await battery.set_mode(data["mode"])
            elif call.service == "set_passive":
                await battery.set_passive(data["power"], data["duration_seconds"], data.get("source"))
            else:
                async with slot_lock:
                    await battery.write_slot(_slot_payload(data), data["activate_manual"])
                    slots = await slot_store.async_load() or {}
                    battery_slots = slots.setdefault(entry_id, {})
                    slot = str(data["slot"])
                    if call.service == "disable_slot":
                        battery_slots.setdefault(slot, {})["enabled"] = False
                    else:
                        battery_slots[slot] = {
                            key: data[key]
                            for key in ("start_time", "end_time", "days", "power", "action", "enabled")
                            if key in data
                        }
                    await slot_store.async_save(slots)
        except MarstekError as exc:
            raise HomeAssistantError(str(exc)) from exc

    for action, schema in SCHEMAS.items():
        hass.services.async_register(
            DOMAIN, action, handle, schema=schema,
            supports_response=(
                SupportsResponse.ONLY
                if action in {"get_status", "get_device_info", "get_slots"}
                else SupportsResponse.NONE
            ),
        )
    return True


async def async_setup_entry(hass, entry):
    client = MarstekClient(entry.data[CONF_HOST], entry.data[CONF_PORT])
    store = passive_store(hass, DOMAIN, entry.entry_id)
    battery = PassiveControl(hass, client, store, entry.entry_id)
    await battery.async_load()
    hass.data[DOMAIN][entry.entry_id] = battery
    return True


async def async_unload_entry(hass, entry):
    battery = hass.data[DOMAIN].pop(entry.entry_id)
    await battery.async_unload()
    return True


async def async_remove_entry(hass, entry):
    await passive_store(hass, DOMAIN, entry.entry_id).async_remove()
