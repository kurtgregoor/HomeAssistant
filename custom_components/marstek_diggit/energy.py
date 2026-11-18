"""Tariff-aware, side-effect-free policy and energy accounting."""

from dataclasses import dataclass, replace
from datetime import timedelta, timezone
from decimal import Decimal, InvalidOperation
from math import ceil, isfinite

CHARGE_EFFICIENCY = 0.90
DISCHARGE_EFFICIENCY = 0.90
CAPACITY_WH = 5120
SOURCES = ("super_offpeak", "offpeak", "peak", "solar", "unknown")
CHEAP = ("offpeak", "super_offpeak")


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def tariff_at(local, schedule):
    minute = local.hour * 60 + local.minute
    for offset in (0, 1):
        profile = "weekday" if (local.weekday() - offset) % 7 < 5 else "weekend"
        for tariff, blocks in schedule.get(profile, {}).items():
            for block in blocks:
                start, end = (
                    int(value[:2]) * 60 + int(value[3:5]) for value in block.split("-")
                )
                if offset == 0 and (start <= minute < end or end < start <= minute):
                    return tariff
                if offset == 1 and end < start and minute < end:
                    return tariff
    return None


def price(prices, tariff):
    try:
        result = Decimal(str(prices.get(tariff)))
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def permitted_energy(ledger, tariff, prices):
    """Allow Auto only if every remaining Wh is eligible.

    A battery cannot select which administrative energy bucket to discharge.
    """
    current = price(prices, tariff)
    if current is None:
        return False
    eligible = 0
    for source, amount in ledger.items():
        if amount <= 0:
            continue
        cost = Decimal(0) if source == "solar" else price(prices, source)
        if source == "unknown" or cost is None or cost >= current:
            return False
        eligible += amount
    return eligible > 0


def reconcile_energy(previous, stored_wh, source="unknown", attributable_wh=0):
    """Track stored Wh. Deduct proportionally to preserve unknown fractions."""
    buckets = {key: max(0, previous.get(key, 0)) for key in SOURCES}
    total = sum(buckets.values())
    if total > stored_wh:
        return {key: value * stored_wh / total for key, value in buckets.items()}
    gain = stored_wh - total
    credited = min(gain, max(0, attributable_wh))
    buckets[source] += credited
    buckets["unknown"] += gain - credited
    return buckets


def account_measurement(previous, before, after, tariff, before_tariff, grid_pair, seconds):
    """Credit source only with corroborating counter and uninterrupted samples."""
    stored = after.soc * CAPACITY_WH / 100
    known = None
    if (
        before and 0 < seconds <= 30 and before_tariff == tariff
        and before.input_wh is not None and after.input_wh is not None
        and before.output_wh is not None and after.output_wh == before.output_wh
        and before.mode == after.mode
        and before.watts < -50 and after.watts < -50
    ):
        delta = after.input_wh - before.input_wh
        if 0 < delta <= 2500 * seconds / 3600 + 1:
            if all(watts is not None and watts <= -50 for watts in grid_pair):
                known = "solar"
            # Mixed solar and grid cannot be separated using net power alone.
            # The caller may certify zero PV during both samples.
            elif tariff in CHEAP + ("peak",) and all(
                watts is not None and watts >= 50 for watts in grid_pair
            ):
                known = tariff
            if known:
                return reconcile_energy(previous, stored, known, delta * CHARGE_EFFICIENCY)
    # After a telemetry gap, unobserved cycling may have replaced existing energy.
    if before is None or not 0 < seconds <= 30 or (
        before.input_wh is None or after.input_wh is None
        or after.input_wh != before.input_wh
        or (before.output_wh is not None and after.output_wh is not None
            and after.output_wh < before.output_wh)
    ):
        return reconcile_energy({}, stored)
    return reconcile_energy(previous, stored)


@dataclass(frozen=True)
class Battery:
    soc: float
    watts: float
    mode: str
    input_wh: float = None
    output_wh: float = None

    @classmethod
    def from_status(cls, status):
        soc = number(status.get("bat_soc"))
        watts = number(status.get("ongrid_power"))
        mode = status.get("mode")
        if soc is None or not 0 <= soc <= 100 or watts is None or mode not in ("Auto", "Passive"):
            return None
        incoming = number(status.get("total_grid_input_energy"))
        outgoing = number(status.get("total_grid_output_energy"))
        return cls(soc, watts, mode, incoming, outgoing)


@dataclass(frozen=True)
class Decision:
    mode: str
    target: float
    watts: tuple
    reason: str
    blocks: tuple = ()


