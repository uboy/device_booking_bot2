from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any, Dict, List

# Базовая директория для файлов данных (можно переопределить через переменную окружения)
DATA_DIR = os.getenv("DATA_DIR", ".")

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
DEVICES_FILE = os.path.join(DATA_DIR, "devices.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
LOGS_FILE = os.path.join(DATA_DIR, "device_logs.json")
GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")

config: Dict[str, Any] = {}
devices: List[Dict[str, Any]] = []
users: List[Dict[str, Any]] = []
logs: Dict[str, List[Dict[str, Any]]] = {}
groups: List[Dict[str, Any]] = []

_write_lock = threading.RLock()


def _ensure_data_dir() -> None:
    """Создает директорию для данных, если ее еще нет."""
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_json(path: str, default: Any):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        # Возвращаем default, если файл поврежден
        return default


def _atomic_write_json(path: str, data: Any) -> None:
    """Пишем данные атомарно, чтобы избежать частично записанных файлов."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with _write_lock:
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path) or ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


def _save_json(path: str, data: Any) -> None:
    _atomic_write_json(path, data)


def load_all() -> None:
    """Загружаем config, devices, users, logs, groups и проставляем дефолты."""
    global config, devices, users, logs, groups

    _ensure_data_dir()

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

    groups_data = _load_json(GROUPS_FILE, [])
    if not isinstance(groups_data, list):
        groups_data = []
    groups.clear()
    groups.extend(groups_data)


def save_config() -> None:
    _save_json(CONFIG_FILE, config)


def save_devices() -> None:
    _save_json(DEVICES_FILE, devices)


def save_users() -> None:
    _save_json(USERS_FILE, users)


def save_logs() -> None:
    _save_json(LOGS_FILE, logs)


def save_groups() -> None:
    _save_json(GROUPS_FILE, groups)
