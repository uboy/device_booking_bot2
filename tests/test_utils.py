import importlib
from datetime import datetime, timedelta
from pathlib import Path

import storage
import utils


def reload_modules(tmp_path: Path):
    import os

    os.environ["DATA_DIR"] = str(tmp_path)
    importlib.reload(storage)
    importlib.reload(utils)


def test_cleanup_expired_bookings(tmp_path: Path):
    reload_modules(tmp_path)

    now = datetime.now()
    expired = now - timedelta(hours=1)
    active = now + timedelta(hours=1)

    storage.devices.clear()
    storage.devices.extend(
        [
            {"id": 1, "sn": "A1", "status": "booked", "booking_expiration": expired.isoformat(), "user_id": 1},
            {"id": 2, "sn": "A2", "status": "booked", "booking_expiration": active.isoformat(), "user_id": 2},
        ]
    )

    utils.cleanup_expired_bookings()

    device1, device2 = storage.devices
    assert device1["status"] == "free"
    assert "user_id" not in device1
    assert device2["status"] == "booked"
    assert device2["user_id"] == 2
