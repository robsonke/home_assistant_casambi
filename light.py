"""
Support for Casambi lights.
For more details about this component, please refer to the documentation at
https://home-assistant.io/components/@todo
"""
# https://developers.home-assistant.io/docs/creating_component_index/
# https://github.com/home-assistant/core/blob/dev/homeassistant/components/unifi/__init__.py
# https://github.com/home-assistant/example-custom-config/tree/master/custom_components/example_light/
# https://developers.home-assistant.io/docs/asyncio_working_with_async/
# https://github.com/home-assistant/core/blob/master/homeassistant/components/deconz/deconz_device.py
# https://github.com/home-assistant/core/blob/master/homeassistant/components/deconz/light.py
# https://github.com/home-assistant/core/blob/dev/homeassistant/components/elgato/__init__.py
# https://developers.home-assistant.io/docs/core/entity/light

"""Support for LED lights."""
import logging
import pprint
import ssl
import asyncio
import aiocasambi
import async_timeout
import math

from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

import voluptuous as vol

from homeassistant.components.light import (
    ATTR_BRIGHTNESS_PCT,
    SUPPORT_BRIGHTNESS,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_NAME
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.helpers import aiohttp_client
from homeassistant.const import CONF_EMAIL, CONF_API_KEY

import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    WIRE_ID,
    CONF_USER_PASSWORD,
    CONF_NETWORK_PASSWORD,
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_SOFTWARE_VERSION,
    SCAN_INTERVAL_TIME_SECS
)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_USER_PASSWORD): cv.string,
        vol.Required(CONF_NETWORK_PASSWORD): cv.string,
        vol.Required(CONF_EMAIL): cv.string,
        vol.Required(CONF_API_KEY): cv.string,
    })
}, extra=vol.ALLOW_EXTRA)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=SCAN_INTERVAL_TIME_SECS)

UNITS = {}

async def async_setup_platform(hass: HomeAssistant, config: dict, async_add_entities, discovery_info=None):
    str_config = pprint.pformat(config)
    #_LOGGER.debug(f"async_setup_platform config: {str_config}")

    user_password = config[CONF_USER_PASSWORD]
    network_password = config[CONF_NETWORK_PASSWORD]
    email = config[CONF_EMAIL]
    api_key = config[CONF_API_KEY]

    #_LOGGER.debug(f"async_setup_platform user_password: {user_password} network_pasword: {network_password} email: {email} api_key: {api_key}")

    sslcontext = ssl.create_default_context()
    session = aiohttp_client.async_get_clientsession(hass)

    controller = aiocasambi.Controller(
        email=email,
        user_password=user_password,
        network_password=network_password,
        api_key=api_key,
        websession=session,
        sslcontext=sslcontext,
        wire_id=WIRE_ID,
        callback=signalling_callback,
    )

    try:
        with async_timeout.timeout(10):
            await controller.create_user_session()
            await controller.create_network_session()
            await controller.start_websocket()

    except aiocasambi.LoginRequired:
        _LOGGER.warning(f"Connected to casambi but couldn't log in")
        return False

    except aiocasambi.Unauthorized:
        _LOGGER.warning(f"Connected to casambi but not registered")
        return False

    except (asyncio.TimeoutError, aiocasambi.RequestError):
        _LOGGER.exception('Error connecting to the Casambi')
        return False

    except aiocasambi.AiocasambiException:
        _LOGGER.exception('Unknown Casambi communication error occurred')
        return False

    await controller.initialize()

    units =  controller.get_units()

    #_LOGGER.debug(f"Casambi unit: f{units}")

    for unit in units:
        #_LOGGER.debug(f"Casambi unit: f{unit}")
        casambi_light = CasambiLight(unit, controller)
        async_add_entities([casambi_light], True)

        UNITS[casambi_light.unique_id] = casambi_light

    return True


class CasambiLight(LightEntity):
    """Defines a Casambi Key Light."""

    def __init__(
        self, unit, controller,
    ):
        """Initialize Casambi Key Light."""
        self._brightness_pct: Optional[int] = None
        self._state: Optional[bool] = None
        self._temperature: Optional[int] = None
        self._available = True
        self.unit = unit
        self.controller = controller

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self.unit.name

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def unique_id(self) -> str:
        """Return the unique ID for this sensor."""
        return self.unit.unique_id

    @property
    def brightness_pct(self) -> Optional[int]:
        """Return the brightness of this light between 1..100."""
        return self._brightness_pct

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        return SUPPORT_BRIGHTNESS

    @property
    def is_on(self) -> bool:
        """Return the state of the light."""
        return bool(self._state)
    
    def process_update(self, data):
        """Process callback message,, update home assistant light state"""
        _LOGGER.debug(f"process_update self: {self} data: {data}")

        #if data.value > 0:
        #    self._state = True
        #    self._brightness = int(math.ceil(data.value * 255))
        #else:
        #    self._state = False
        self.async_schedule_update_ha_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        _LOGGER.debug(f"async_turn_off {self}")

        await self.unit.turn_unit_off()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        _LOGGER.debug(f"async_turn_on {self} kwargs: {kwargs}")

        await self.unit.turn_unit_on()

    @property
    def should_poll(self):
        """Disable polling by returning False"""
        return False

    async def async_update(self) -> None:
        """Update Casambi entity."""
        if self.unit.value > 0:
            self._state = True
            self._brightness_pct = int(math.ceil(self.unit.value * 100))
        else:
            self._state = False
        _LOGGER.debug(f"async_update {self}")

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information about this Casambi Key Light."""
        #return {
        #    ATTR_IDENTIFIERS: {(DOMAIN, self._info.serial_number)},
        #    ATTR_NAME: self._info.product_name,
        #    ATTR_MANUFACTURER: "Casambi",
        #    ATTR_MODEL: self._info.product_name,
        #    ATTR_SOFTWARE_VERSION: f"{self._info.firmware_version} ({self._info.firmware_build_number})",
        #}

        return {
            ATTR_IDENTIFIERS: {(DOMAIN, "fff")},
            ATTR_NAME: "Casambi",
            ATTR_MANUFACTURER: "Casambi",
            ATTR_MODEL: "Casambi",
            ATTR_SOFTWARE_VERSION: f"",
        }

    def __repr__(self) -> str:
        """Return the representation."""
        name = self.unit.name

        result = f"<Casambi light {name}: unit={self.unit}"

        return result


def signalling_callback(signal, data):
    _LOGGER.debug(f"signalling_callback signal: {signal} data: {data}")
    if signal == aiocasambi.websocket.SIGNAL_DATA:
        for key, value in data.items():
            UNITS[key].process_update(value)
