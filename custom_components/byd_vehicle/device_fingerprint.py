"""Generate a randomized but realistic Android device fingerprint."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

_POOL_FILE = Path(__file__).parent / "device_pool.json"


def _luhn_check_digit(partial: str) -> str:
    """Calculate the Luhn check digit for a partial IMEI (first 14 digits)."""
    digits = [int(d) for d in partial]
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - (total % 10)) % 10)


def _generate_imei(tac_prefix: str) -> str:
    """Generate a valid 15-digit IMEI using a real TAC prefix.

    The TAC prefix (first 8 digits) identifies the device manufacturer/model.
    The remaining 6 digits are a random serial, plus a Luhn check digit.
    """
    serial = "".join(str(random.randint(0, 9)) for _ in range(6))
    partial = tac_prefix + serial
    return partial + _luhn_check_digit(partial)


def _generate_mac() -> str:
    """Generate a random locally-administered unicast MAC address.

    The second nibble is set to 2/6/A/E (locally administered, unicast).
    Format: XX:XX:XX:XX:XX:XX
    """
    first_byte = random.randint(0, 255) | 0x02  # set locally-administered bit
    first_byte &= 0xFE  # clear multicast bit
    octets = [first_byte] + [random.randint(0, 255) for _ in range(5)]
    return ":".join(f"{b:02x}" for b in octets)


def _load_device_pool() -> list[dict]:
    """Load the curated device pool from the JSON file."""
    with _POOL_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def generate_device_profile() -> dict[str, str]:
    """Generate a complete, randomised DeviceProfile dict.

    Picks a random device from the pool, generates a valid IMEI with the
    device's TAC prefix, derives imei_md5, and generates a random MAC.
    All values are realistic for an Android 12-15 phone.

    Returns a dict whose keys match ``pybyd.config.DeviceProfile`` fields.
    """
    pool = _load_device_pool()
    device = random.choice(pool)

    # Pick a consistent sdk/os pair from the device's options
    idx = random.randrange(len(device["sdk_options"]))
    sdk = device["sdk_options"][idx]
    os_type = device["os_options"][idx]

    imei = _generate_imei(device["tac_prefix"])
    imei_md5 = hashlib.md5(imei.encode()).hexdigest()  # noqa: S324
    mac = _generate_mac()

    return {
        "ostype": "and",
        "imei": imei,
        "mac": mac,
        "model": device["model"],
        "sdk": sdk,
        "mod": device["mod"],
        "imei_md5": imei_md5,
        "mobile_brand": device["mobile_brand"],
        "mobile_model": device["mobile_model"],
        "device_type": "0",
        "network_type": "wifi",
        "os_type": os_type,
        "os_version": sdk,
    }
