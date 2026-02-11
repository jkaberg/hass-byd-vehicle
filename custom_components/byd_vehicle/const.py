"""Constants for the BYD Vehicle integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "byd_vehicle"

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.CLIMATE,
    Platform.LOCK,
    Platform.SWITCH,
]

CONF_BASE_URL = "base_url"
CONF_COUNTRY_CODE = "country_code"
CONF_LANGUAGE = "language"
CONF_POLL_INTERVAL = "poll_interval"
CONF_GPS_POLL_INTERVAL = "gps_poll_interval"

DEFAULT_POLL_INTERVAL = 300
DEFAULT_GPS_POLL_INTERVAL = 300
DEFAULT_COUNTRY = "Netherlands"
DEFAULT_COUNTRY_CODE = "NL"
DEFAULT_LANGUAGE = "en"

BASE_URLS: dict[str, str] = {
    "Europe": "https://dilinkappoversea-eu.byd.auto",
    "Australia": "https://dilinkappoversea-au.byd.auto",
}

COUNTRY_OPTIONS: dict[str, tuple[str, str]] = {
    "Australia": ("AU", "en"),
    "Austria": ("AT", "de"),
    "Belgium": ("BE", "en"),
    "Brazil": ("BR", "pt"),
    "Colombia": ("CO", "es"),
    "Costa Rica": ("CR", "es"),
    "Denmark": ("DK", "da"),
    "El Salvador": ("SV", "es"),
    "France": ("FR", "fr"),
    "Germany": ("DE", "de"),
    "Hong Kong": ("HK", "zh"),
    "India": ("IN", "en"),
    "Indonesia": ("ID", "id"),
    "Japan": ("JP", "ja"),
    "Malaysia": ("MY", "ms"),
    "Mexico": ("MX", "es"),
    "Netherlands": ("NL", "nl"),
    "Norway": ("NO", "no"),
    "Pakistan": ("PK", "en"),
    "Philippines": ("PH", "en"),
    "Poland": ("PL", "pl"),
    "South Africa": ("ZA", "en"),
    "South Korea": ("KR", "ko"),
    "Sweden": ("SE", "sv"),
    "Thailand": ("TH", "th"),
    "Turkey": ("TR", "tr"),
    "United Kingdom": ("GB", "en"),
    "Uzbekistan": ("UZ", "uz"),
}
