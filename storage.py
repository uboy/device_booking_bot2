from __future__ import annotations

import json
import os
from typing import Any, Dict, List

CONFIG_FILE = "config.json"
DEVICES_FILE = "devices.json"
USERS_FILE = "users.json"
LOGS_FILE = "device_logs.json"

config: Dict[str, Any] = {}
devices: List[Dict[str, Any]] = []
users: List[Dict[str, Any]] = []
logs: Dict[str, List[Dict[str, Any]]] = {}


def _load_json(path: str, default: Any):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_all() -> None:
    """Загружаем config, devices, users, logs и проставляем дефолты."""
    global config, devices, users, logs

    config = _load_json(CONFIG_FILE, {})
    config.setdefault("bot_token", "PUT_YOUR_TOKEN_HERE")
    config.setdefault("admin_ids", [])
    config.setdefault("device_types", ["Phone", "Tablet", "PC", "RKBoard"])
    config.setdefault("registration_enabled", False)
    config.setdefault("default_booking_period_days", 1)
    config.setdefault("max_devices_per_user", 2)
    config.setdefault("notify_before_minutes", 60)
    config.setdefault("webapp_url", "")

    devices_data = _load_json(DEVICES_FILE, [])
    if not isinstance(devices_data, list):
        devices_data = []
    devices.clear()
    devices.extend(devices_data)

    users_data = _load_json(USERS_FILE, [])
    if not isinstance(users_data, list):
        users_data = []
    users.clear()
    users.extend(users_data)

    logs_data = _load_json(LOGS_FILE, {})
    if not isinstance(logs_data, dict):
        logs_data = {}
    logs.clear()
    logs.update(logs_data)


def save_config() -> None:
    _save_json(CONFIG_FILE, config)


def save_devices() -> None:
    _save_json(DEVICES_FILE, devices)


def save_users() -> None:
    _save_json(USERS_FILE, users)


def save_logs() -> None:
    _save_json(LOGS_FILE, logs)
