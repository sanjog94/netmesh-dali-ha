"""Config flow for netmesh DALI."""
import logging
import socket
import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from .const import DOMAIN, API_INFO

_LOGGER = logging.getLogger(__name__)

class NetmeshDaliConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                info = await self._async_get_info(host)
                if info:
                    await self.async_set_unique_id(f"netmesh_dali_{host}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=info.get("name", "netmesh DALI"),
                        data={CONF_HOST: host},
                    )
                else:
                    errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"
        else:
            found = await self.hass.async_add_executor_job(self._discover)
            if found:
                return await self.async_step_user({CONF_HOST: found})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=""): str}),
            errors=errors,
        )

    async def _async_get_info(self, host):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{host}{API_INFO}", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as err:
            _LOGGER.debug("Cannot connect to %s: %s", host, err)
        return None

    def _discover(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(5.0)
            sock.sendto(b"discovery", ("255.255.255.255", 5555))
            data, addr = sock.recvfrom(1024)
            response = data.decode("utf-8")
            sock.close()
            if "dali-2-iot" in response or "netmesh" in response:
                return addr[0]
        except Exception:
            pass
        return None
