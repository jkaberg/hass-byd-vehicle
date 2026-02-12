#!/usr/bin/env python3
"""Comprehensive translation grammar/quality fix script for all locales."""

import json
from pathlib import Path

TRANS = Path("custom_components/byd_vehicle/translations")


def set_path(data: dict, path: str, value: str) -> None:
    """Set a nested dict value by dotted path."""
    keys = path.split(".")
    d = data
    for k in keys[:-1]:
        d = d[k]
    d[keys[-1]] = value


def fix_de(data: dict) -> None:
    """Fix German translations."""
    set_path(data, "config.step.user.data.control_pin", "Steuerungs-PIN (optional, 6-stellig)")
    set_path(data, "config.error.invalid_control_pin", "Ungültiger Steuerungs-PIN oder Cloud-Steuerung ist vorübergehend gesperrt")
    set_path(data, "entity.sensor.full_hour.name", "Stunden bis voll")
    set_path(data, "entity.sensor.full_minute.name", "Minuten bis voll")
    set_path(data, "entity.binary_sensor.charge_heat_state.name", "Ladeheizung")
    set_path(data, "entity.button.flash_lights.name", "Lichthupe")
    set_path(data, "entity.climate.climate.state_attributes.preset_mode.state.max_heat", "Max. Heizung")


def fix_es(data: dict) -> None:
    """Fix Spanish translations."""
    set_path(data, "options.step.init.title", "Actualizar sondeo")
    set_path(data, "config.error.invalid_control_pin", "PIN de control no válido o el control en la nube está bloqueado temporalmente")
    set_path(data, "config.error.unknown", "Error inesperado")
    set_path(data, "entity.sensor.time_to_full.name", "Tiempo de carga completa")
    set_path(data, "entity.sensor.tirepressure_system.name", "Estado TPMS")
    set_path(data, "entity.sensor.abs_warning.name", "Advertencia ABS")
    set_path(data, "entity.sensor.upgrade_status.name", "Estado de actualización OTA")
    # Capitalize entity names consistently
    set_path(data, "entity.binary_sensor.left_front_door.name", "Puerta delantera izquierda")
    set_path(data, "entity.binary_sensor.right_front_door.name", "Puerta delantera derecha")
    set_path(data, "entity.binary_sensor.left_front_window.name", "Ventana delantera izquierda")
    set_path(data, "entity.binary_sensor.right_front_window.name", "Ventana delantera derecha")
    set_path(data, "entity.binary_sensor.left_rear_window.name", "Ventana trasera izquierda")
    set_path(data, "entity.binary_sensor.right_rear_window.name", "Ventana trasera derecha")
    set_path(data, "entity.button.flash_lights.name", "Luces de destello")
    set_path(data, "entity.button.find_car.name", "Encontrar auto")
    set_path(data, "entity.button.close_windows.name", "Cerrar ventanas")
    set_path(data, "entity.sensor.refrigerator_door_state.name", "Puerta del refrigerador")


def fix_fr(data: dict) -> None:
    """Fix French translations."""
    set_path(data, "config.step.user.description", "Configurez votre compte BYD.")
    set_path(data, "config.step.user.data.control_pin", "PIN de contrôle (facultatif, 6 chiffres)")
    set_path(data, "config.error.invalid_control_pin", "PIN de contrôle invalide ou le contrôle cloud est temporairement verrouillé")
    set_path(data, "options.step.init.title", "Mettre à jour l'interrogation")
    set_path(data, "entity.sensor.wait_status.name", "Statut d'attente de charge")
    set_path(data, "entity.sensor.booking_charging_minute.name", "Minute de charge programmée")
    set_path(data, "entity.sensor.abs_warning.name", "Avertissement ABS")
    set_path(data, "entity.sensor.oil_endurance.name", "Autonomie carburant")
    set_path(data, "entity.binary_sensor.left_rear_window.name", "Vitre arrière gauche")
    set_path(data, "entity.binary_sensor.right_rear_window.name", "Vitre arrière droite")
    set_path(data, "entity.button.flash_lights.name", "Appels de phares")


