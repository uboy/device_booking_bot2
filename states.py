from __future__ import annotations

from enum import Enum, auto


class BotState(Enum):
    NONE = auto()
    ADDING_DEVICE = auto()
    ADDING_DEVICE_NAME = auto()
    ADDING_DEVICE_SN = auto()
    ADDING_DEVICE_TYPE = auto()
    ADDING_USER = auto()
    ADDING_USER_ID = auto()
    EDITING_USER = auto()
    WAITING_TRANSFER_CONFIRMATION = auto()  # Ожидание подтверждения передачи устройства
    VIEWING_DEVICE_MODELS = auto()  # Просмотр моделей выбранного типа
