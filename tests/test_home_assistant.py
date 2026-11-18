"""Smoke tests with Home Assistant 2025.7 and fake battery responses."""

from datetime import timedelta
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from homeassistant.core import HomeAssistant
except ModuleNotFoundError as exc:
    if exc.name != "homeassistant":
        raise
    raise unittest.SkipTest("Requires Home Assistant 2025.7 or newer") from exc

from homeassistant.config_entries import ConfigEntries
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.marstek_diggit import DOMAIN, async_setup
from custom_components.marstek_diggit.client import MarstekNoResponse
from custom_components.marstek_diggit.controller import EnergyController


class Integration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.hass = HomeAssistant(directory.name)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        self.hass.http = SimpleNamespace(async_register_static_paths=AsyncMock())
        self.first, self.second = (self.battery(30), self.battery(60))
        self.hass.data[DOMAIN] = {"first": self.first, "second": self.second}
        self.assertTrue(await async_setup(self.hass, {}))
        self.hass.states.async_set("sensor.p1", "450", {"unit_of_measurement": "W"})
        self.hass.states.async_set("sensor.smappee", "0", {"unit_of_measurement": "W"})
        self.hass.states.async_set("sensor.pv", "0", {"unit_of_measurement": "W"})
        self.tariffs = {
            "prices": {"peak": ".25", "offpeak": ".18", "super_offpeak": ".14"},
            "schedule": {
                day: {"offpeak": ["00:00-24:00"], "peak": [], "super_offpeak": []}
                for day in ("weekday", "weekend")
            },
        }

    def battery(self, soc):
        return SimpleNamespace(
            get_status=AsyncMock(return_value={"mode": "Auto", "bat_soc": soc, "ongrid_power": 0}),
            set_mode=AsyncMock(),
            set_passive=AsyncMock(),
            set_energy_power=AsyncMock(),
            client=SimpleNamespace(get_device_info=AsyncMock(return_value={
                "model": "VenusE 3.0", "firmware": 151,
            }), get_energy_counters=AsyncMock(return_value={
                "total_grid_input_energy": 40, "total_grid_output_energy": 0,
            })),
        )

    def assert_no_writes(self):
        for battery in (self.first, self.second):
            battery.set_mode.assert_not_called()
            battery.set_passive.assert_not_called()
            battery.set_energy_power.assert_not_called()

    async def test_existing_actions_and_simulation_gate(self):
        for service in ("get_status", "set_passive", "get_tariffs", "configure_energy_controller", "get_energy_plan"):
            self.assertTrue(self.hass.services.has_service(DOMAIN, service))
        snapshot = await self.hass.services.async_call(DOMAIN, "get_energy_plan", blocking=True, return_response=True)
        self.assertFalse(snapshot["config"]["enabled"])
        self.assertTrue(snapshot["config"]["simulation"])
        with self.assertRaises(HomeAssistantError):
            await self.hass.services.async_call(
                DOMAIN, "configure_energy_controller", {"simulation": False, "enabled": True}, blocking=True,
            )
        self.assert_no_writes()

    async def test_restored_configuration_is_read_only_and_handles_missing_data(self):
        controller = EnergyController(self.hass, DOMAIN, AsyncMock(return_value=self.tariffs))
        controller.store.async_load = AsyncMock(return_value={"config": {
            "enabled": True, "battery_ids": ["first", "second"], "p1_sensor": "sensor.p1",
            "ev_sensor": "sensor.smappee", "solar_sensor": "sensor.pv",
        }})
        controller.persist = lambda: None
        with patch.object(controller, "subscribe") as subscribe:
            await controller.load()
        subscribe.assert_called_once()
        await controller.evaluate()
        self.assertEqual(controller.snapshot["decision"]["mode"], "CHARGING")
        self.assertEqual(controller.snapshot["decision"]["watts"], (-2500, 0))
        self.assertEqual(controller.snapshot["execution"], "simulation")
        first_plan = controller.snapshot["plan"]
        self.hass.states.async_set("sensor.smappee", "1800", {"unit_of_measurement": "W"})
        await controller.evaluate()
        self.assertEqual(controller.snapshot["decision"]["mode"], "HOLDING")
        self.assertIs(controller.snapshot["plan"], first_plan)
        self.hass.states.async_remove("sensor.p1")
        await controller.evaluate()
        self.assertEqual(controller.snapshot["decision"]["mode"], "SAFE_FALLBACK")
        self.hass.states.async_set("sensor.p1", "200", {"unit_of_measurement": "W"})
        self.second.get_status.side_effect = MarstekNoResponse("geen antwoord")
        controller.battery_at = dt_util.now().timestamp() - 30
        await controller.evaluate()
        self.assertIsNone(controller.snapshot["batteries"][1])
        self.assertEqual(controller.snapshot["decision"]["mode"], "SAFE_FALLBACK")
        self.assert_no_writes()

    async def test_p1_event_updates_budget_without_replanning(self):
        controller = EnergyController(self.hass, DOMAIN, AsyncMock(return_value=self.tariffs))
        controller.persist = lambda: None
        controller.store.async_save = AsyncMock()
        try:
            await controller.configure(SimpleNamespace(data={
                "enabled": True, "battery_ids": ["first", "second"], "p1_sensor": "sensor.p1",
                "ev_sensor": "sensor.smappee",
            }))
            await self.hass.async_block_till_done()
            self.assertEqual(controller.snapshot["decision"]["mode"], "CHARGING")
            plan = controller.snapshot["plan"]
            self.hass.states.async_set("sensor.p1", "8000", {"unit_of_measurement": "W"})
            await self.hass.async_block_till_done()
            self.assertEqual(controller.snapshot["decision"]["watts"], (0, 0))
            self.assertTrue(controller.snapshot["quarter_charge_limited"])
            self.assertIs(controller.snapshot["plan"], plan)
            self.assert_no_writes()
        finally:
            await controller.configure(SimpleNamespace(data={"enabled": False}))

    async def test_live_hold_before_charge_and_no_duplicate_command(self):
        controller = EnergyController(self.hass, DOMAIN, AsyncMock())
        operations = []
        for i, battery in enumerate((self.first, self.second)):
            async def power(watts, i=i, battery=battery):
                operations.append((i, watts))
                battery.get_status.return_value = {"mode": "Passive", "bat_soc": 50, "ongrid_power": watts}
                return dt_util.utcnow()
            battery.set_energy_power.side_effect = power
        ids = ["first", "second"]
        await controller.apply(ids, (-300, 0), lambda power, status: power)
        self.assertEqual(operations, [(1, 0), (0, -300)])
        await controller.apply(ids, (-300, 0), lambda power, status: power)
        self.assertEqual(len(operations), 2)
        await controller.apply(ids, (-300, 0), lambda power, status: 0)
        self.assertEqual(operations[-1], (0, 0))
        self.first.set_mode.assert_not_called()
        self.second.set_mode.assert_not_called()

    async def test_unconfirmed_hold_blocks_live_charge(self):
        controller = EnergyController(self.hass, DOMAIN, AsyncMock())
        self.second.set_energy_power.side_effect = MarstekNoResponse("geen antwoord")
        self.first.set_energy_power.return_value = dt_util.utcnow()
        with self.assertRaisesRegex(Exception, "Batterij 2"):
            await controller.apply(["first", "second"], (-300, 0), lambda power, status: power)
        self.first.set_energy_power.assert_awaited_once_with(0)

    async def test_live_power_does_not_create_restore_timer(self):
        from custom_components.marstek_diggit.passive import PassiveControl

        client = SimpleNamespace(
            get_status=AsyncMock(side_effect=[
                {"mode": "Auto", "ongrid_power": 200},
                {"mode": "Passive", "ongrid_power": -281},
            ]),
            set_passive=AsyncMock(return_value=dt_util.utcnow()),
        )
        store = SimpleNamespace(async_save=AsyncMock())
        control = PassiveControl(self.hass, client, store, "first")
        with patch("custom_components.marstek_diggit.passive.sleep", AsyncMock()):
            await control.set_energy_power(-300)
        client.set_passive.assert_awaited_once_with(-300, 60, "Auto")
        store.async_save.assert_not_called()

    async def test_ev_hysteresis_and_stale_sensor(self):
        controller = EnergyController(self.hass, DOMAIN, AsyncMock())
        controller.config["ev_sensor"] = "sensor.smappee"
        attrs = {"unit_of_measurement": "W"}
        self.hass.states.async_set("sensor.smappee", "1200", attrs)
        now = dt_util.now()
        self.assertTrue(controller.read_ev(now))
        controller.hass.states.async_set("sensor.smappee", "999", attrs)
        self.assertTrue(controller.read_ev(now))
        controller.hass.states.async_set("sensor.smappee", "450", attrs)
        self.assertTrue(controller.read_ev(now))
        self.assertFalse(controller.read_ev(now + timedelta(seconds=11)))
        self.assertIsNone(controller.read_ev(now + timedelta(seconds=130)))