def fix_pt(data: dict) -> None:
    """Fix Portuguese translations."""
    set_path(data, "options.step.init.title", "Atualizar consulta")
    set_path(data, "config.step.user.data.control_pin", "PIN de controle (opcional, 6 dígitos)")
    set_path(data, "config.step.user.data.poll_interval", "Intervalo de consulta (segundos)")
    set_path(data, "config.step.user.data.gps_poll_interval", "GPS intervalo de consulta (segundos)")
    set_path(data, "config.step.user.data.smart_gps_polling", "Consulta GPS inteligente")
    set_path(data, "config.error.invalid_control_pin", "PIN de controle inválido ou controle de nuvem está temporariamente bloqueado")
    set_path(data, "options.step.init.data.poll_interval", "Intervalo de consulta (segundos)")
    set_path(data, "options.step.init.data.gps_poll_interval", "GPS intervalo de consulta (segundos)")
    set_path(data, "options.step.init.data.smart_gps_polling", "Consulta GPS inteligente")
    set_path(data, "entity.sensor.time_to_full.name", "Tempo de carga completa")
    set_path(data, "entity.sensor.wait_status.name", "Status de espera de carga")
    set_path(data, "entity.sensor.tirepressure_system.name", "Estado TPMS")
    set_path(data, "entity.sensor.abs_warning.name", "Aviso ABS")
    set_path(data, "entity.sensor.upgrade_status.name", "Status de atualização OTA")
    set_path(data, "entity.binary_sensor.is_online.name", "Online")


def fix_da(data: dict) -> None:
    """Fix Danish translations."""
    set_path(data, "options.step.init.title", "Opdatér polling")
    set_path(data, "entity.sensor.ev_endurance.name", "EV-rækkevidde")
    set_path(data, "entity.sensor.full_minute.name", "Minutter til fuld")
    set_path(data, "entity.sensor.charge_remaining_hours.name", "Resterende ladetimer")
    set_path(data, "entity.sensor.charge_remaining_minutes.name", "Resterende lademinutter")
    set_path(data, "entity.sensor.svs.name", "Service påkrævet snart")
    set_path(data, "entity.binary_sensor.skylight.name", "Soltag")
    set_path(data, "entity.binary_sensor.left_rear_door_lock.name", "Venstre bagdørlås")
    set_path(data, "entity.button.flash_lights.name", "Lyshorn")


def fix_no(data: dict) -> None:
    """Fix Norwegian translations."""
    set_path(data, "options.step.init.title", "Oppdater polling")
    set_path(data, "config.step.user.data.poll_interval", "Pollingintervall (sekunder)")
    set_path(data, "options.step.init.data.poll_interval", "Pollingintervall (sekunder)")
    set_path(data, "entity.sensor.endurance_mileage.name", "Rekkevidde")
    set_path(data, "entity.sensor.ev_endurance.name", "EV-rekkevidde")
    set_path(data, "entity.sensor.full_hour.name", "Timer til full")
    set_path(data, "entity.sensor.full_minute.name", "Minutter til full")
    set_path(data, "entity.sensor.charge_remaining_hours.name", "Gjenstående ladetimer")
    set_path(data, "entity.sensor.charge_remaining_minutes.name", "Gjenstående lademinutter")
    set_path(data, "entity.sensor.total_power.name", "Total effekt")
    set_path(data, "entity.sensor.svs.name", "Service påkrevd snart")
    set_path(data, "entity.binary_sensor.sentry_status.name", "Vaktmodus")
    set_path(data, "entity.binary_sensor.left_front_door.name", "Venstre frontdør")
    set_path(data, "entity.binary_sensor.right_front_door.name", "Høyre frontdør")
    set_path(data, "entity.binary_sensor.left_front_window.name", "Venstre frontvindu")
    set_path(data, "entity.binary_sensor.right_front_window.name", "Høyre frontvindu")
    set_path(data, "entity.binary_sensor.left_front_door_lock.name", "Venstre frontdørlås")
    set_path(data, "entity.binary_sensor.right_front_door_lock.name", "Høyre frontdørlås")
    set_path(data, "entity.binary_sensor.left_rear_door_lock.name", "Venstre bakdørlås")
    set_path(data, "entity.binary_sensor.right_rear_door_lock.name", "Høyre bakdørlås")
    set_path(data, "entity.sensor.left_rear_tire_status.name", "Dekkstatus bak venstre")
    set_path(data, "entity.sensor.right_rear_tire_status.name", "Dekkstatus bak høyre")
    set_path(data, "entity.button.flash_lights.name", "Lyshorn")
    set_path(data, "entity.select.rear_left_seat_heat.name", "Venstre baksetevarme")


