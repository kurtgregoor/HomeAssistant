"""Persist the household's electricity tariff schedule."""

from decimal import Decimal, InvalidOperation
import re

import voluptuous as vol

from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

TARIFFS = {"peak": "Piek", "offpeak": "Dal", "super_offpeak": "Superdal"}
PROFILES = ("weekday", "weekend")
DAYS = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")
TIME = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
BLOCK = re.compile(rf"({TIME})\s*-\s*({TIME}|24:00)")


def price(value):
    try:
        amount = Decimal(value.strip().replace(",", "."))
    except InvalidOperation as exc:
        raise vol.Invalid("Vul een geldige prijs in €/kWh in.") from exc
    if not amount.is_finite() or amount < 0:
        raise vol.Invalid("Vul een eindige prijs van minstens € 0 in.")
    return format(amount, "f")


def validate_prices(values):
    return {kind: price(value) for kind, value in values.items()}


SCHEMA = vol.Schema({
    vol.Required("prices"): vol.All(
        {vol.Required(kind): vol.All(str, vol.Length(max=20), vol.Match(r"^[0-9]+(?:[.,][0-9]{1,4})?$"))
         for kind in TARIFFS},
        validate_prices,
    ),
    vol.Required("schedule"): {
        vol.Required(profile): {
            vol.Required(kind): vol.All([str], vol.Length(max=24))
            for kind in TARIFFS
        }
        for profile in PROFILES
    },
})


def minutes(value):
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def normalize_schedule(schedule):
    normalized = {profile: {kind: [] for kind in TARIFFS} for profile in PROFILES}
    parsed = {profile: [] for profile in PROFILES}
    for profile in PROFILES:
        label = "Werkdagen" if profile == "weekday" else "Weekend"
        for kind, blocks in schedule[profile].items():
            for block in blocks:
                match = BLOCK.fullmatch(block.strip())
                if not match:
                    raise HomeAssistantError(f"{label}, {TARIFFS[kind]}: gebruik UU:MM-UU:MM.")
                start, end = match.groups()
                if start == end:
                    raise HomeAssistantError(f"{label}, {TARIFFS[kind]}: begin en einde zijn gelijk.")
                parsed[profile].append((minutes(start), minutes(end), kind))
                normalized[profile][kind].append(f"{start}-{end}")

    per_day = [[] for _ in DAYS]
    for day in range(len(DAYS)):
        for start, end, kind in parsed["weekday" if day < 5 else "weekend"]:
            if end < start:
                per_day[day].append((start, 1440, kind))
                if end:
                    per_day[(day + 1) % len(DAYS)].append((0, end, kind))
            else:
                per_day[day].append((start, end, kind))

    for day, intervals in enumerate(per_day):
        previous_end = 0
        for start, end, kind in sorted(intervals):
            if start < previous_end:
                raise HomeAssistantError(
                    f"Op {DAYS[day]} overlapt {TARIFFS[kind]} om "
                    f"{start // 60:02d}:{start % 60:02d} met een ander tijdvak."
                )
            previous_end = end
    return normalized


def register_tariff_actions(hass, domain):
    storage = Store(hass, 1, f"{domain}.tariffs")

    async def get_tariffs(call=None):
        return await storage.async_load() or {
            "prices": {kind: "" for kind in TARIFFS},
            "schedule": {profile: {kind: [] for kind in TARIFFS} for profile in PROFILES},
        }

    async def set_tariffs(call):
        await storage.async_save({
            "prices": call.data["prices"],
            "schedule": normalize_schedule(call.data["schedule"]),
        })

    hass.services.async_register(domain, "get_tariffs", get_tariffs, supports_response=SupportsResponse.ONLY)
    hass.services.async_register(domain, "set_tariffs", set_tariffs, schema=SCHEMA)
    return get_tariffs
