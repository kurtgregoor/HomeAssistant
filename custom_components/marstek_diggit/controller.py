"""Home Assistant adapter for the household energy planner."""

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta
from functools import partial

import voluptuous as vol

from homeassistant.core import SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .client import MarstekError
from .energy import (
    CAPACITY_WH, Battery, Quarter, account_measurement, decide, learning, number,
    plan_24h, tariff_at,
)

DEFAULTS = {
    "enabled": False, "simulation": True, "minimum_soc": 12, "grid_limit": 4500,
    "interval_minutes": 10, "max_charge": 2500, "safety_margin": 15,
    "learning_days": 30, "shadow_days": 14, "learning_active": False,
    "max_sensor_age": 120, "peak_auto": True,
}
SENSORS = ("p1_sensor", "ev_sensor", "solar_sensor", "forecast_sensor", "quarter_energy_sensor")


def integer(low, high):
    return vol.All(int, vol.Range(min=low, max=high))


CONFIG_SCHEMA = vol.Schema({
    vol.Optional("battery_ids"): vol.All([str], vol.Length(min=2, max=2), vol.Unique()),
    **{vol.Optional(key): vol.Any("", cv.entity_id) for key in SENSORS},
    vol.Optional("enabled"): cv.boolean,
    vol.Optional("simulation"): cv.boolean,
    vol.Optional("learning_active"): cv.boolean,
    vol.Optional("minimum_soc"): integer(0, 99),
    vol.Optional("grid_limit"): integer(500, 25000),
    vol.Optional("interval_minutes"): integer(10, 60),
    vol.Optional("max_charge"): integer(100, 2500),
    vol.Optional("safety_margin"): integer(0, 100),
    vol.Optional("learning_days"): integer(30, 90),
    vol.Optional("shadow_days"): integer(14, 90),
    vol.Optional("max_sensor_age"): integer(30, 600),
})


def _reading(state, now, max_age, units):
    if not state or (now - state.last_reported).total_seconds() > max_age:
        return None
    value = number(state.state)
    multiplier = units.get(state.attributes.get("unit_of_measurement"))
    return value * multiplier if value is not None and multiplier is not None else None