def fix_sv(data: dict) -> None:
    """Fix Swedish translations."""
    set_path(data, "options.step.init.title", "Uppdatera polling")
    set_path(data, "entity.sensor.temp_in_car.name", "Kupétemperatur")
    set_path(data, "entity.sensor.soc.name", "Lade-SOC")
    set_path(data, "entity.sensor.time_to_full.name", "Tid till full laddning")
    set_path(data, "entity.sensor.ev_endurance.name", "EV-räckvidd")
    set_path(data, "entity.sensor.full_hour.name", "Timmar till full")
    set_path(data, "entity.sensor.full_minute.name", "Minuter till full")
    set_path(data, "entity.sensor.charge_remaining_hours.name", "Återstående laddtimmar")
    set_path(data, "entity.sensor.charge_remaining_minutes.name", "Återstående laddminuter")
    set_path(data, "entity.sensor.total_power.name", "Total effekt")
    set_path(data, "entity.sensor.svs.name", "Service krävs snart")
    set_path(data, "entity.binary_sensor.sentry_status.name", "Vaktläge")
    set_path(data, "entity.button.flash_lights.name", "Ljustuta")


def fix_pl(data: dict) -> None:
    """Fix Polish translations."""
    set_path(data, "options.step.init.title", "Aktualizuj odpytywanie")
    set_path(data, "entity.sensor.endurance_mileage.name", "Zasięg")
    set_path(data, "entity.sensor.ev_endurance.name", "Zasięg EV")
    set_path(data, "entity.sensor.full_hour.name", "Godziny do pełnej")
    set_path(data, "entity.sensor.full_minute.name", "Minuty do pełnej")
    set_path(data, "entity.sensor.charge_remaining_hours.name", "Pozostałe godziny ładowania")
    set_path(data, "entity.sensor.charge_remaining_minutes.name", "Pozostałe minuty ładowania")
    set_path(data, "entity.sensor.svs.name", "Wymagany serwis")
    set_path(data, "entity.sensor.upgrade_status.name", "Stan aktualizacji OTA")
    set_path(data, "entity.sensor.abs_warning.name", "Ostrzeżenie ABS")
    set_path(data, "entity.sensor.charging_update_time.name", "Ostatnia aktualizacja ładowania")
    set_path(data, "entity.binary_sensor.charge_heat_state.name", "Ogrzewanie ładowania")
    set_path(data, "entity.button.flash_lights.name", "Sygnał świetlny")


def fix_hu(data: dict) -> None:
    """Fix Hungarian translations."""
    set_path(data, "config.step.user.title", "Csatlakozás a BYD-hez")
    set_path(data, "options.step.init.title", "Lekérdezés frissítése")
    set_path(data, "entity.sensor.power_gear.name", "Fokozatválasztó pozíció")
    set_path(data, "entity.sensor.ev_endurance.name", "EV hatótáv")
    set_path(data, "entity.sensor.full_hour.name", "Órák a telítődésig")
    set_path(data, "entity.sensor.full_minute.name", "Percek a telítődésig")
    set_path(data, "entity.sensor.charge_remaining_hours.name", "Hátralévő töltési órák")
    set_path(data, "entity.sensor.charge_remaining_minutes.name", "Hátralévő töltési percek")
    set_path(data, "entity.sensor.svs.name", "Szerviz szükséges hamarosan")
    set_path(data, "entity.sensor.charging_update_time.name", "Töltés utolsó frissítése")
    set_path(data, "entity.binary_sensor.trunk_lid.name", "Csomagtartó")
    set_path(data, "entity.button.flash_lights.name", "Fényjel")
    set_path(data, "entity.button.find_car.name", "Autó keresése")


def fix_nl(data: dict) -> None:
    """Fix Dutch translations."""
    set_path(data, "entity.climate.climate.state_attributes.preset_mode.state.max_cool", "Maximale koeling")
    set_path(data, "entity.button.close_windows.name", "Sluit ramen")
    set_path(data, "entity.binary_sensor.right_front_window.name", "Raam rechtsvoor")


