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


def get_group_by_id(group_id: int) -> Optional[Dict[str, Any]]:
    """Получить группу по ID."""
    return next((g for g in storage.groups if g.get("id") == group_id), None)


def get_group_by_name(group_name: str) -> Optional[Dict[str, Any]]:
    """Получить группу по имени."""
    return next((g for g in storage.groups if g.get("name") == group_name), None)


def get_user_group(user_id: int) -> Optional[Dict[str, Any]]:
    """Получить группу пользователя."""
    user = get_user_by_id(user_id)
    if not user:
        return None
    group_id = user.get("group_id")
    if not group_id:
        return None
    return get_group_by_id(group_id)


def get_device_group(device_id: int) -> Optional[Dict[str, Any]]:
    """Получить группу устройства."""
    device = next((d for d in storage.devices if d.get("id") == device_id), None)
    if not device:
        return None
    group_id = device.get("group_id")
    if not group_id:
        return None
    return get_group_by_id(group_id)


def can_user_book_device(user_id: int, device_id: int) -> bool:
    """Проверить, может ли пользователь забронировать устройство.
    
    Администраторы могут бронировать любые устройства.
    Обычные пользователи могут бронировать только устройства из своей группы.
    Если пользователь или устройство не в группе - бронирование невозможно.
    """
    # Администраторы могут бронировать любые устройства
    if is_admin(user_id):
        return True
    
    user_group = get_user_group(user_id)
    device_group = get_device_group(device_id)
    
    # Если пользователь или устройство не в группе - нельзя бронировать
    if not user_group or not device_group:
        return False
    
    # Пользователь может бронировать только устройства из своей группы
    return user_group.get("id") == device_group.get("id")


def filter_devices_by_user_group(user_id: int, devices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Отфильтровать устройства по группе пользователя.
    
    Администраторы видят все устройства.
    Обычные пользователи видят только устройства из своей группы.
    """
    # Администраторы видят все устройства
    if is_admin(user_id):
        return devices
    
    user_group = get_user_group(user_id)
    
    # Если пользователь не в группе - не видит устройств
    if not user_group:
        return []
    
    # Фильтруем устройства по группе
    user_group_id = user_group.get("id")
    return [d for d in devices if d.get("group_id") == user_group_id]


def get_default_group() -> Optional[Dict[str, Any]]:
    """Возвращает группу по умолчанию (первая по возрастанию ID)."""
    if not storage.groups:
        return None
    return sorted(storage.groups, key=lambda g: g.get("id", 0))[0]


def get_default_group_id() -> Optional[int]:
    """ID группы по умолчанию."""
    group = get_default_group()
    return group.get("id") if group else None


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
