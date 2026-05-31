"""Light platform for netmesh DALI."""
import logging
import asyncio
import aiohttp
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from .const import DOMAIN, API_DEVICES, API_DEVICE_CONTROL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    host = hass.data[DOMAIN][entry.entry_id]["host"]
    devices = await _fetch_devices(host)
    entities = []
    known_ids = set()
    for device in devices:
        entities.append(NetmeshDaliLight(host, device, entry.entry_id))
        known_ids.add(device["id"])
    async_add_entities(entities, update_before_add=False)

    hass.data[DOMAIN][entry.entry_id]["known_ids"] = known_ids
    hass.data[DOMAIN][entry.entry_id]["async_add_entities"] = async_add_entities

    async def refresh_devices(now=None):
        while True:
            await asyncio.sleep(60)
            try:
                current_devices = await _fetch_devices(host)
                current_ids = {d["id"] for d in current_devices}
                new_ids = current_ids - hass.data[DOMAIN][entry.entry_id]["known_ids"]
                if new_ids:
                    new_entities = []
                    for device in current_devices:
                        if device["id"] in new_ids:
                            new_entities.append(NetmeshDaliLight(host, device, entry.entry_id))
                    if new_entities:
                        hass.data[DOMAIN][entry.entry_id]["async_add_entities"](new_entities, update_before_add=False)
                        hass.data[DOMAIN][entry.entry_id]["known_ids"].update(new_ids)
                        _LOGGER.info("Added %d new DALI device(s)", len(new_entities))
            except Exception as err:
                _LOGGER.debug("Device refresh error: %s", err)

    entry.async_create_background_task(hass, refresh_devices(), "netmesh_dali_refresh")

async def _fetch_devices(host):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{host}{API_DEVICES}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("devices", [])
    except Exception as err:
        _LOGGER.error("Failed to fetch devices from %s: %s", host, err)
    return []

class NetmeshDaliLight(LightEntity):
    _attr_should_poll = False

    def __init__(self, host, device, entry_id):
        self._host = host
        self._device_id = device["id"]
        self._address = device.get("address", 0)
        self._attr_name = device.get("name", f"DALI Device {self._device_id}")
        self._attr_unique_id = f"netmesh_dali_{host}_{self._device_id}"
        self._entry_id = entry_id
        features = device.get("features", {})
        self._has_brightness = "dimmable" in features
        self._has_cct = "colorKelvin" in features
        self._has_rgb = "colorRGB" in features
        if self._has_cct and self._has_rgb:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.RGB}
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_min_color_temp_kelvin = 2700
            self._attr_max_color_temp_kelvin = 6500
            self._attr_rgb_color = (255, 255, 255)
        elif self._has_cct:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_min_color_temp_kelvin = 2700
            self._attr_max_color_temp_kelvin = 6500
        elif self._has_rgb:
            self._attr_supported_color_modes = {ColorMode.RGB}
            self._attr_color_mode = ColorMode.RGB
            self._attr_rgb_color = (255, 255, 255)
        elif self._has_brightness:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF
        self._attr_is_on = features.get("switchable", {}).get("status", False)
        dim_pct = features.get("dimmable", {}).get("status", 0)
        self._attr_brightness = int(dim_pct * 2.55) if dim_pct else 0
        if self._has_cct:
            self._attr_color_temp_kelvin = features.get("colorKelvin", {}).get("status", 4000)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{host}_{self._device_id}")},
            "name": self._attr_name,
            "manufacturer": "netmesh",
            "model": "DALI-2 Control Gear",
            "sw_version": "1.0.0",
            "via_device": (DOMAIN, host),
        }

    async def async_turn_on(self, **kwargs):
        payload = {"switchable": True}
        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
            payload["dimmable"] = round(brightness / 2.55)
            self._attr_brightness = brightness
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            payload["colorKelvin"] = kelvin
            self._attr_color_temp_kelvin = kelvin
            self._attr_color_mode = ColorMode.COLOR_TEMP
        if ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            payload["colorRGB"] = {"r": r / 255.0, "g": g / 255.0, "b": b / 255.0}
            self._attr_rgb_color = (r, g, b)
            self._attr_color_mode = ColorMode.RGB
        self._attr_is_on = True
        self.async_write_ha_state()
        await self._send_control(payload)

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self._attr_brightness = 0
        self.async_write_ha_state()
        await self._send_control({"switchable": False})

    async def _send_control(self, payload):
        url = f"http://{self._host}{API_DEVICE_CONTROL.format(self._device_id)}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        _LOGGER.error("Control failed for device %d: HTTP %d", self._device_id, resp.status)
        except Exception as err:
            _LOGGER.error("Failed to send control to device %d: %s", self._device_id, err)