def fix_tr(data: dict) -> None:
    """Fix Turkish translations."""
    set_path(data, "options.step.init.title", "Yoklamayı güncelle")
    set_path(data, "entity.sensor.ev_endurance.name", "EV menzili")
    set_path(data, "entity.sensor.full_hour.name", "Doluluk saatleri")
    set_path(data, "entity.sensor.full_minute.name", "Doluluk dakikaları")
    set_path(data, "entity.sensor.charge_remaining_hours.name", "Kalan şarj saatleri")
    set_path(data, "entity.sensor.charge_remaining_minutes.name", "Kalan şarj dakikaları")
    set_path(data, "entity.sensor.svs.name", "Servis gerekli")
    set_path(data, "entity.sensor.charging_update_time.name", "Şarj son güncelleme")
    set_path(data, "entity.button.flash_lights.name", "Far yakma")


def fix_ja(data: dict) -> None:
    """Fix Japanese translations."""
    set_path(data, "options.step.init.title", "ポーリング設定")
    set_path(data, "entity.sensor.temp_in_car.name", "車内温度")
    set_path(data, "entity.sensor.soc.name", "充電 SOC")
    set_path(data, "entity.sensor.ev_endurance.name", "EV 航続距離")
    set_path(data, "entity.sensor.full_hour.name", "満充電までの時間")
    set_path(data, "entity.sensor.full_minute.name", "満充電までの分数")
    set_path(data, "entity.sensor.charge_remaining_hours.name", "残り充電時間")
    set_path(data, "entity.sensor.charge_remaining_minutes.name", "残り充電分数")
    set_path(data, "entity.sensor.svs.name", "要点検")
    set_path(data, "entity.sensor.esp.name", "横滑り防止装置")
    set_path(data, "entity.sensor.charging_update_time.name", "充電の最終更新")
    set_path(data, "entity.binary_sensor.charge_heat_state.name", "充電ヒーティング")
    set_path(data, "entity.button.flash_lights.name", "ライトフラッシュ")
    set_path(data, "entity.button.close_windows.name", "窓を閉じる")
    set_path(data, "entity.switch.car_on.name", "車両オン")
    set_path(data, "entity.climate.climate.state_attributes.preset_mode.state.max_heat", "最大暖房")
    set_path(data, "entity.climate.climate.state_attributes.preset_mode.state.max_cool", "最大冷房")


def fix_ko(data: dict) -> None:
    """Fix Korean translations."""
    set_path(data, "entity.sensor.temp_in_car.name", "실내 온도")
    set_path(data, "entity.sensor.ev_endurance.name", "EV 주행거리")
    set_path(data, "entity.sensor.charge_remaining_hours.name", "충전 남은 시간")
    set_path(data, "entity.sensor.svs.name", "점검 필요")
    set_path(data, "entity.sensor.charging_update_time.name", "충전 마지막 업데이트")
    set_path(data, "entity.binary_sensor.is_any_window_open.name", "창문")
    set_path(data, "entity.binary_sensor.charge_heat_state.name", "충전 히팅")
    set_path(data, "entity.switch.battery_heat.name", "배터리 히팅")
    set_path(data, "entity.climate.climate.state_attributes.preset_mode.state.max_heat", "최대 난방")
    set_path(data, "entity.climate.climate.state_attributes.preset_mode.state.max_cool", "최대 냉방")
    set_path(data, "entity.lock.lock.name", "잠금")


def fix_zh_hans(data: dict) -> None:
    """Fix Simplified Chinese translations."""
    set_path(data, "entity.binary_sensor.is_charging.name", "充电中")
    set_path(data, "entity.sensor.full_hour.name", "充满小时数")
    set_path(data, "entity.sensor.full_minute.name", "充满分钟数")
    set_path(data, "entity.sensor.charge_remaining_hours.name", "充电剩余小时")
    set_path(data, "entity.sensor.charge_remaining_minutes.name", "充电剩余分钟")
    set_path(data, "entity.sensor.svs.name", "请尽快保养")
    set_path(data, "entity.switch.battery_heat.name", "电池加热")
    set_path(data, "entity.switch.car_on.name", "车辆启动")


