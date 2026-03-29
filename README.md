# BYD Vehicle Integration for Home Assistant

Home Assistant custom integration for BYD vehicles, powered by [pyBYD](https://github.com/jkaberg/pyBYD).

[![Matrix](https://img.shields.io/matrix/hass-byd-vehicle%3Akaberg.me?server_fqdn=matrix.kaberg.me&fetchMode=summary)](https://matrix.to/#/#hass-byd-vehicle:kaberg.me)

> [!NOTE]
> The integration and pyBYD are nearing feature complete. A small number of API values still need final mapping/validation. Follow ongoing mapping work in pyBYD issue #20: https://github.com/jkaberg/pyBYD/issues/20

## Installation

### Option 1: HACS (Custom Repository)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jkaberg&repository=hass-byd-vehicle&category=Integration)

1. Open HACS → **Integrations**.
2. Open the menu (**⋮**) → **Custom repositories**.
3. Add `https://github.com/jkaberg/hass-byd-vehicle` as **Integration**.
4. Install **BYD Vehicle**.
5. Restart Home Assistant.
6. Add **BYD Vehicle** from **Settings → Devices & Services**.

### Option 2: Manual

1. Open your Home Assistant config directory.
2. Create `custom_components/` if needed.
3. Copy `custom_components/byd_vehicle/` from this repository into your HA config.
4. Restart Home Assistant.
5. Add **BYD Vehicle** from **Settings → Devices & Services**.

## Initial setup

Configuration is UI-only via Home Assistant config flow.

> [!TIP]
> Use an dedicated BYD account for the integration, that way you won't be logged out from the BYD app on your main account - see [here](https://www.youtube.com/watch?v=DRzsjYHjlqQ) for instructions.

> [!IMPORTANT]
> If you intend to control the car via the integration (turn on/off A/C, lock the car etc.), it's crucial that you set up an operation/control PIN in the BYD app prior to setting up this integration. This also applies if you use an dedicated account for the integration, which means the dedicated account must also set an control PIN.

| Field | Required | Default | Description |
|---|---|---|---|
| Username | Yes | — | BYD account username (email/phone). |
| Password | Yes | — | BYD account password. |
| Country | Yes | United Kingdom | Country used for country code and language. |
| Control PIN | No | — | Optional PIN used for remote commands. |
| Climate duration | No | 10 | Climate run time in minutes. |
| Debug dump API responses | No | Off | Writes API request/response traces for troubleshooting. |

> [!TIP]
> If you get invalid authentication, verify credentials first, then verify selected country.

## After setup

Entity updates are cloud-polled, poll intervals are exposed as entities and can be tuned using automations.

## Documentation

- Troubleshooting: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- Contributing: [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)
