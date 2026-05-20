"""Constants for the BYD Vehicle integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "byd_vehicle"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.DEVICE_TRACKER,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

CONF_BASE_URL = "base_url"
CONF_COUNTRY_CODE = "country_code"
CONF_LANGUAGE = "language"
CONF_POLL_INTERVAL = "poll_interval"
CONF_GPS_POLL_INTERVAL = "gps_poll_interval"
CONF_DEVICE_PROFILE = "device_profile"
CONF_CONTROL_PIN = "control_pin"
CONF_CLIMATE_DURATION = "climate_duration"
CONF_DEBUG_DUMPS = "debug_dumps"

DEFAULT_POLL_INTERVAL = 300
DEFAULT_GPS_POLL_INTERVAL = 300
DEFAULT_CLIMATE_DURATION = 10
DEFAULT_DEBUG_DUMPS = False
DEFAULT_COUNTRY = "United Kingdom"
DEFAULT_LANGUAGE = "en"

MIN_POLL_INTERVAL = 30
MAX_POLL_INTERVAL = 900
MIN_GPS_POLL_INTERVAL = 30
MAX_GPS_POLL_INTERVAL = 900

# Node-to-server mapping based on BYD app reverse engineering.
# Push server URLs are stored as reference metadata for future usage.
NODE_METADATA: dict[int, dict[str, str]] = {
    1: {
        "region": "Europe",
        "api_base_url": "https://dilinkappoversea-eu.byd.auto",
        "push_server": "https://dilinkpush-eu.byd.auto:8443",
    },
    2: {
        "region": "Singapore/APAC",
        "api_base_url": "https://dilinkappoversea-sg.byd.auto",
        "push_server": "https://dilinkpush-sg.byd.auto:8443",
    },
    3: {
        "region": "Australia",
        "api_base_url": "https://dilinkappoversea-au.byd.auto",
        "push_server": "https://dilinkpush-au.byd.auto:8443",
    },
    4: {
        "region": "Brazil",
        "api_base_url": "https://dilinkappoversea-br.byd.auto",
        "push_server": "https://dilinkpush-br.byd.auto:8443",
    },
    5: {
        "region": "Japan",
        "api_base_url": "https://dilinkappoversea-jp.byd.auto",
        "push_server": "https://dilinkpush-jp.byd.auto:8443",
    },
    6: {
        "region": "Uzbekistan",
        "api_base_url": "https://dilinkappoversea-uz.byd.auto",
        "push_server": "https://dilinkpush-uz.byd.auto:8443",
    },
    7: {
        "region": "Middle East/Africa",
        "api_base_url": "https://dilinkappoversea-no.byd.auto",
        "push_server": "https://dilinkpush-no.byd.auto:8443",
    },
    8: {
        "region": "Mexico/Latin America",
        "api_base_url": "https://dilinkappoversea-mx.byd.auto",
        "push_server": "https://dilinkpush-mx.byd.auto:8443",
    },
    9: {
        "region": "Indonesia",
        "api_base_url": "https://dilinkappoversea-id.byd.auto",
        "push_server": "https://dilinkpush-id.byd.auto:8443",
    },
    10: {
        "region": "Turkey",
        "api_base_url": "https://dilinkappoversea-tr.byd.auto",
        "push_server": "https://dilinkpush-tr.byd.auto:8443",
    },
    11: {
        "region": "Korea",
        "api_base_url": "https://dilinkappoversea-kr.byd.auto",
        "push_server": "https://dilinkpush-kr.byd.auto:8443",
    },
    12: {
        "region": "India",
        "api_base_url": "https://dilinkappoversea-in.byd.auto",
        "push_server": "https://dilinkpush-in.byd.auto:8443",
    },
    13: {
        "region": "Vietnam",
        "api_base_url": "https://dilinkappoversea-vn.byd.auto",
        "push_server": "https://dilinkpush-vn.byd.auto:8443",
    },
    14: {
        "region": "Saudi Arabia",
        "api_base_url": "https://dilinkappoversea-sa.byd.auto",
        "push_server": "https://dilinkpush-sa.byd.auto:8443",
    },
    15: {
        "region": "Oman",
        "api_base_url": "https://dilinkappoversea-om.byd.auto",
        "push_server": "https://dilinkpush-om.byd.auto:8443",
    },
    16: {
        "region": "Kazakhstan",
        "api_base_url": "https://dilinkappoversea-kz.byd.auto",
        "push_server": "https://dilinkpush-kz.byd.auto:8443",
    },
}

# Backward-compatible mapping retained for existing entry defaults and logs.
BASE_URLS: dict[str, str] = {
    node["region"]: node["api_base_url"] for node in NODE_METADATA.values()
}

# country label -> (country code, default language)
COUNTRY_OPTIONS: dict[str, tuple[str, str]] = {
    "Albania": ("AL", "en"),
    "Argentina": ("AR", "es"),
    "Australia": ("AU", "en"),
    "Austria": ("AT", "de"),
    "Bahrain": ("BH", "ar"),
    "Bangladesh": ("BD", "en"),
    "Belgium": ("BE", "en"),
    "Bhutan": ("BT", "en"),
    "Bolivia": ("BO", "es"),
    "Bosnia and Herzegovina": ("BA", "en"),
    "Brazil": ("BR", "pt"),
    "Brunei": ("BN", "en"),
    "Bulgaria": ("BG", "en"),
    "Cambodia": ("KH", "en"),
    "Chile": ("CL", "es"),
    "Colombia": ("CO", "es"),
    "Costa Rica": ("CR", "es"),
    "Croatia": ("HR", "en"),
    "Cyprus": ("CY", "en"),
    "Czech Republic": ("CZ", "en"),
    "Denmark": ("DK", "en"),
    "Dominican Republic": ("DO", "es"),
    "Ecuador": ("EC", "es"),
    "Egypt": ("EG", "ar"),
    "El Salvador": ("SV", "es"),
    "Estonia": ("EE", "en"),
    "Finland": ("FI", "en"),
    "France": ("FR", "fr"),
    "French Polynesia": ("PF", "fr"),
    "Germany": ("DE", "de"),
    "Greece": ("GR", "en"),
    "Guatemala": ("GT", "es"),
    "Hong Kong": ("HK", "zh_TW"),
    "Honduras": ("HN", "es"),
    "Hungary": ("HU", "en"),
    "Iceland": ("IS", "en"),
    "India": ("IN", "en"),
    "Indonesia": ("ID", "id"),
    "Ireland": ("IE", "en"),
    "Israel": ("IL", "he"),
    "Italy": ("IT", "it"),
    "Japan": ("JP", "ja"),
    "Jordan": ("JO", "ar"),
    "Kazakhstan": ("KZ", "ru"),
    "Kosovo": ("XK", "en"),
    "Kuwait": ("KW", "ar"),
    "Laos": ("LA", "en"),
    "Latvia": ("LV", "en"),
    "Liechtenstein": ("LI", "de"),
    "Lithuania": ("LT", "en"),
    "Luxembourg": ("LU", "fr"),
    "Macao": ("MO", "zh_TW"),
    "Malaysia": ("MY", "en"),
    "Maldives": ("MV", "en"),
    "Malta": ("MT", "en"),
    "Mauritius": ("MU", "en"),
    "Mexico": ("MX", "es"),
    "Moldova": ("MD", "ru"),
    "Monaco": ("MC", "fr"),
    "Mongolia": ("MN", "en"),
    "Montenegro": ("ME", "en"),
    "Morocco": ("MA", "ar"),
    "Myanmar": ("MM", "en"),
    "Nepal": ("NP", "en"),
    "Netherlands": ("NL", "nl"),
    "New Caledonia": ("NC", "fr"),
    "New Zealand": ("NZ", "en"),
    "Nicaragua": ("NI", "es"),
    "North Macedonia": ("MK", "en"),
    "Norway": ("NO", "en"),
    "Oman": ("OM", "ar"),
    "Pakistan": ("PK", "en"),
    "Panama": ("PA", "es"),
    "Paraguay": ("PY", "es"),
    "Peru": ("PE", "es"),
    "Philippines": ("PH", "en"),
    "Poland": ("PL", "en"),
    "Portugal": ("PT", "pt"),
    "Qatar": ("QA", "ar"),
    "Reunion Island": ("RE", "fr"),
    "Romania": ("RO", "en"),
    "Saudi Arabia": ("SA", "ar"),
    "Serbia": ("RS", "en"),
    "Singapore": ("SG", "en"),
    "Slovakia": ("SK", "en"),
    "Slovenia": ("SI", "en"),
    "South Africa": ("ZA", "en"),
    "South Korea": ("KR", "ko"),
    "Spain": ("ES", "es"),
    "Sri Lanka": ("LK", "en"),
    "Sweden": ("SE", "en"),
    "Switzerland": ("CH", "de"),
    "Thailand": ("TH", "th"),
    "Turkey": ("TR", "tr"),
    "Ukraine": ("UA", "ru"),
    "United Arab Emirates": ("AE", "ar"),
    "United Kingdom": ("GB", "en"),
    "Uruguay": ("UY", "es"),
    "Uzbekistan": ("UZ", "ru"),
    "Vatican City": ("VA", "it"),
    "Vietnam": ("VN", "vi"),
}

COUNTRY_TO_NODE: dict[str, int] = {
    # Node 1 - EU
    "NO": 1,
    "NL": 1,
    "DE": 1,
    "DK": 1,
    "SE": 1,
    "FR": 1,
    "AT": 1,
    "LU": 1,
    "BE": 1,
    "FI": 1,
    "IT": 1,
    "ES": 1,
    "PT": 1,
    "GB": 1,
    "IE": 1,
    "IS": 1,
    "IL": 1,
    "HU": 1,
    "MT": 1,
    "GR": 1,
    "CH": 1,
    "PL": 1,
    "CY": 1,
    "EE": 1,
    "LV": 1,
    "LT": 1,
    "CZ": 1,
    "RO": 1,
    "SK": 1,
    "SI": 1,
    "BG": 1,
    "HR": 1,
    "LI": 1,
    "ME": 1,
    "RS": 1,
    "BA": 1,
    "MK": 1,
    "AL": 1,
    "MD": 1,
    "MC": 1,
    "VA": 1,
    "XK": 1,
    "UA": 1,
    # Node 2 - SG/APAC
    "SG": 2,
    "TH": 2,
    "MY": 2,
    "HK": 2,
    "MO": 2,
    "KH": 2,
    "LA": 2,
    "PH": 2,
    "BN": 2,
    "MM": 2,
    "NP": 2,
    "BD": 2,
    "PK": 2,
    "LK": 2,
    "PF": 2,
    "NC": 2,
    "MN": 2,
    "BT": 2,
    "MV": 2,
    # Node 3 - AU
    "AU": 3,
    "NZ": 3,
    # Node 4 - BR
    "BR": 4,
    # Node 5 - JP
    "JP": 5,
    # Node 6 - UZ
    "UZ": 6,
    # Node 7 - MEA
    "AE": 7,
    "KW": 7,
    "QA": 7,
    "MA": 7,
    "BH": 7,
    "JO": 7,
    "ZA": 7,
    "RE": 7,
    "MU": 7,
    "EG": 7,
    # Node 8 - MX/LATAM
    "MX": 8,
    "CL": 8,
    "UY": 8,
    "CO": 8,
    "DO": 8,
    "CR": 8,
    "PE": 8,
    "EC": 8,
    "PY": 8,
    "BO": 8,
    "PA": 8,
    "GT": 8,
    "SV": 8,
    "HN": 8,
    "NI": 8,
    "AR": 8,
    # Node 9 - ID
    "ID": 9,
    # Node 10 - TR
    "TR": 10,
    # Node 11 - KR
    "KR": 11,
    # Node 12 - IN
    "IN": 12,
    # Node 13 - VN
    "VN": 13,
    # Node 14 - SA
    "SA": 14,
    # Node 15 - OM
    "OM": 15,
    # Node 16 - KZ
    "KZ": 16,
}

COUNTRY_BY_CODE: dict[str, tuple[str, str]] = {
    country_code: (country_name, language)
    for country_name, (country_code, language) in COUNTRY_OPTIONS.items()
}


def get_country_connection_settings(country_name: str) -> tuple[str, str, str]:
    """Return (country_code, language, api_base_url) for a configured country label."""
    country_code, language = COUNTRY_OPTIONS[country_name]
    node_id = COUNTRY_TO_NODE[country_code]
    return country_code, language, NODE_METADATA[node_id]["api_base_url"]


def get_country_connection_settings_by_code(country_code: str) -> tuple[str, str, str]:
    """Return (country_code, language, api_base_url) from a country code."""
    normalized_code = country_code.upper()
    _country_name, language = COUNTRY_BY_CODE[normalized_code]
    node_id = COUNTRY_TO_NODE[normalized_code]
    return normalized_code, language, NODE_METADATA[node_id]["api_base_url"]
