"""Persist and restore a temporary Passive command for one config entry."""

from asyncio import Lock, sleep
from datetime import datetime, timedelta, timezone
import logging
from math import isfinite

from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store

from .client import MODE_CONFIG, MarstekError, MarstekModeRejected

_LOGGER = logging.getLogger(__name__)
_RETRY_DELAY = timedelta(seconds=30)


def passive_store(hass, domain, entry_id):
    return Store(hass, 1, f"{domain}.passive.{entry_id}", atomic_writes=True)


class PassiveControl:
    def __init__(self, hass, client, store, entry_id):
        self.client = client
        self._hass = hass
        self._store = store
        self._entry_id = entry_id
        self._lock = Lock()
        self._pending = None
        self._cancel_timer = None
        self._unloaded = False

    async def async_load(self):
        if pending := await self._store.async_load():
            self._set_pending(pending)

    async def async_unload(self):
        self._unloaded = True
        async with self._lock:
            self._cancel()

    def _ensure_loaded(self):
        if self._unloaded:
            raise MarstekError("Deze Marstek-batterij is niet meer geladen.")

    def _cancel(self):
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None

    def _schedule(self, pending, when):
        self._cancel()

        async def restore(_now):
            await self._restore(pending)

        self._cancel_timer = async_track_point_in_utc_time(self._hass, restore, when)

    def _set_pending(self, pending):
        self._pending = pending
        deadline = datetime.fromisoformat(pending["ends_at"])
        self._schedule(pending, max(deadline, datetime.now(timezone.utc)))

    async def get_status(self):
        async with self._lock:
            status = await self.client.get_status()
            if status["mode"] == "Passive" and self._pending:
                status["passive_source"] = self._pending.get("source")
                status["passive_power"] = self._pending.get("power")
            return status

    async def set_passive(self, power, duration_seconds, source=None):
        async with self._lock:
            self._ensure_loaded()
            previous_mode = (await self.client.get_status())["mode"]
            previous = self._pending if previous_mode == "Passive" else None
            mode = previous["original_mode"] if previous else previous_mode
            if source and (
                mode != "Auto" or (previous and previous.get("source") != source)
            ):
                raise MarstekError("De programmatie kan alleen Auto of haar eigen Passive-opdracht aanpassen.")
            if mode not in MODE_CONFIG:
                raise MarstekError(f"Passive niet gestart: {mode} kan niet worden hersteld.")

            duration = timedelta(seconds=duration_seconds)
            deadline = datetime.now(timezone.utc) + duration
            pending = {
                "original_mode": mode,
                "ends_at": deadline.isoformat(),
                "source": source,
                "power": power,
            }
            # Save before sending UDP. The battery may apply the command even
            # if Home Assistant stops or the UDP acknowledgement is lost.
            await self._store.async_save(pending)
            self._set_pending(pending)
            try:
                started_at = await self.client.set_passive(
                    power, duration_seconds, previous_mode
                )
            except MarstekModeRejected:
                if previous is None:
                    await self._clear()
                else:
                    await self._store.async_save(previous)
                    self._set_pending(dict(previous))
                raise

            deadline = started_at + duration
            confirmed = {**pending, "ends_at": deadline.isoformat()}
            await self._store.async_save(confirmed)
            self._set_pending(confirmed)

    async def set_energy_power(self, power):
        """Take a bounded charge lease or hold without scheduling legacy Auto restore."""
        if not -2500 <= power <= 0:
            raise MarstekError("Energy Planner accepteert alleen laden of 0 W.")
        async with self._lock:
            self._ensure_loaded()
            if self._pending:
                raise MarstekError("Wacht tot de bestaande Passive-opdracht is afgelopen.")
            status = await self.client.get_status()
            mode = status["mode"]
            if mode not in ("Auto", "Passive"):
                raise MarstekError(f"Energy Planner kan modus {mode} niet overnemen.")
            sent_at = await self.client.set_passive(power, 60, mode)
            # V151 acknowledges a setpoint before the inverter ramps.
            for delay in (3.5, 2):
                await sleep(delay)
                try:
                    observed = await self.client.get_status()
                except MarstekError:
                    continue
                watts = observed.get("ongrid_power")
                if (observed["mode"] == "Passive" and isinstance(watts, (int, float))
                        and isfinite(watts) and (
                            abs(watts) <= 20 if power == 0 else power - 100 <= watts <= -20
                        )):
                    return sent_at
            raise MarstekError("Passive-opdracht niet bevestigd door modus en vermogen.")

    async def set_energy_auto(self, still_allowed):
        async with self._lock:
            self._ensure_loaded()
            if self._pending:
                raise MarstekError("Wacht tot de bestaande Passive-opdracht is afgelopen.")
            status = await self.client.get_status()
            if not still_allowed():
                return False
            if status["mode"] == "Auto":
                return True
            watts = status.get("ongrid_power")
            if status["mode"] != "Passive" or not isinstance(watts, (int, float)) or abs(watts) > 20:
                raise MarstekError("Bevestig eerst Passive 0 W vóór Auto.")
            await self.client.set_mode("Auto")
            for delay in (1.2, 2):
                await sleep(delay)
                if not still_allowed():
                    return False
                try:
                    if (await self.client.get_status())["mode"] == "Auto":
                        return True
                except MarstekError:
                    continue
            raise MarstekError("Auto niet bevestigd door de batterij.")

    async def set_mode(self, mode):
        async with self._lock:
            self._ensure_loaded()
            await self.client.set_mode(mode)
            await self._clear()

    async def write_slot(self, schedule, activate_manual):
        async with self._lock:
            self._ensure_loaded()
            await self.client.write_slot(schedule, activate_manual)
            if activate_manual:
                await self._clear()

    async def _clear(self):
        if self._pending:
            await self._store.async_remove()
            self._pending = None
            self._cancel()

    async def _restore(self, pending):
        async with self._lock:
            if self._unloaded or self._pending is not pending:
                return
            self._cancel_timer = None
            try:
                await self.client.restore_from_passive(pending["original_mode"])
                await self._clear()
            except (MarstekError, OSError) as exc:
                _LOGGER.warning(
                    "Herstel naar %s voor Marstek-batterij %s mislukt. "
                    "Nieuwe poging over %s seconden: %s",
                    pending["original_mode"], self._entry_id,
                    int(_RETRY_DELAY.total_seconds()), exc,
                )
                self._schedule(pending, datetime.now(timezone.utc) + _RETRY_DELAY)