def fix_th(data: dict) -> None:
    """Fix Thai translations."""
    set_path(data, "options.step.init.title", "อัปเดตการโพล")
    set_path(data, "config.step.user.data.smart_gps_polling", "โพลลิ่ง GPS อัจฉริยะ")
    set_path(data, "options.step.init.data.smart_gps_polling", "โพลลิ่ง GPS อัจฉริยะ")
    set_path(data, "entity.sensor.ev_endurance.name", "ระยะทาง EV")
    set_path(data, "entity.sensor.full_hour.name", "ชั่วโมงจนเต็ม")
    set_path(data, "entity.sensor.full_minute.name", "นาทีจนเต็ม")
    set_path(data, "entity.sensor.charge_remaining_hours.name", "ชั่วโมงชาร์จที่เหลือ")
    set_path(data, "entity.sensor.charge_remaining_minutes.name", "นาทีชาร์จที่เหลือ")
    set_path(data, "entity.sensor.booking_charging_minute.name", "นาทีชาร์จตามกำหนดเวลา")
    set_path(data, "entity.sensor.tirepressure_system.name", "สถานะ TPMS")
    set_path(data, "entity.sensor.abs_warning.name", "คำเตือน ABS")
    set_path(data, "entity.sensor.upgrade_status.name", "สถานะอัปเกรด OTA")
    set_path(data, "entity.sensor.svs.name", "ต้องเข้ารับบริการเร็วๆ นี้")
    set_path(data, "entity.sensor.charging_update_time.name", "การอัปเดตการชาร์จครั้งล่าสุด")
    set_path(data, "entity.binary_sensor.vehicle_state.name", "รถเปิดอยู่")
    set_path(data, "entity.switch.car_on.name", "รถเปิดอยู่")
    set_path(data, "entity.climate.climate.state_attributes.preset_mode.state.max_cool", "ทำความเย็นสูงสุด")


def fix_id(data: dict) -> None:
    """Fix Indonesian translations."""
    set_path(data, "options.step.init.title", "Perbarui polling")
    set_path(data, "config.step.user.data.username", "Nama pengguna")
    set_path(data, "config.step.user.data.poll_interval", "Interval polling (detik)")
    set_path(data, "config.step.user.data.gps_poll_interval", "GPS interval polling (detik)")
    set_path(data, "config.step.user.data.smart_gps_polling", "Polling GPS cerdas")
    set_path(data, "config.error.invalid_control_pin", "PIN kontrol tidak valid atau kontrol cloud dikunci sementara")
    set_path(data, "options.step.init.data.poll_interval", "Interval polling (detik)")
    set_path(data, "options.step.init.data.gps_poll_interval", "GPS interval polling (detik)")
    set_path(data, "options.step.init.data.smart_gps_polling", "Polling GPS cerdas")
    set_path(data, "entity.sensor.ev_endurance.name", "Jangkauan EV")
    set_path(data, "entity.sensor.full_hour.name", "Jam hingga penuh")
    set_path(data, "entity.sensor.full_minute.name", "Menit hingga penuh")
    set_path(data, "entity.sensor.charge_remaining_hours.name", "Sisa jam pengisian")
    set_path(data, "entity.sensor.charge_remaining_minutes.name", "Sisa menit pengisian")
    set_path(data, "entity.sensor.tirepressure_system.name", "Status TPMS")
    set_path(data, "entity.sensor.abs_warning.name", "Peringatan ABS")
    set_path(data, "entity.sensor.upgrade_status.name", "Status peningkatan OTA")
    set_path(data, "entity.sensor.svs.name", "Servis diperlukan segera")
    set_path(data, "entity.sensor.total_power.name", "Daya total")
    set_path(data, "entity.sensor.pwr.name", "Peringatan daya")
    set_path(data, "entity.sensor.charging_update_time.name", "Pembaruan pengisian terakhir")
    set_path(data, "entity.binary_sensor.is_any_window_open.name", "Jendela")
    set_path(data, "entity.binary_sensor.skylight.name", "Atap kaca")
    set_path(data, "entity.binary_sensor.charge_heat_state.name", "Pemanasan pengisian")
    set_path(data, "entity.switch.battery_heat.name", "Pemanasan baterai")


