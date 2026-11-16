"""Marstek Open API over UDP."""

import asyncio
from itertools import count
import json
import socket

DAY_BITS = {
    "mon": 1, "tue": 2, "wed": 4, "thu": 8,
    "fri": 16, "sat": 32, "sun": 64,
}
MODE_CONFIG = {"Auto": "auto_cfg", "AI": "ai_cfg", "UPS": "ups_cfg"}
MODE_FIELDS = ("mode", "workmode", "work_mode", "esmode", "current_mode", "active_mode")
MODES = {mode.lower(): mode for mode in (*MODE_CONFIG, "Manual", "Passive")}


class MarstekError(Exception):
    """The battery did not confirm the request."""


class MarstekModeRejected(MarstekError):
    """The battery explicitly refused a mode change."""


class MarstekClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.lock = asyncio.Lock()
        self._ids = count(1)

    def _roundtrip(self, request):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(5)
                sock.connect((self.host, self.port))
                sock.send(json.dumps(request).encode())
                response = json.loads(sock.recv(65535))
        except (OSError, ValueError) as exc:
            raise MarstekError(f"{request['method']}: geen geldig antwoord van de batterij") from exc

        if not isinstance(response, dict) or response.get("id") != request["id"]:
            raise MarstekError(f"{request['method']}: onverwacht antwoord")
        if "error" in response:
            raise MarstekError(f"{request['method']}: {response['error']}")
        if not isinstance(response.get("result"), (dict, str)):
            raise MarstekError(f"{request['method']}: resultaat ontbreekt")
        return response["result"]

    async def _request(self, method, **params):
        request = {"id": next(self._ids), "method": method, "params": params or {"id": 0}}
        return await asyncio.to_thread(self._roundtrip, request)

    async def _set(self, mode, **config):
        result = await self._request("ES.SetMode", id=0, config={"mode": mode, **config})
        if isinstance(result, dict) and result.get("set_result") in (False, "false", "0"):
            raise MarstekModeRejected(f"De batterij heeft {mode} geweigerd")
        if not isinstance(result, dict):
            raise MarstekError(f"De batterij heeft {mode} niet bevestigd")

    async def _get_status(self):
        result = await self._request("ES.GetMode")
        status = dict(result) if isinstance(result, dict) else {"mode": result}
        for field in MODE_FIELDS:
            mode = status.get(field)
            if isinstance(mode, str) and mode.strip():
                status["mode"] = MODES.get(mode.strip().lower(), mode.strip())
                return status
        raise MarstekError("De batterij heeft geen modus teruggegeven")

    async def get_status(self):
        async with self.lock:
            return await self._get_status()

    async def get_device_info(self):
        async with self.lock:
            result = await self._request("Marstek.GetDevice", ble_mac="0")
        if not isinstance(result, dict) or not (result.get("device") or result.get("ver")):
            raise MarstekError("De batterij heeft geen model of firmwareversie teruggegeven")
        return {
            label: result[key]
            for key, label in (("device", "model"), ("ver", "firmware"))
            if result.get(key) is not None
        }

    async def set_mode(self, mode):
        async with self.lock:
            await self._set(mode, **{MODE_CONFIG[mode]: {"enable": 1}})

    async def set_passive(self, power, duration_seconds):
        async with self.lock:
            await self._set("Passive", passive_cfg={"power": power, "cd_time": duration_seconds})

    async def restore_from_passive(self, mode):
        async with self.lock:
            if (await self._get_status())["mode"] != "Passive":
                return
            await self._set(mode, **{MODE_CONFIG[mode]: {"enable": 1}})
            await asyncio.sleep(1.2)
            current = (await self._get_status())["mode"]
            if current != mode:
                raise MarstekError(f"Verwachte modus {mode}, batterij meldt {current}")

    async def write_slot(self, schedule, activate_manual):
        async with self.lock:
            previous_mode = None
            if not activate_manual:
                previous_mode = (await self._get_status())["mode"]
                if previous_mode not in (*MODE_CONFIG, "Manual"):
                    raise MarstekError(
                        f"Slot niet geschreven: {previous_mode} kan niet worden hersteld. "
                        "Kies Manual activeren om bewust van modus te wisselen."
                    )

            try:
                await self._set("Manual", manual_cfg=schedule)
            finally:
                if previous_mode in MODE_CONFIG:
                    try:
                        await asyncio.sleep(1.2)
                        await self._set(previous_mode, **{MODE_CONFIG[previous_mode]: {"enable": 1}})
                    except MarstekError as exc:
                        raise MarstekError(
                            f"Herstel naar {previous_mode} mislukt. Controleer de batterijmodus "
                            "en het tijdslot."
                        ) from exc
