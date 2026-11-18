"""Run with python -m unittest discover -s tests."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo


def load_module(name):
    directory = Path(__file__).resolve().parents[1] / "custom_components" / "marstek_diggit"
    spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


energy = load_module("energy")
client = load_module("client")
PRICES = {"peak": ".25", "offpeak": ".18", "super_offpeak": ".14"}
SCHEDULE = {
    "weekday": {"offpeak": ["11:00-17:00"], "super_offpeak": ["22:00-07:00"], "peak": ["07:00-11:00"]},
    "weekend": {"offpeak": ["17:00-01:00"], "super_offpeak": ["11:00-17:00"], "peak": []},
}
FIRST, SECOND = energy.Battery(30, 0, "Auto"), energy.Battery(60, 0, "Passive")


def decision(tariff="offpeak", **changes):
    settings = dict(tariff=tariff, prices=PRICES, batteries=(FIRST, SECOND),
                    ledgers=({"super_offpeak": 500}, {"solar": 500}), grid=400,
                    ev=False, margin=4500, target=100, minimum=12)
    return energy.decide(**{**settings, **changes})


class Rules(unittest.TestCase):
    def test_weekend_and_midnight(self):
        zone = ZoneInfo("Europe/Brussels")
        for stamp, expected in [
            ("2026-11-20T21:59", None), ("2026-11-20T22:00", "super_offpeak"),
            ("2026-11-21T06:59", "super_offpeak"), ("2026-11-21T07:00", None),
            ("2026-11-21T11:00", "super_offpeak"), ("2026-11-22T00:30", "offpeak"),
        ]:
            with self.subTest(stamp=stamp):
                self.assertEqual(energy.tariff_at(datetime.fromisoformat(stamp).replace(tzinfo=zone),
                                                   SCHEDULE), expected)

    def test_superdal_full_and_dal_learning(self):
        for tariff, target in (("super_offpeak", 81), ("offpeak", 100)):
            result = decision(tariff, target=target)
            self.assertEqual((result.mode, result.target, result.watts), ("CHARGING", 100, (-2500, 0)))
        full = energy.Battery(100, 0, "Passive")
        self.assertEqual(decision("super_offpeak", batteries=(full, full)).mode, "HOLDING")

    def test_car_blocks_discharge_and_grid_charging(self):
        for tariff in PRICES:
            result = decision(tariff, ev=True)
            self.assertEqual(result.watts, (0, 0))
            self.assertIn("auto laadt", result.blocks)
        self.assertEqual(decision("peak", ev=True, grid=-750).watts, (-650, 0))

    def test_no_battery_to_battery_transfer(self):
        charging = energy.replace(SECOND, watts=-500)
        self.assertEqual(decision("peak", batteries=(FIRST, charging)).mode, "HOLDING")
        discharging = energy.replace(SECOND, watts=500)
        hold = decision("offpeak", batteries=(FIRST, discharging))
        self.assertEqual(hold.watts, (0, 0))
        self.assertIn("batterij ontlaadt", hold.blocks)

    def test_auto_only_for_allowed_aligned_prices(self):
        self.assertEqual(decision("peak").mode, "SELF_CONSUMPTION")
        for ledgers in ({"peak": 100}, {"unknown": 1}, {}, {"offpeak": 5}):
            prices = {**PRICES, "offpeak": PRICES["peak"]}
            self.assertEqual(decision("peak", ledgers=(ledgers, {"solar": 50}), prices=prices).mode, "HOLDING")

    def test_fallbacks(self):
        for changes in ({"grid": None}, {"ev": None}, {"batteries": (FIRST, None)}):
            self.assertEqual(decision("peak", **changes).mode, "SAFE_FALLBACK")
        self.assertIsNone(energy.Battery.from_status({"mode": "Manual", "ongrid_power": 0, "bat_soc": 30}))
        self.assertEqual(decision("peak", minimum=30).mode, "HOLDING")

    def test_lower_soc_and_active_charging(self):
        second = energy.replace(SECOND, watts=-500)
        self.assertEqual(decision(batteries=(FIRST, second)).watts, (0, -2500))
        self.assertEqual(decision(batteries=(energy.replace(FIRST, soc=100), SECOND)).watts, (0, -2500))

    def test_surplus_can_exceed_learned_paid_charge_target(self):
        full_for_dal = (energy.replace(FIRST, soc=80), energy.replace(SECOND, soc=85))
        self.assertEqual(decision(batteries=full_for_dal, target=80).mode, "HOLDING")
        solar = decision(batteries=full_for_dal, target=80, grid=-600)
        self.assertEqual((solar.target, solar.watts), (100, (-500, 0)))

    def test_limited_charge_and_recovery(self):
        self.assertEqual(decision(grid=4100, margin=4500).watts, (-200, 0))
        self.assertEqual(decision(grid=4400, margin=4500).watts, (0, 0))
        self.assertEqual(decision(grid=2000, margin=4500).watts, (-2300, 0))


class Accounting(unittest.TestCase):
    def test_import_quarter_and_rollover(self):
        now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        quarter = energy.Quarter()
        for i in range(61):
            result = quarter.update(now + timedelta(seconds=10 * i), 4900, 4500)
        self.assertEqual(result["forecast_w"], 4900)
        self.assertEqual(result["above_seconds"], 600)
        self.assertAlmostEqual(result["allowed_w"], 3700)
        after = quarter.update(now + timedelta(minutes=15), 1000, 4500, official=0)
        self.assertEqual(after["allowed_w"], 4500)
        self.assertEqual(after["source"], "meter")
        self.assertEqual(after["above_seconds"], 0)

    def test_import_only_and_partial_restart(self):
        now = datetime(2026, 11, 18, 12, 3, tzinfo=timezone.utc)
        quarter = energy.Quarter()
        result = quarter.update(now, -300, 4500)
        self.assertFalse(result["complete"])
        result = quarter.update(now + timedelta(seconds=10), 320, 4500)
        self.assertEqual(result["energy_wh"], 0)
        self.assertGreater(result["allowed_w"], 4500)

    def test_source_losses_and_conservative_restart(self):
        before = energy.Battery(0, -1800, "Passive", 200, 20)
        after = energy.replace(before, soc=.1, input_wh=207)
        ledger = energy.account_measurement({}, before, after, "offpeak", "offpeak", (400, 450), 15)
        self.assertAlmostEqual(ledger["offpeak"], 5.12)
        self.assertFalse(ledger["unknown"])
        after_outage = energy.account_measurement(ledger, None, after, "offpeak", None, (None, None), 0)
        self.assertEqual(after_outage["unknown"], 5.12)
        unproven = energy.account_measurement(ledger, before, after, "peak", "offpeak", (400, 450), 15)
        self.assertEqual(unproven["unknown"], 5.12)


class Planning(unittest.TestCase):
    def test_learning_shadow_and_explicit_activation(self):
        today = datetime(2026, 11, 18)
        days = [dict(valid=True, evening_wh=2400 + i, weekend=i % 7 > 4,
                     date=(today - timedelta(days=45-i)).date().isoformat()) for i in range(44)]
        for day in days[30:]:
            day["prediction_wh"] = 2600
        def result(history, active):
            return energy.learning(history, False, 12, .15, 30, 14, active)
        self.assertEqual(result(days[:29], True)["applied_target"], 100)
        self.assertEqual(result(days[:43], True)["phase"], "shadow")
        self.assertEqual(result(days, False)["applied_target"], 100)
        active = result(days, True)
        self.assertEqual(active["phase"], "active")
        self.assertLess(active["applied_target"], 100)
        self.assertEqual(len(active["errors"]), 14)

    def test_24_physical_hours_and_same_policy(self):
        zone = ZoneInfo("Europe/Brussels")
        now = datetime(2026, 10, 24, 18, 0, tzinfo=zone)
        rows = energy.plan_24h(now, SCHEDULE, PRICES, (FIRST, SECOND),
                              ({"solar": 1800}, {"solar": 3072}), False, 400, lambda _: 0,
                              None, {"grid_limit": 4500, "minimum_soc": 12, "max_charge": 2500,
                                     "interval_minutes": 10}, 100)
        self.assertEqual(rows[0]["mode"], decision(grid=400).mode)
        self.assertEqual(rows[0]["status"], "planned")
        self.assertEqual(datetime.fromisoformat(rows[-1]["end"]).timestamp() - now.timestamp(), 86400)
        self.assertTrue(any(row["status"] == "blocked" for row in rows))
        self.assertEqual([row["end"] for row in rows[:-1]], [row["start"] for row in rows[1:]])


class Protocol(unittest.IsolatedAsyncioTestCase):
    async def test_documented_wh_counters(self):
        battery = client.MarstekClient("127.0.0.1", 30000)
        requests = []
        def reply(request):
            requests.append(request["method"])
            return {"total_grid_input_energy": 88, "total_grid_output_energy": 40}
        battery._roundtrip = reply
        self.assertEqual((await battery.get_energy_counters())["total_grid_input_energy"], 88)
        self.assertEqual(requests, ["ES.GetStatus"])

    async def test_expired_legacy_passive_restores_auto(self):
        battery = client.MarstekClient("127.0.0.1", 30000)
        replies = iter([{"mode": "Passive"}, {"set_result": True}, {"mode": "Auto"}])
        sent = []
        def reply(request):
            sent.append(request)
            return next(replies)
        battery._roundtrip = reply
        await battery.restore_from_passive("Auto")
        self.assertEqual(sent[1]["params"]["config"]["mode"], "Auto")
        self.assertEqual([request["method"] for request in sent], ["ES.GetMode", "ES.SetMode", "ES.GetMode"])


if __name__ == "__main__":
    unittest.main()