def fix_ms(data: dict) -> None:
    """Fix Malay translations."""
    set_path(data, "options.step.init.title", "Kemas kini polling")
    set_path(data, "config.step.user.data.poll_interval", "Selang polling (saat)")
    set_path(data, "config.step.user.data.gps_poll_interval", "GPS selang polling (saat)")
    set_path(data, "config.step.user.data.smart_gps_polling", "Polling GPS pintar")
    set_path(data, "config.error.invalid_control_pin", "PIN kawalan tidak sah atau kawalan awan dikunci buat sementara waktu")
    set_path(data, "options.step.init.data.poll_interval", "Selang polling (saat)")
    set_path(data, "options.step.init.data.gps_poll_interval", "GPS selang polling (saat)")
    set_path(data, "options.step.init.data.smart_gps_polling", "Polling GPS pintar")
    set_path(data, "entity.sensor.ev_endurance.name", "Jarak EV")
    set_path(data, "entity.sensor.full_hour.name", "Jam sehingga penuh")
    set_path(data, "entity.sensor.charge_remaining_hours.name", "Baki jam pengecasan")
    set_path(data, "entity.sensor.charge_remaining_minutes.name", "Baki minit pengecasan")
    set_path(data, "entity.sensor.tirepressure_system.name", "Status TPMS")
    set_path(data, "entity.sensor.abs_warning.name", "Amaran ABS")
    set_path(data, "entity.sensor.upgrade_status.name", "Status naik taraf OTA")
    set_path(data, "entity.sensor.charging_update_time.name", "Kemas kini pengecasan terakhir")
    set_path(data, "entity.binary_sensor.is_any_door_open.name", "Pintu")
    set_path(data, "entity.switch.battery_heat.name", "Pemanasan bateri")
    set_path(data, "entity.climate.climate.name", "Iklim")


def fix_uz(data: dict) -> None:
    """Fix Uzbek translations."""
    set_path(data, "options.step.init.title", "So'rovni yangilash")
    set_path(data, "config.step.user.data.poll_interval", "So'rov oralig'i (sekundlar)")
    set_path(data, "config.step.user.data.gps_poll_interval", "GPS so'rov oralig'i (sekundlar)")
    set_path(data, "options.step.init.data.poll_interval", "So'rov oralig'i (sekundlar)")
    set_path(data, "options.step.init.data.gps_poll_interval", "GPS so'rov oralig'i (sekundlar)")
    set_path(data, "entity.sensor.temp_in_car.name", "Salon harorati")
    set_path(data, "entity.sensor.ev_endurance.name", "EV masofasi")
    set_path(data, "entity.sensor.full_hour.name", "To'lgunlikkacha soatlar")
    set_path(data, "entity.sensor.full_minute.name", "To'lgunlikkacha daqiqalar")
    set_path(data, "entity.sensor.charge_remaining_hours.name", "Qolgan zaryadlash soatlari")
    set_path(data, "entity.sensor.charge_remaining_minutes.name", "Qolgan zaryadlash daqiqalari")
    set_path(data, "entity.sensor.svs.name", "Xizmat talab qilinadi")
    set_path(data, "entity.sensor.charging_update_time.name", "Zaryadlash oxirgi yangilanishi")
    set_path(data, "entity.binary_sensor.sliding_door.name", "Sirpanma eshik")
    set_path(data, "entity.binary_sensor.sliding_door_lock.name", "Sirpanma eshik qulfi")
    set_path(data, "entity.button.find_car.name", "Avtomobilni toping")


FIXERS = {
    "de": fix_de,
    "es": fix_es,
    "fr": fix_fr,
    "pt": fix_pt,
    "da": fix_da,
    "no": fix_no,
    "sv": fix_sv,
    "pl": fix_pl,
    "hu": fix_hu,
    "nl": fix_nl,
    "tr": fix_tr,
    "ja": fix_ja,
    "ko": fix_ko,
    "zh-Hans": fix_zh_hans,
    "th": fix_th,
    "id": fix_id,
    "ms": fix_ms,
    "uz": fix_uz,
}


def main():
    total_fixes = 0
    for locale, fixer in FIXERS.items():
        path = TRANS / f"{locale}.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        # Count changes by comparing before/after
        before = json.dumps(data, ensure_ascii=False)
        fixer(data)
        after = json.dumps(data, ensure_ascii=False)

        if before != after:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            # rough count
            fixes = sum(1 for a, b in zip(before.split('"'), after.split('"')) if a != b)
            total_fixes += fixes
            print(f"  {locale}.json: updated")
        else:
            print(f"  {locale}.json: no changes needed")

    print(f"\nDone. Updated {len(FIXERS)} locale files.")


if __name__ == "__main__":
    main()
