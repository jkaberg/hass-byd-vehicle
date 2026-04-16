import logging
import time
import httpx
import json # <--- New import
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

ABRP_API_URL = "https://api.iternio.com/1/tlm/send"
API_KEY = "32b2162f-9599-4647-8139-66e9f9528370"

async def async_send_telemetry(hass: HomeAssistant, token: str, data: dict):
    """Send vehicle telemetry to ABRP."""
    
    payload = {
        "utc": int(time.time()),
        "soc": data.get("soc"),
        "speed": data.get("speed"),
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "is_charging": data.get("is_charging"),
        "ext_temp": data.get("ext_temp"),
        "odometer": data.get("odometer"),
        "range": data.get("range"),
    }

    # Remove None values
    payload = {k: v for k, v in payload.items() if v is not None}

    # ABRP requires the 'tlm' parameter to be a JSON-encoded STRING
    params = {
        "api_key": API_KEY,
        "token": token,
        "tlm": json.dumps(payload) # <--- Encodes with double quotes
    }

    try:
        # We use verify=False to stop the "Blocking Call" warning in HA logs
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(ABRP_API_URL, params=params, timeout=10)
            _LOGGER.debug("ABRP Payload Sent: %s", json.dumps(payload))
            _LOGGER.debug("ABRP Response: %s", response.text)
            response.raise_for_status()
    except Exception as ex:
        _LOGGER.error("Failed to send data to ABRP: %s", ex)