class EnergyController:
    def __init__(self, hass, domain, load_tariffs):
        self.hass = hass
        self.domain = domain
        self.load_tariffs = load_tariffs
        self.store = Store(hass, 1, f"{domain}.energy_controller", atomic_writes=True)
        self.config = dict(DEFAULTS)
        self.history = []
        self.ledgers = {}
        self.lock = asyncio.Lock()
        self.quarter = Quarter()
        self.snapshot = {}
        self.batteries = (None, None)
        self.battery_at = None
        self.last_tariff = None
        self.last_strategy = None
        self.last_sample = None
        self.ev_active = None
        self.ev_low_since = None
        self.day = None
        self.cancel = None
        self.timer = None
        self.pending = None
        self.next_event = False
        self.last_tariff_data = None
        self.battery_context = (None, None, None)
        self.last_intent = None
        self.last_change = None
        self.verified_firmware = set()
        self.leases = {}
        self.last_command = None
        self.command_error = None

    async def load(self):
        data = await self.store.async_load() or {}
        self.config.update(data.get("config", {}))
        self.history = data.get("history", [])
        self.day = data.get("day")
        # Keep recorded buckets for diagnostics until the first fresh sample.
        self.ledgers = data.get("ledgers", {})
        if self.config["enabled"]:
            self.subscribe()

    def persist(self):
        self.store.async_delay_save(self.data, 15)

    def data(self):
        return {"config": self.config, "history": self.history[-365:],
                "ledgers": self.ledgers, "day": self.day}

    @callback
    def subscribe(self):
        if self.cancel:
            self.cancel()
            self.cancel = None
        if self.timer:
            self.timer()
            self.timer = None
        if self.config["enabled"]:
            sensors = {self.config[key] for key in SENSORS if self.config.get(key)}
            self.cancel = async_track_state_change_event(self.hass, sensors, self.schedule)
            # Simulation guard checks clock boundaries and sensor freshness.
            self.timer = async_track_time_interval(self.hass, self.schedule, timedelta(seconds=5))
            self.schedule()

    @callback
    def schedule(self, _event=None):
        if not self.config["enabled"]:
            return
        if self.pending and not self.pending.done():
            self.next_event = True
            return
        self.pending = self.hass.async_create_task(self.drain(), "Marstek Energy Planner")

    async def drain(self):
        try:
            while self.config["enabled"]:
                self.next_event = False
                await self.evaluate()
                if not self.next_event:
                    break
        except (HomeAssistantError, OSError, ValueError) as exc:
            self.snapshot = {**self.snapshot, "error": str(exc), "decision": {
                "mode": "SAFE_FALLBACK", "reason": str(exc), "blocks": ["interne fout"],
                "target": 100, "watts": (0, 0),
            }}

    def state(self, key):
        entity = self.config.get(key)
        return self.hass.states.get(entity) if entity else None

    def watts(self, key, now):
        return _reading(self.state(key), now, self.config["max_sensor_age"], {"W": 1, "kW": 1000})

    async def get_battery(self, entry_id):
        battery = self.hass.data[self.domain].get(entry_id)
        if battery is None:
            return None
        try:
            status = await battery.get_status()
        except (MarstekError, OSError):
            return None
        try:
            status.update(await battery.client.get_energy_counters())
        except (MarstekError, OSError):
            pass
        return Battery.from_status(status)

    def read_ev(self, now):
        watts = self.watts("ev_sensor", now)
        state = self.state("ev_sensor")
        if watts is None and state and state.domain == "binary_sensor" and (
            now - state.last_reported
        ).total_seconds() <= self.config["max_sensor_age"]:
            watts = {"on": 1000, "off": 0}.get(state.state)
        if watts is None:
            self.ev_low_since = None
            return None
        if watts >= 1000:
            self.ev_active = True
        if watts > 700:
            self.ev_low_since = None
        else:
            if self.ev_low_since is None:
                self.ev_low_since = now
            if self.ev_active is not True or (now - self.ev_low_since).total_seconds() >= 10:
                self.ev_active = False
        return self.ev_active

    def official_quarter(self, now):
        state = self.state("quarter_energy_sensor")
        value = _reading(state, now, self.config["max_sensor_age"], {"Wh": 1, "kWh": 1000})
        if value is None or value < 0:
            return None
        raw_start = state.attributes.get("quarter_start")
        start = dt_util.parse_datetime(raw_start) if isinstance(raw_start, str) else None
        if start and start.tzinfo and start.timestamp() <= now.timestamp() < start.timestamp() + 900:
            # Require alignment with the meter's stated quarter before using its counter.
            if start.timestamp() % 900 == 0:
                return value
        return None

    def forecast(self, now):
        state = self.state("forecast_sensor")
        if not state or (now - state.last_reported).total_seconds() > 6 * 3600:
            return None
        raw = state.attributes.get("watts_by_hour")
        if not isinstance(raw, dict):
            return None
        by_time = {}
        for stamp, watts in raw.items():
            at = dt_util.parse_datetime(stamp) if isinstance(stamp, str) else None
            value = number(watts)
            if at and at.tzinfo and value is not None and value >= 0:
                by_time[int(at.timestamp() // 3600)] = round(value)
        return lambda time: by_time.get(int(time.timestamp() // 3600))

    def record(self, now, tariff, forecast, grid, pv, ev_watts, batteries):
        date = now.date().isoformat()
        if self.day is None:
            self.day = {"date": date, "weekend": now.weekday() >= 5, "expected": 0,
                        "covered": 0, "evening_wh": 0, "peak_wh": 0,
                        "pv_wh": 0, "ev_wh": 0, "battery_in_wh": 0, "battery_out_wh": 0}
            if forecast["phase"] != "learning":
                self.day["prediction_wh"] = forecast["forecast_wh"]
        sample = (now, tariff, grid, pv, ev_watts, batteries)
        previous, self.last_sample = self.last_sample, sample
        if not previous:
            return
        start, prev_tariff, prev_grid, prev_pv, prev_ev, prev_batteries = previous
        elapsed = now.timestamp() - start.timestamp()
        if start.date() != now.date() or elapsed <= 0:
            return
        evening = 17 <= start.hour < 23
        if not evening and prev_tariff != "peak":
            return
        day = self.day
        day["expected"] += elapsed
        if elapsed > 30 or None in (prev_grid, prev_pv, prev_ev) or any(b is None for b in prev_batteries):
            return
        # Battery power is positive for export; EV load is tracked separately.
        battery_w = sum(b.watts for b in prev_batteries)
        watts = max(0, prev_grid + prev_pv + battery_w - prev_ev)
        hours = elapsed / 3600
        day["covered"] += elapsed
        if evening:
            day["evening_covered"] = day.get("evening_covered", 0) + elapsed
        if evening:
            day["evening_wh"] += watts * hours
        if prev_tariff == "peak":
            day["peak_wh"] += watts * hours
        day["pv_wh"] += prev_pv * hours
        day["ev_wh"] += prev_ev * hours
        day["battery_in_wh"] += sum(max(0, -b.watts) for b in prev_batteries) * hours
        day["battery_out_wh"] += sum(max(0, b.watts) for b in prev_batteries) * hours

    def finish_day(self):
        day = self.day
        # Reject late starts, restarts and insufficient evening coverage.
        day["valid"] = (day["expected"] >= 6 * 3600 - 30
                        and day["covered"] >= 0.98 * day["expected"]
                        and day.get("evening_covered", 0) >= 0.98 * 6 * 3600)
        self.history = [*self.history[-364:], day]

    def owns(self, entry_id):
        return (self.config["enabled"] and not self.config["simulation"]
                and entry_id in self.config.get("battery_ids", []))

    async def verify_firmware(self, ids):
        for entry in ids:
            if entry in self.verified_firmware:
                continue
            battery = self.hass.data[self.domain].get(entry)
            if battery is None:
                raise MarstekError("Geconfigureerde batterij ontbreekt.")
            info = await battery.client.get_device_info()
            model = str(info.get("model", "")).replace(" ", "").casefold()
            if model != "venuse3.0" or str(info.get("firmware")) != "151":
                raise MarstekError("Actieve sturing is getest voor Venus E 3.0 op firmware V151.")
            self.verified_firmware.add(entry)

    async def apply(self, ids, watts, before_charge=None):
        """Hold the other battery first. Never send a positive setpoint or Auto."""
        if (len(ids) != 2 or len(watts) != 2 or any(power > 0 for power in watts)
                or sum(power < 0 for power in watts) > 1):
            raise MarstekError("Ongeldig gezamenlijk laadvoorstel.")
        await self.verify_firmware(ids)
        failures = []
        for index in sorted(range(2), key=lambda i: watts[i] < 0):
            entry, power = ids[index], watts[index]
            battery = self.hass.data[self.domain].get(entry)
            try:
                if battery is None:
                    raise MarstekError("Geconfigureerde batterij ontbreekt.")
                status = Battery.from_status(await battery.get_status())
                if status is None:
                    raise MarstekError("Batterijstatus ontbreekt of modus is niet bevestigd.")
                if power < 0:
                    power = 0 if failures or before_charge is None else before_charge(power, status)
                lease = self.leases.get(entry)
                if power == 0 and status.mode == "Passive" and abs(status.watts) <= 20:
                    self.leases.pop(entry, None)
                    continue
                if power < 0 and lease and lease[0] == power and (
                    dt_util.utcnow() - lease[1]
                ).total_seconds() < 40 and status.mode == "Passive" and status.watts < -20:
                    continue
                sent_at = await battery.set_energy_power(power)
                self.leases[entry] = (power, sent_at)
                self.last_command = f"{dt_util.as_local(sent_at).isoformat()} · batterij {index + 1} · {power} W"
            except (MarstekError, OSError) as exc:
                failures.append(f"Batterij {index + 1} · {exc}")
        if failures:
            raise MarstekError("; ".join(failures))

    def auto_allowed(self):
        now = dt_util.now()
        return tariff_at(now, self.last_live_schedule) == "peak" and self.read_ev(now) is False

    async def apply_auto(self, ids, states):
        if not self.auto_allowed():
            await self.apply(ids, (0, 0))
            return
        if any(b.mode == "Passive" and abs(b.watts) > 20 for b in states):
            await self.apply(ids, (0, 0))
        await self.verify_firmware(ids)
        for index, (entry, observed) in enumerate(zip(ids, states)):
            battery = self.hass.data[self.domain].get(entry)
            if battery is None:
                raise MarstekError("Geconfigureerde batterij ontbreekt.")
            if not self.auto_allowed():
                await self.apply(ids, (0, 0))
                return
            if not await battery.set_energy_auto(self.auto_allowed):
                await self.apply(ids, (0, 0))
                return
            if observed.mode != "Auto":
                self.last_command = f"{dt_util.now().isoformat()} · batterij {index + 1} · Auto"
            self.leases.pop(entry, None)

    def live_budget(self, tariff, limit, batteries, original_grid, power, status):
        now = dt_util.now()
        if not 0 <= (now - self.live_sample_at).total_seconds() <= 15:
            return 0
        grid = self.watts("p1_sensor", now)
        ev = self.read_ev(now)
        if grid is None or ev is None or tariff_at(now, self.last_live_schedule) != tariff:
            return 0
        # The other battery was confirmed idle before reaching this guard.
        base = max(grid + status.watts, original_grid + sum(b.watts for b in batteries))
        budget = limit - base - 200
        if ev or tariff == "peak" or tariff_at(now + timedelta(seconds=65), self.last_live_schedule) != tariff:
            budget = min(budget, -base - 100)
        available = max(0, int(budget // 50) * 50)
        return -min(-power, available) if available >= 100 else 0

    async def evaluate(self):
        async with self.lock:
            config = self.config
            if not config["enabled"]:
                return
            now = dt_util.now()
            tariff_data = await self.load_tariffs()
            schedule, prices = tariff_data["schedule"], tariff_data["prices"]
            tariff = tariff_at(now, schedule)
            grid = self.watts("p1_sensor", now)
            pv = self.watts("solar_sensor", now)
            ev = self.read_ev(now)
            quarter = self.quarter.update(now, grid, config["grid_limit"], self.official_quarter(now))
            ids = config.get("battery_ids", [])
            changed = tariff != self.last_tariff or tariff_data != self.last_tariff_data
            if self.last_tariff_data and prices != self.last_tariff_data["prices"]:
                # Repricing stored energy could authorize an invalid discharge.
                self.ledgers = {}
                self.battery_context = (None, None, None)
                self.battery_at = None
            due = (self.last_strategy is None or changed or
                   now.timestamp() - self.last_strategy >= config["interval_minutes"] * 60)
            # Read-only samples are separate from the 10-minute planning cadence.
            # One read per battery per 20 sec supports provenance/learning and mode freshness.
            if len(ids) == 2 and (self.battery_at is None or now.timestamp() - self.battery_at >= 20):
                batteries = tuple(await asyncio.gather(*(self.get_battery(entry) for entry in ids)))
                seconds = now.timestamp() - self.battery_at if self.battery_at is not None else 0
                old_grid, old_pv, old_tariff = self.battery_context
                evidence = (None, None)
                if all(b and b.watts <= 0 for b in (*self.batteries, *batteries)):
                    if pv == old_pv == 0 or (
                        pv is not None and old_pv is not None and min(pv, old_pv) > 50
                        and grid is not None and old_grid is not None and max(grid, old_grid) < -50
                    ):
                        evidence = (old_grid, grid)
                for i, (entry, battery) in enumerate(zip(ids, batteries)):
                    if battery:
                        self.ledgers[entry] = account_measurement(
                            self.ledgers.get(entry, {}), self.batteries[i], battery, tariff,
                            old_tariff, evidence, seconds)
                self.batteries, self.battery_at = batteries, now.timestamp()
                self.battery_context = (grid, pv, tariff)
                self.persist()

            if self.day and self.day["date"] != now.date().isoformat():
                self.finish_day()
                self.day = None
                due = True
            forecast = self.snapshot.get("learning")
            if due or forecast is None:
                forecast = learning(self.history, now.weekday() >= 5, config["minimum_soc"],
                                    config["safety_margin"] / 100, config["learning_days"],
                                    config["shadow_days"], config["learning_active"])
            previous_day = self.day
            self.record(now, tariff, forecast, grid, pv, self.watts("ev_sensor", now), self.batteries)
            if previous_day is not self.day:
                self.persist()

            ledgers = tuple(self.ledgers.get(entry, {}) for entry in ids)
            decision = decide(tariff, prices, self.batteries, ledgers, grid, ev,
                              quarter["allowed_w"], forecast["applied_target"],
                              config["minimum_soc"], config["max_charge"], peak_auto=config["peak_auto"])
            if not config["simulation"]:
                self.live_sample_at = now
                self.last_live_schedule = schedule
                guard = partial(self.live_budget, tariff, quarter["allowed_w"], self.batteries, grid)
                try:
                    if decision.mode == "SELF_CONSUMPTION":
                        await self.apply_auto(ids, self.batteries)
                    elif not (tariff == "peak" and ev is False and "telemetrie" in decision.blocks):
                        await self.apply(ids, decision.watts, guard)
                    self.command_error = None
                except (MarstekError, OSError) as exc:
                    self.command_error = str(exc)
            intent = (decision.mode, decision.watts)
            if intent != self.last_intent:
                self.last_intent = intent
                self.last_change = {"at": now.isoformat(), "mode": decision.mode,
                                    "watts": decision.watts, "status": "simulated" if config["simulation"] else "planned"}
            plan = self.snapshot.get("plan", [])
            if due:
                household = (max(0, grid + (pv or 0) + sum(b.watts for b in self.batteries)
                                 - (self.watts("ev_sensor", now) or 0))
                             if grid is not None and all(self.batteries) else None)
                solar = self.forecast(now)
                plan = await self.hass.async_add_executor_job(partial(
                    plan_24h, now, schedule, prices, self.batteries, ledgers, ev,
                    household, solar, forecast["forecast_wh"], config, forecast["applied_target"]))
                self.last_strategy = now.timestamp()
                self.last_tariff = tariff
                self.last_tariff_data = tariff_data

            self.snapshot = {
                "updated": now.isoformat(), "tariff": tariff, "decision": asdict(decision),
                "batteries": [asdict(b) if b else None for b in self.batteries],
                "available_wh": round(sum(max(0, b.soc - config["minimum_soc"]) * CAPACITY_WH / 100
                                          for b in self.batteries if b)),
                "quarter": quarter, "learning": forecast, "plan": plan, "ledgers": self.ledgers,
                "execution": "simulation" if config["simulation"] else "active",
                "last_successful_command": self.last_command,
                "error": self.command_error,
                "last_simulated_change": self.last_change,
                "observed_modes": [battery.mode if battery else None for battery in self.batteries],
                "blocked_execution": ("Simulatie" if config["simulation"]
                                      else "Auto tijdens piek zonder autoladen"),
                "next_action": next((row for row in plan[1:] if row["mode"] != decision.mode), None),
                "superdal_shortfall": next((
                    row["soc"] for i, row in enumerate(plan)
                    if row["tariff"] == "super_offpeak" and
                    (i + 1 == len(plan) or plan[i + 1]["tariff"] != "super_offpeak")
                    and any(soc is not None and soc < 100 for soc in row["soc"])
                ), None),
                "quarter_warning": quarter["above_seconds"] >= 600,
                "quarter_charge_limited": (tariff in ("offpeak", "super_offpeak") and
                                           grid is not None and all(self.batteries) and
                                           quarter["allowed_w"] - grid -
                                           sum(b.watts for b in self.batteries) - 200 < config["max_charge"]),

                "unavoidable_peak": (grid is not None and all(self.batteries) and
                                     grid + sum(b.watts for b in self.batteries) > quarter["allowed_w"]),

            }

    async def configure(self, call):
        async with self.lock:
            config = {**self.config, **call.data}
            ids = config.get("battery_ids", [])
            if config["enabled"] and (
                len(ids) != 2 or any(entry not in self.hass.data[self.domain] for entry in ids)
                or not config.get("p1_sensor") or not config.get("ev_sensor")
            ):
                raise HomeAssistantError("Selecteer twee batterijen, een P1-sensor en een Smappee-sensor.")
            old_ids = self.config.get("battery_ids", [])
            old_live = self.config["enabled"] and not self.config["simulation"]
            new_live = config["enabled"] and not config["simulation"]
            try:
                if new_live:
                    await self.verify_firmware(ids)
                if old_live and (not new_live or ids != old_ids):
                    await self.apply(old_ids, (0, 0))
            except (MarstekError, OSError) as exc:
                raise HomeAssistantError(str(exc)) from exc
            if ids != self.config.get("battery_ids", []):
                self.batteries = (None, None)
                self.battery_at = None
                self.last_sample = None
            if any(config.get(key) != self.config.get(key) for key in SENSORS):
                self.last_sample = None
                self.battery_context = (None, None, None)
                self.quarter = Quarter()
                self.ev_active = self.ev_low_since = None
            if not config["enabled"]:
                self.snapshot = {}
                self.last_sample = None
                self.battery_at = None
                self.last_intent = self.last_change = None
                self.quarter = Quarter()
            await self.store.async_save({**self.data(), "config": config})
            self.config = config
            self.last_strategy = None
            self.subscribe()

    async def status(self, _call):
        return {**self.snapshot, "config": self.config,
                "battery_entries": [
                    {"id": entry_id, "title": entry.title if (entry := self.hass.config_entries.async_get_entry(entry_id)) else entry_id}
                    for entry_id in self.hass.data[self.domain]
                ]}


async def register_energy_actions(hass, domain, load_tariffs):
    controller = EnergyController(hass, domain, load_tariffs)
    await controller.load()
    async_register_admin_service(hass, domain, "configure_energy_controller",
                                 controller.configure, schema=CONFIG_SCHEMA)
    hass.services.async_register(domain, "get_energy_plan", controller.status, supports_response=SupportsResponse.ONLY)
    return controller
