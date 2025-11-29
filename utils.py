from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from prettytable import PrettyTable

import storage


def format_datetime(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "Не указано"
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        return iso_str
    return dt.strftime("%d.%m.%Y %H:%M")


def log_action(device_sn: str, action: str) -> None:
    if device_sn not in storage.logs:
        storage.logs[device_sn] = []
    storage.logs[device_sn].append(
        {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
        }
    )
    storage.save_logs()


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    return next((u for u in storage.users if u.get("user_id") == user_id), None)


def get_user_role(user_id: int) -> Optional[str]:
    user = get_user_by_id(user_id)
    if not user:
        return None
    status = user.get("status")
    if status not in ("active", "approved"):
        return None
    return user.get("role")


def is_admin(user_id: int) -> bool:
    return (
        get_user_role(user_id) == "Admin"
        or user_id in storage.config.get("admin_ids", [])
    )


def get_user_full_name(user_id: int) -> str:
    user = get_user_by_id(user_id)
    if not user:
        return "Неизвестно"
    return f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or "Неизвестно"


def get_user_devices(user_id: int) -> List[Dict[str, Any]]:
    return [d for d in storage.devices if d.get("user_id") == user_id]


def cleanup_expired_bookings() -> None:
    """Освобождает устройства с истёкшим сроком брони."""
    now = datetime.now()
    changed = False
    for d in storage.devices:
        exp = d.get("booking_expiration")
        if not exp:
            continue
        try:
            dt = datetime.fromisoformat(exp)
        except ValueError:
            continue
        if dt < now and d.get("status") == "booked":
            d["status"] = "free"
            d.pop("user_id", None)
            d.pop("booking_expiration", None)
            log_action(d["sn"], "Бронирование автоматически завершено (истёк срок)")
            changed = True
    if changed:
        storage.save_devices()


def devices_table(devices: List[Dict[str, Any]], mobile_format: bool = False) -> str:
    """Возвращает строку с таблицей устройств.
    
    Args:
        devices: Список устройств
        mobile_format: Если True, использует упрощенный формат для мобильных устройств
    """
    if mobile_format:
        # Упрощенный формат для мобильных устройств
        lines = []
        for d in devices:
            status_emoji = "✅" if d.get("status") == "free" else "🔒"
            status_text = "Свободно" if d.get("status") == "free" else "Забронировано"
            
            device_info = (
                f"{status_emoji} **{d.get('name')}**\n"
                f"🆔 ID: {d.get('id')} | 📦 {d.get('type')} | 🔢 SN: `{d.get('sn')}`\n"
                f"📊 Статус: {status_text}"
            )
            
            if d.get("status") == "booked":
                expiration = format_datetime(d.get("booking_expiration"))
                user_name = get_user_full_name(d.get("user_id"))
                device_info += f"\n📅 До: {expiration} | 👤 {user_name}"
            
            lines.append(device_info)
        
        return "\n\n".join(lines)
    else:
        # Формат PrettyTable для ПК
        table = PrettyTable()
        table.field_names = ["ID", "Название", "SN", "Тип", "Статус", "До", "Пользователь"]
        for d in devices:
            table.add_row(
                [
                    d.get("id"),
                    d.get("name"),
                    d.get("sn"),
                    d.get("type"),
                    "Свободно" if d.get("status") == "free" else "Забронировано",
                    format_datetime(d.get("booking_expiration")),
                    get_user_full_name(d.get("user_id")) if d.get("status") == "booked" else "-",
                ]
            )
        return str(table)