def decide(tariff, prices, batteries, ledgers, grid, ev, margin, target, minimum,
           max_charge=2500, *, peak_auto=False):
    target = target if tariff == "offpeak" else 100
    if peak_auto and tariff == "peak" and ev is False:
        if len(batteries) == 2 and all(battery is not None for battery in batteries):
            return Decision("SELF_CONSUMPTION", target, (None, None), "Piek en wagen laadt niet")
        return Decision("SAFE_FALLBACK", target, (0, 0), "Batterijmodus niet bevestigd", ("telemetrie",))
    if grid is None or ev is None or len(batteries) != 2 or any(battery is None for battery in batteries):
        return Decision("SAFE_FALLBACK", target, (0, 0), "Kritieke meting of modus ontbreekt",
                        ("telemetrie",))
    if tariff is None:
        return Decision("SAFE_FALLBACK", target, (0, 0), "Geen geldig tariefblok", ("tarief",))
    output = sum(battery.watts for battery in batteries)
    base = grid + output
    headroom = max(0, (margin or 0) - base - 200)
    solar_budget = max(0, -base - 100)
    net_allowed = tariff in CHEAP and not ev
    budget = headroom if net_allowed else min(solar_budget, headroom)
    candidates = [i for i, battery in enumerate(batteries) if battery.soc < target]
    if not candidates and target < 100 and solar_budget >= 100:
        # A learned target reduces paid charging. Surplus can fill unused capacity.
        net_allowed = False
        target = 100
        candidates = [i for i, battery in enumerate(batteries) if battery.soc < target]
        budget = min(solar_budget, headroom)
    if not net_allowed:
        # Existing charging can be kept only if the export budget covers it.
        budget = min(budget, max(0, -grid + sum(max(0, -b.watts) for b in batteries) - 100))
    blocks = []
    if ev:
        blocks.append("auto laadt")
    if any(battery.watts < -50 for battery in batteries):
        blocks.append("batterij laadt")
    if any(battery.soc <= minimum for battery in batteries):
        blocks.append("minimum-SoC")
    if len(ledgers) != 2 or not all(permitted_energy(ledger, tariff, prices) for ledger in ledgers):
        blocks.append("energieherkomst of tarief")
    if candidates and budget >= 100:
        selected = min(candidates, key=lambda index: (batteries[index].watts >= -50, batteries[index].soc))
        watts = min(max_charge, int(budget // 50) * 50)
        if any(battery.watts > 50 for battery in batteries):
            return Decision("HOLDING", target, (0, 0), "Eerst ontlading stoppen en rust bevestigen",
                            tuple(blocks) + ("batterij ontlaadt",))
        return Decision("CHARGING", target, tuple(-watts if i == selected else 0 for i in range(2)),
                        "Laden binnen kwartiermarge" if net_allowed else "Gemeten overschot laden",
                        tuple(blocks))
    if tariff == "peak" and not blocks:
        return Decision("SELF_CONSUMPTION", target, (None, None), "Auto via CT003")
    reason = "Laadbudget te klein" if candidates and net_allowed else "Energie vasthouden"
    return Decision("HOLDING", target, (0, 0), reason, tuple(blocks))


class Quarter:
    def __init__(self):
        self.start = None
        self.last = None
        self.energy = 0
        self.covered = 0
        self.above_since = None

    def update(self, now, power, limit, official=None):
        timestamp = now.timestamp()
        start = int(timestamp // 900) * 900
        if self.start != start:
            self.energy = self.covered = 0
            self.start = start
        if self.last:
            old_ts, old_watts = self.last
            dt = timestamp - max(old_ts, start)
            if power is not None and old_watts is not None and 0 <= timestamp - old_ts <= 30 and dt > 0:
                self.energy += max(0, old_watts) * dt / 3600
                self.covered += dt
        if power is None or power <= limit:
            self.above_since = None
        elif self.above_since is None or (self.last and timestamp - self.last[0] > 30):
            self.above_since = timestamp
        self.last = timestamp, power
        elapsed = timestamp - start
        remaining = 900 - elapsed
        measured = official if official is not None else self.energy
        # Reserve the configured limit for unobserved seconds. Predictions
        # stay explicitly partial until the whole interval is accounted for.
        missing = max(0, elapsed - self.covered)
        estimated = measured + (missing * limit / 3600 if official is None else 0)
        future = max(0, power) if power is not None else None
        return {
            "grid_w": power, "energy_wh": round(measured, 2),
            "average_w": round(estimated * 3600 / elapsed) if elapsed > 0 else None,
            "forecast_w": round((estimated * 3600 + future * remaining) / 900) if future is not None else None,
            "remaining_seconds": round(remaining),
            "allowed_w": max(0, (limit * 900 - estimated * 3600) / remaining),
            "limit_w": limit, "above_seconds": int(timestamp - self.above_since) if self.above_since is not None else 0,
            "source": "meter" if official is not None else "estimated",
            "complete": official is not None or missing <= 1,
        }


def learning(days, weekend, minimum, margin, learn_days, shadow_days, active):
    training = [day for day in days if day["valid"] and "prediction_wh" not in day]
    shadow = [day for day in days if day["valid"] and day.get("prediction_wh") is not None]
    complete = len(training) >= learn_days
    pool = [day for day in days if day["valid"]]
    comparable = [day for day in pool if day["weekend"] == weekend]
    pool = (comparable if len(comparable) >= 5 else pool)[-30:]
    weights = range(1, len(pool) + 1)
    forecast = sum(day["evening_wh"] * weight for day, weight in zip(pool, weights)) / sum(weights) if pool else None
    theoretical = min(100, ceil(minimum + 100 * forecast * (1 + margin) / (
        2 * CAPACITY_WH * DISCHARGE_EFFICIENCY
    ))) if complete and forecast is not None else 100
    phase = "learning" if not complete else (
        "active" if active and len(shadow) >= shadow_days else "shadow"
    )
    errors = [{"date": day["date"], "predicted_wh": day["prediction_wh"],
               "actual_wh": day["evening_wh"],
               "error_wh": round(day["prediction_wh"] - day["evening_wh"])} for day in shadow[-30:]]
    return {"phase": phase, "valid_days": len(training) + len(shadow), "shadow_days": len(shadow),
            "forecast_wh": round(forecast) if forecast is not None else None,
            "target": theoretical, "applied_target": theoretical if phase == "active" else 100,
            "confidence": "historical" if complete and len(shadow) >= shadow_days else "insufficient",
            "errors": errors}


def plan_24h(now, schedule, prices, batteries, ledgers, ev, household, solar, forecast_wh,
             settings, target):
    """Project 24 physical hours. Reuse the live policy on each segment."""
    current = now.astimezone(timezone.utc)
    end = current + timedelta(hours=24)
    plan = []
    ledgers = [dict(ledger) for ledger in ledgers]
    batteries = tuple(replace(battery, watts=0) if battery else None for battery in batteries)
    while current < end:
        local = current.astimezone(now.tzinfo)
        tariff = tariff_at(local, schedule)
        until = min(end, current.replace(second=0, microsecond=0) + timedelta(minutes=1))
        duration = (until - current).total_seconds() / 3600
        pv = solar(local) if solar else None
        demand = household
        if tariff == "peak" and 17 <= local.hour < 23 and forecast_wh is not None:
            demand = forecast_wh / 6
        grid = max(0, demand) - (pv or 0) if demand is not None else None
        assumed_ev = ev if (current - now.astimezone(timezone.utc)).total_seconds() < settings["interval_minutes"] * 60 else False
        decision = decide(tariff, prices, batteries, ledgers, grid, assumed_ev,
                          settings["grid_limit"], target, settings["minimum_soc"], settings["max_charge"],
                          peak_auto=settings.get("peak_auto", False))
        if all(batteries):
            batteries = tuple(replace(b, soc=min(decision.target, b.soc + max(0, -(w or 0)) * duration *
                                                  CHARGE_EFFICIENCY * 100 / CAPACITY_WH))
                              if (w or 0) < 0 else b for b, w in zip(batteries, decision.watts))
            for i, (battery, watts) in enumerate(zip(batteries, decision.watts)):
                if (watts or 0) < 0 and i < len(ledgers):
                    source = "solar" if grid < watts else tariff if pv == 0 else "unknown"
                    ledgers[i] = reconcile_energy(
                        ledgers[i], battery.soc * CAPACITY_WH / 100, source,
                        -watts * duration * CHARGE_EFFICIENCY)
            if decision.mode == "SELF_CONSUMPTION" and grid is not None and grid > 0:
                # Only a system-level estimate. CT003 owns the real split.
                usable = [max(0, b.soc - settings["minimum_soc"]) for b in batteries]
                required = grid * duration * 100 / (CAPACITY_WH * DISCHARGE_EFFICIENCY)
                fraction = min(1, required / sum(usable)) if sum(usable) else 0
                batteries = tuple(replace(b, soc=b.soc - spare * fraction) for b, spare in zip(batteries, usable))
                for i, battery in enumerate(batteries):
                    ledgers[i] = reconcile_energy(ledgers[i], battery.soc * CAPACITY_WH / 100)
        soc = [round(b.soc, 1) if b else None for b in batteries]
        row = {"start": local.isoformat(), "end": until.astimezone(now.tzinfo).isoformat(),
               "tariff": tariff, "mode": decision.mode, "reason": decision.reason, "target": decision.target,
               "soc": soc, "solar_w": pv, "household_w": round(demand) if demand is not None else None,
               "status": "blocked" if decision.mode == "SAFE_FALLBACK" or (
                   tariff == "peak" and decision.mode == "HOLDING" and decision.blocks) else "planned"}
        group = ("tariff", "mode", "reason", "target", "solar_w", "household_w", "status")
        if plan and all(plan[-1][key] == row[key] for key in group):
            plan[-1].update(end=row["end"], soc=soc)
        else:
            plan.append(row)
        current = until
    return plan
