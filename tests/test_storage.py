import importlib
from pathlib import Path

import pytest


def reload_storage(tmp_path: Path):
    """Reload storage module with isolated DATA_DIR."""
    import os
    import storage

    os.environ["DATA_DIR"] = str(tmp_path)
    importlib.reload(storage)
    return storage


def test_storage_roundtrip(tmp_path: Path):
    storage = reload_storage(tmp_path)

    storage.devices.clear()
    storage.devices.append({"id": 1, "sn": "SN1"})
    storage.save_devices()

    # Перезагружаем и убеждаемся, что данные на месте
    storage.devices.clear()
    storage.load_all()
    assert storage.devices == [{"id": 1, "sn": "SN1"}]


def test_atomic_write_creates_dir(tmp_path: Path):
    storage_dir = tmp_path / "nested"
    storage = reload_storage(storage_dir)

    storage.logs.clear()
    storage.logs["device1"] = [{"action": "test"}]
    storage.save_logs()

    assert (storage_dir / "device_logs.json").exists()
