from __futuretable import PrettyTable  # pip install prettytable
from datetime import datetime, timedelta
import re
import csv
import json
import os
from typing import Any, Optional, List, Dict
import io

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ==============================
#   Глобальные данные
# ==============================

CONFIG_FILE = "config.json"
DEVICES_FILE = "devices.json"
USERS_FILE = "users.json"
LOGS_FILE = "device_logs.json"

config: Dict[str, Any] = {}
devices: List[Dict[str, Any]] = []
users: List[Dict[str, Any]] = []
logs: Dict[str, List[Dict[str, Any]]] = {}

# Флаг регистрации (загружается/сохраняется через config.json)
registration_enabled: bool = False


# ==============================
#   Работа с файлами
# ==============================

def load_json(filename: str, default: Any) -> Any:
    if not os.path.exists(filename):
        return default
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(filename: str, data: Any) -> None:
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_all_data() -> None:
    global config, devices, users, logs, registration_enabled

    config = load_json(CONFIG_FILE, {})
    # дефолты для конфига
    config.setdefault("bot_token", "YOUR_TELEGRAM_BOT_TOKEN_HERE")
    config.setdefault("admin_ids", [])
    config.setdefault("device_types", ["Tablet", "Phone", "PC", "RKBoard"])
    config.setdefault("registration_enabled", False)

    registration_enabled = bool(config.get("registration_enabled", False))

    # устройства — список словарей (как в devices.json_template)
    devices_list = load_json(DEVICES_FILE, [])
    # гарантируем, что это список
    devices[:] = devices_list if isinstance(devices_list, list) else []

    # пользователи — список словарей
    users_list = load_json(USERS_FILE, [])
    users[:] = users_list if isinstance(users_list, list) else []

    logs_dict = load_json(LOGS_FILE, {})
    logs.clear()
    logs.update(logs_dict if isinstance(logs_dict, dict) else {})


def save_config() -> None:
    config["registration_enabled"] = registration_enabled
    save_json(CONFIG_FILE, config)


def save_devices() -> None:
    save_json(DEVICES_FILE, devices)


def save_users() -> None:
    save_json(USERS_FILE, users)


def save_logs() -> None:
    save_json(LOGS_FILE, logs)


# ==============================
#   Утилиты
# ==============================

def format_datetime(iso_datetime: Optional[str]) -> str:
    if not iso_datetime:
        return "Не указано"
    try:
        dt = datetime.fromisoformat(iso_datetime)
    except ValueError:
        return iso_datetime
    return dt.strftime("%d.%m.%Y %H:%M")


def log_action(device_sn: str, action: str) -> None:
    if device_sn not in logs:
        logs[device_sn] = []
    logs[device_sn].append(
        {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "action": action}
    )
    save_logs()


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    return next((u for u in users if u.get("user_id") == user_id), None)


def get_user_role(user_id: int) -> Optional[str]:
    user = get_user_by_id(user_id)
    if user and user.get("status") == "active":
        return user.get("role")
    return None


def get_user_full_name(user_id: int) -> str:
    user = get_user_by_id(user_id)
    if not user:
        return "Неизвестно"
    return f"{user.get('first_name', 'Неизвестно')} {user.get('last_name', 'Неизвестно')}".strip()


def is_admin(user_id: int) -> bool:
    # Админ, если:
    # - в users с ролью Admin и статусом active, или
    # - в списке admin_ids из config
    return (
        get_user_role(user_id) == "Admin"
        or user_id in config.get("admin_ids", [])
    )


def get_main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    keyboard = [["Список устройств", "Бронирование"], ["Мои устройства"]]
    if is_admin(user_id):
        keyboard.append(["Администрирование"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_user_devices_list(user_id: int) -> List[Dict[str, Any]]:
    return [d for d in devices if d.get("user_id") == user_id]


def cleanup_expired_bookings() -> None:
    """Автоматически освобождает устройства с истёкшим сроком брони."""
    now = datetime.now()
    changed = False
    for d in devices:
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
        save_devices()


# ==============================
#   Декоратор доступа
# ==============================

def access_control(required_status: str = "active", required_role: Optional[str] = None):
    """
    Проверяет:
      - зарегистрирован ли пользователь,
      - имеет ли нужный статус,
      - имеет ли нужную роль (если указано).
    Работает и для сообщений, и для callback_query.
    """

    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user = update.effective_user
            user_id = user.id if user else None

            is_callback = update.callback_query is not None
            msg_obj = update.callback_query.message if is_callback else update.message

            if user_id is None or msg_obj is None:
                return

            db_user = get_user_by_id(user_id)

            if not db_user:
                await msg_obj.reply_text(
                    "Вы не зарегистрированы. Используйте /register для отправки заявки.",
                    reply_markup=ReplyKeyboardMarkup([["/help"]], resize_keyboard=True),
                )
                return

            if db_user.get("status") != required_status:
                await msg_obj.reply_text(
                    f"Ваш статус: {db_user.get('status')}. "
                    f"Доступ разрешён только для пользователей со статусом: {required_status}.",
                    reply_markup=ReplyKeyboardMarkup([["/help"]], resize_keyboard=True),
                )
                return

            if required_role and db_user.get("role") != required_role and not (
                required_role == "Admin" and is_admin(user_id)
            ):
                await msg_obj.reply_text(
                    f"Доступ к этой функции разрешён только для пользователей с ролью: {required_role}.",
                    reply_markup=ReplyKeyboardMarkup([["/help"]], resize_keyboard=True),
                )
                return

            return await func(update, context, *args, **kwargs)

        return wrapper

    return decorator


# ==============================
#   Команды / help / меню
# ==============================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/start - Главное меню\n"
        "/help - Справка\n"
        "/register - Отправить заявку на регистрацию\n"
        "\nДоступные функции зависят от вашей роли."
    )


@access_control()
async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        "Главное меню:", reply_markup=get_main_menu_keyboard(user_id)
    )


@access_control()
async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Просто возвращаем главное меню
    user_id = update.effective_user.id
    await update.message.reply_text(
        "Главное меню:", reply_markup=get_main_menu_keyboard(user_id)
    )


# ==============================
#   Регистрация
# ==============================

async def register_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global registration_enabled

    if not registration_enabled:
        await update.message.reply_text("Регистрация временно отключена.")
        return

    tg_user = update.effective_user
    user_id = tg_user.id

    for u in users:
        if u.get("user_id") == user_id:
            await update.message.reply_text(
                "Вы уже зарегистрированы или ваша заявка ожидает рассмотрения."
            )
            return

    new_user = {
        "user_id": user_id,
        "username": tg_user.username or "Не указано",
        "first_name": tg_user.first_name or "Не указано",
        "last_name": tg_user.last_name or "Не указано",
        "role": "User",
        "status": "pending",
    }
    users.append(new_user)
    save_users()

    await update.message.reply_text(
        "Ваша заявка на регистрацию отправлена. Ожидайте подтверждения администратора."
    )


@access_control(required_role="Admin")
async def toggle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global registration_enabled
    registration_enabled = not registration_enabled
    save_config()
    status = "включена" if registration_enabled else "выключена"
    await update.message.reply_text(f"Регистрация {status}.")


# ==============================
#   Устройства — список / просмотр
# ==============================

@access_control()
async def list_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_expired_bookings()

    if not devices:
        await update.message.reply_text("Нет устройств для отображения.")
        return

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for d in devices:
        grouped.setdefault(d.get("type", "Не указан"), []).append(d)

    response = "Список устройств:\n"
    for dev_type, group in sorted(grouped.items()):
        table = PrettyTable()
        table.field_names = [
            "Название",
            "SN",
            "Статус",
            "Дата окончания брони",
            "Пользователь",
        ]
        for d in group:
            status = "Свободно" if d.get("status") == "free" else "Забронировано"
            user_name = (
                get_user_full_name(d.get("user_id"))
                if d.get("status") == "booked"
                else "-"
            )
            booking_exp = format_datetime(d.get("booking_expiration"))
            table.add_row([d.get("name"), d.get("sn"), status, booking_exp, user_name])

        response += f"\n{dev_type}:\n```\n{table}\n```\n"

    await update.message.reply_text(response, parse_mode="Markdown")


# ==============================
#   Бронирование устройств
# ==============================

@access_control()
async def book_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_expired_bookings()
    # доступные типы только среди свободных устройств
    available_types = sorted(
        {d["type"] for d in devices if d.get("status") == "free"}
    )

    if not available_types:
        await update.message.reply_text("Нет доступных устройств для бронирования.")
        return

    keyboard = [[t] for t in available_types]
    keyboard.append(["Назад"])
    await update.message.reply_text(
        "Выберите тип устройства для бронирования:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


@access_control()
async def select_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_expired_bookings()
    device_type = update.message.text.strip()
    # фильтруем свободные устройства этого типа
    available = [
        d for d in devices if d.get("type") == device_type and d.get("status") == "free"
    ]

    if not available:
        await update.message.reply_text(
            f"Нет доступных устройств типа {device_type}.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True),
        )
        return

    keyboard = [
        [f"{d['name']} ({d['type']}) - ID {d['id']}"] for d in available
    ]
    keyboard.append(["Назад"])
    await update.message.reply_text(
        "Выберите устройство для бронирования:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


@access_control()
async def book_specific_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_expired_bookings()
    device_text = update.message.text.strip()

    try:
        device_id = int(device_text.split(" - ID ")[-1])
    except (ValueError, IndexError):
        await update.message.reply_text(
            "Ошибка: некорректный формат данных устройства.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True),
        )
        return

    device = next(
        (d for d in devices if d.get("id") == device_id and d.get("status") == "free"),
        None,
    )
    if not device:
        await update.message.reply_text(
            "Ошибка: устройство не найдено или уже забронировано.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True),
        )
        return

    # Новая функциональность: период брони по умолчанию + можно задать в конфиге
    default_period = device.get(
        "default_booking_period", config.get("default_booking_period_days", 1)
    )
    expiration_date = datetime.now() + timedelta(days=default_period)

    device["status"] = "booked"
    device["user_id"] = update.effective_user.id
    device["booking_expiration"] = expiration_date.isoformat()
    save_devices()

    await update.message.reply_text(
        f"Устройство {device['name']} (SN: {device['sn']}) "
        f"забронировано до {expiration_date.strftime('%Y-%m-%d %H:%M:%S')}."
    )

    log_action(
        device["sn"],
        f"Устройство забронировано пользователем "
        f"{get_user_full_name(update.effective_user.id)} "
        f"до {expiration_date.strftime('%Y-%m-%d %H:%M:%S')}.",
    )


# ==============================
#   Мои устройства / освобождение
# ==============================

@access_control()
async def my_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_expired_bookings()
    user_id = update.effective_user.id
    user_devs = get_user_devices_list(user_id)

    if not user_devs:
        await update.message.reply_text("У вас нет забронированных устройств.")
        return

    table = PrettyTable()
    table.field_names = ["Название", "SN", "Дата окончания брони"]
    for d in user_devs:
        table.add_row(
            [d["name"], d["sn"], format_datetime(d.get("booking_expiration"))]
        )

    keyboard = [
        [f"Освободить {d['name']} (SN: {d['sn']})"] for d in user_devs
    ]
    keyboard.append(["Освободить все устройства"])
    keyboard.append(["Назад"])

    await update.message.reply_text(
        f"Ваши забронированные устройства:\n```\n{table}\n```",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


@access_control()
async def release_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_expired_bookings()
    user_id = update.effective_user.id
    user_role = get_user_role(user_id)

    is_callback = update.callback_query is not None
    src = update.callback_query if is_callback else update.message
    text = src.data if is_callback else src.text.strip()

    menu_context = context.user_data.get("menu_context", "user_devices")
    if is_callback and context.user_data.get("menu_context") != "admin_panel":
        menu_context = "admin_panel" if user_role == "Admin" else "user_devices"

    release_all = text in ("release_all_devices", "Освободить все устройства")

    if release_all:
        candidates = [
            d
            for d in devices
            if d.get("status") == "booked"
            and (
                (menu_context == "user_devices" and d.get("user_id") == user_id)
                or (menu_context == "admin_panel" and user_role == "Admin")
            )
        ]
    else:
        if is_callback:
            # callback_data вида "release_<id>"
            try:
                device_id = int(text.split("_", 1)[1])
            except (ValueError, IndexError):
                await src.edit_message_text("Ошибка: некорректный идентификатор устройства.")
                return
            candidates = [
                d
                for d in devices
                if d.get("id") == device_id
                and d.get("status") == "booked"
                and (
                    (menu_context == "user_devices" and d.get("user_id") == user_id)
                    or (menu_context == "admin_panel" and user_role == "Admin")
                )
            ]
        else:
            # текст: "Освободить NAME (SN: SN123)"
            match = re.match(r"Освободить (.+?) \(SN: (.+?)\)", text)
            if not match:
                await src.reply_text(
                    "Ошибка: некорректный формат команды.",
                    reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True),
                )
                return
            name, sn = match.groups()
            candidates = [
                d
                for d in devices
                if d.get("name") == name
                and d.get("sn") == sn
                and d.get("status") == "booked"
                and (
                    (menu_context == "user_devices" and d.get("user_id") == user_id)
                    or (menu_context == "admin_panel" and user_role == "Admin")
                )
            ]

    if not candidates:
        msg = "Нет устройств для освобождения."
    else:
        for d in candidates:
            d["status"] = "free"
            prev_user = d.pop("user_id", None)
            d.pop("booking_expiration", None)
            who = "администратором" if user_role == "Admin" else "пользователем"
            log_action(
                d["sn"],
                f"Освобождено {who} {get_user_full_name(user_id)} (ранее {prev_user})",
            )
        save_devices()
        msg = (
            "Все устройства успешно освобождены."
            if release_all
            else f"Устройство {candidates[0]['name']} (SN: {candidates[0]['sn']}) успешно освобождено."
        )

    if is_callback:
        await src.edit_message_text(msg)
        if menu_context == "admin_panel":
            await all_booked_devices(update, context)
    else:
        await src.reply_text(
            msg, reply_markup=get_main_menu_keyboard(user_id)
        )


# ==============================
#   Админ-панель / просмотр всех бронирований
# ==============================

@access_control(required_role="Admin")
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text(
            "У вас нет доступа к административному меню.",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        return

    keyboard = [
        ["Управление устройствами", "Управление пользователями"],
        ["Просмотр забронированных устройств", "Назад"],
    ]
    await update.message.reply_text(
        "Меню администрирования:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


@access_control(required_role="Admin")
async def all_booked_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_expired_bookings()

    is_callback = update.callback_query is not None
    src = update.callback_query if is_callback else update.message

    booked = [d for d in devices if d.get("status") == "booked"]

    if not booked:
        msg = "Нет забронированных устройств."
        if is_callback:
            await src.edit_message_text(msg)
        else:
            await src.reply_text(msg)
        return

    table = PrettyTable()
    table.field_names = ["Название", "SN", "Дата окончания брони", "Пользователь"]
    for d in booked:
        table.add_row(
            [
                d["name"],
                d["sn"],
                format_datetime(d.get("booking_expiration")),
                get_user_full_name(d.get("user_id")),
            ]
        )

    keyboard = [
        [
            InlineKeyboardButton(
                f"Освободить {d['name']} (SN: {d['sn']})",
                callback_data=f"release_{d['id']}",
            )
        ]
        for d in booked
    ]
    keyboard.append(
        [InlineKeyboardButton("Освободить все устройства", callback_data="release_all_devices")]
    )
    keyboard.append([InlineKeyboardButton("Назад", callback_data="admin_panel")])

    msg = f"Список забронированных устройств:\n```\n{table}\n```"

    context.user_data["menu_context"] = "admin_panel"
    if is_callback:
        await src.edit_message_text(
            msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await src.reply_text(
            msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
        )


# ==============================
#   Управление устройствами (админ)
# ==============================

@access_control(required_role="Admin")
async def manage_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text(
            "У вас нет доступа к управлению устройствами.",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        return

    keyboard = [
        [f"{d['name']} (SN: {d['sn']})", f"История {d['name']}"]
        for d in devices
    ]
    keyboard.append(["Добавить устройство", "Импортировать устройства"])
    keyboard.append(["Назад"])

    await update.message.reply_text(
        "Управление устройствами:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


@access_control(required_role="Admin")
async def manage_selected_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        name_part, sn_part = text.split("(SN:")
        name = name_part.strip()
        sn = sn_part.replace(")", "").strip()
    except ValueError:
        await update.message.reply_text(
            "Ошибка: некорректный формат данных устройства.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True),
        )
        return

    device = next((d for d in devices if d["name"] == name and d["sn"] == sn), None)
    if not device:
        await update.message.reply_text("Устройство не найдено.")
        return

    keyboard = [
        [f"Изменить имя устройства (ID: {device['id']})"],
        [f"Удалить устройство (ID: {device['id']})"],
        ["Назад"],
    ]
    await update.message.reply_text(
        f"Управление устройством:\nНазвание: {device['name']}\nSN: {device['sn']}\nТип: {device['type']}",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


@access_control(required_role="Admin")
async def edit_device_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        device_id = int(text.split("(ID:")[1].replace(")", "").strip())
    except (ValueError, IndexError):
        await update.message.reply_text("Ошибка: некорректный формат ID устройства.")
        return

    device = next((d for d in devices if d.get("id") == device_id), None)
    if not device:
        await update.message.reply_text("Устройство не найдено.")
        return

    context.user_data["editing_device_id"] = device_id
    await update.message.reply_text(
        "Введите новое имя устройства:",
        reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True),
    )


@access_control(required_role="Admin")
async def process_edit_device_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    device_id = context.user_data.get("editing_device_id")
    if not device_id:
        return

    new_name = update.message.text.strip()
    if new_name.lower() == "отмена":
        context.user_data.pop("editing_device_id", None)
        await update.message.reply_text("Операция отменена.")
        return

    device = next((d for d in devices if d.get("id") == device_id), None)
    if not device:
        await update.message.reply_text("Устройство не найдено.")
        context.user_data.pop("editing_device_id", None)
        return

    old_name = device["name"]
    device["name"] = new_name
    save_devices()
    await update.message.reply_text(f"Имя устройства изменено: {old_name} → {new_name}")
    context.user_data.pop("editing_device_id", None)


@access_control(required_role="Admin")
async def delete_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        device_id = int(text.split("(ID:")[1].replace(")", "").strip())
    except (ValueError, IndexError):
        await update.message.reply_text("Ошибка: некорректный формат ID устройства.")
        return

    device = next((d for d in devices if d.get("id") == device_id), None)
    if not device:
        await update.message.reply_text("Устройство не найдено.")
        return

    devices.remove(device)
    save_devices()
    await update.message.reply_text(
        f"Устройство {device['name']} (SN: {device['sn']}) успешно удалено.",
        reply_markup=get_main_menu_keyboard(update.effective_user.id),
    )


@access_control(required_role="Admin")
async def add_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Введите данные устройства в формате:\n"
        "SN, Name, Type\n\nПример:\nSN001, Device-1, Phone",
        reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True),
    )
    context.user_data["awaiting_device_data"] = True


@access_control(required_role="Admin")
async def process_new_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_device_data"):
        return

    line = update.message.text.strip()
    if line.lower() == "назад":
        context.user_data["awaiting_device_data"] = False
        await update.message.reply_text(
            "Отмена добавления устройства.",
            reply_markup=get_main_menu_keyboard(update.effective_user.id),
        )
        return

    try:
        sn, name, dev_type = map(str.strip, line.split(","))
    except ValueError:
        await update.message.reply_text(
            "Некорректный формат. Используйте: SN, Name, Type"
        )
        return

    new_id = max((d.get("id", 0) for d in devices), default=0) + 1
    devices.append(
        {
            "id": new_id,
            "name": name,
            "sn": sn,
            "type": dev_type,
            "status": "free",
        }
    )
    save_devices()
    context.user_data["awaiting_device_data"] = False
    await update.message.reply_text(f"Устройство {name} успешно добавлено.")


@access_control(required_role="Admin")
async def import_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Поддерживаем вызов только из текста ("Импортировать устройства")
    await update.message.reply_text(
        "Отправьте CSV файл с колонками: SN, Name, Type"
    )
    context.user_data["action"] = "import_devices"


@access_control(required_role="Admin")
async def process_import_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("action") != "import_devices":
        return

    file = update.message.document
    if not file:
        await update.message.reply_text("Ошибка: ожидается CSV файл.")
        return

    file_obj = await file.get_file()
    file_path = await file_obj.download_to_drive()

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required = {"SN", "Name", "Type"}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError(
                    "Неверный формат CSV. Нужны колонки: SN, Name, Type."
                )

            max_id = max((d.get("id", 0) for d in devices), default=0)
            counter = 0
            for row in reader:
                max_id += 1
                devices.append(
                    {
                        "id": max_id,
                        "name": row["Name"].strip(),
                        "sn": row["SN"].strip(),
                        "type": row["Type"].strip(),
                        "status": "free",
                    }
                )
                counter += 1

        save_devices()
        await update.message.reply_text(
            f"Устройства успешно импортированы. Добавлено: {counter}."
        )
    except FileNotFoundError:
        await update.message.reply_text("Ошибка: файл не найден.")
    except ValueError as e:
        await update.message.reply_text(f"Ошибка: {e}")
    finally:
        try:
            os.remove(file_path)
        except OSError:
            pass

    context.user_data["action"] = None


@access_control(required_role="Admin")
async def view_device_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace("История", "").strip()
    device = next((d for d in devices if d["name"] == text), None)
    if not device:
        await update.message.reply_text("Устройство не найдено.")
        return

    sn = device["sn"]
    history = logs.get(sn, [])
    if not history:
        await update.message.reply_text(
            f"История устройства {device['name']} (SN: {sn}) отсутствует.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True),
        )
        return

    history_text = "\n".join(
        f"{e['timestamp']}: {e['action']}" for e in history
    )
    await update.message.reply_text(
        f"История устройства {device['name']} (SN: {sn}):\n{history_text}",
        reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True),
    )


# ==============================
#   Управление пользователями (админ)
# ==============================

@access_control(required_role="Admin")
async def manage_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending = [u for u in users if u.get("status") == "pending"]

    keyboard = [
        [f"Утвердить {u['user_id']}", f"Удалить {u['user_id']}"] for u in pending
    ]

    reg_status = "Выключить регистрацию" if registration_enabled else "Включить регистрацию"
    keyboard.append([reg_status])
    keyboard.append(["Список всех пользователей", "Назад"])

    await update.message.reply_text(
        "Управление пользователями:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


@access_control(required_role="Admin")
async def view_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton(
                f"{u.get('first_name', '')} {u.get('last_name', '')} "
                f"{u['user_id']} ({u.get('status')})",
                callback_data=f"user_{u['user_id']}",
            )
        ]
        for u in users
    ]
    keyboard.append([InlineKeyboardButton("Назад", callback_data="admin_panel")])
    await update.message.reply_text(
        "Список пользователей:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


@access_control(required_role="Admin")
async def manage_selected_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    match = re.match(r"user_(\d+)", query.data or "")
    if not match:
        await query.message.reply_text("Ошибка: некорректные данные для пользователя.")
        return

    user_id = int(match.group(1))
    user = get_user_by_id(user_id)
    if not user:
        await query.message.reply_text("Пользователь не найден.")
        return

    keyboard = [
        [InlineKeyboardButton("Удалить пользователя", callback_data=f"delete_user_{user_id}")],
        [InlineKeyboardButton("Забронированные устройства", callback_data=f"user_devices_{user_id}")],
        [InlineKeyboardButton("Назад", callback_data="view_all_users")],
    ]
    await query.message.reply_text(
        f"Управление пользователем:\n"
        f"Имя: {user.get('first_name')}\n"
        f"Фамилия: {user.get('last_name')}\n"
        f"Статус: {user.get('status')}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@access_control(required_role="Admin")
async def process_edit_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get("action")
    if not action or not action.startswith("edit_user_"):
        return

    user_id = int(action.split("_")[-1])
    user = get_user_by_id(user_id)
    if not user:
        await update.message.reply_text("Пользователь не найден.")
        return

    try:
        first_name, last_name, username, role = map(
            str.strip, update.message.text.split(",")
        )
    except ValueError:
        await update.message.reply_text(
            "Некорректный формат. Используйте: Имя, Фамилия, Username, Роль"
        )
        return

    user.update(
        {
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "role": role,
        }
    )
    save_users()
    await update.message.reply_text(
        f"Данные пользователя {first_name} {last_name} успешно обновлены."
    )
    del context.user_data["action"]
    await view_all_users(update, context)


@access_control(required_role="Admin")
async def delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # поддержка и для callback, и для текстовой кнопки "Удалить <id>"
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        match = re.match(r"delete_user_(\d+)", query.data or "")
        if not match:
            await query.message.reply_text("Ошибка обработки данных пользователя.")
            return
        user_id = int(match.group(1))
        src_msg = query.message
    else:
        text = update.message.text.strip()
        match = re.match(r"Удалить (\d+)", text)
        if not match:
            await update.message.reply_text("Ошибка обработки данных пользователя.")
            return
        user_id = int(match.group(1))
        src_msg = update.message

    user = get_user_by_id(user_id)
    if not user:
        await src_msg.reply_text("Пользователь не найден.")
        return

    users.remove(user)
    save_users()
    await src_msg.reply_text(f"Пользователь {user.get('username')} успешно удалён.")


@access_control(required_role="Admin")
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Введите данные пользователя в формате:\n"
        "Имя Фамилия Username\n\nПример:\nИван Иванов ivan123",
        reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True),
    )
    context.user_data["awaiting_user_data"] = True


@access_control(required_role="Admin")
async def process_new_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_user_data"):
        return

    text = update.message.text.strip()
    if text.lower() == "назад":
        context.user_data["awaiting_user_data"] = False
        await update.message.reply_text(
            "Отмена добавления пользователя.",
            reply_markup=get_main_menu_keyboard(update.effective_user.id),
        )
        return

    try:
        first_name, last_name, username = text.split()
    except ValueError:
        await update.message.reply_text(
            "Ошибка: данные должны быть введены в формате:\n"
            "Имя Фамилия Username\nПопробуйте еще раз."
        )
        return

    if any(u.get("username") == username for u in users):
        await update.message.reply_text(
            f"Ошибка: пользователь с username {username} уже существует."
        )
        return

    new_id = max((u.get("user_id", 0) for u in users), default=0) + 1
    users.append(
        {
            "user_id": new_id,
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "role": "User",
            "status": "approved",
        }
    )
    save_users()
    context.user_data["awaiting_user_data"] = False
    await update.message.reply_text(
        f"Пользователь {first_name} {last_name} ({username}) успешно добавлен.",
        reply_markup=get_main_menu_keyboard(update.effective_user.id),
    )


@access_control(required_role="Admin")
async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        msg_text = query.data or ""
        src_msg = query.message
    else:
        msg_text = update.message.text.strip()
        src_msg = update.message

    match = re.match(r"Утвердить (\d+)", msg_text)
    if not match:
        await src_msg.reply_text("Ошибка обработки данных пользователя.")
        return

    user_id = int(match.group(1))
    user = get_user_by_id(user_id)
    if not user:
        await src_msg.reply_text("Пользователь не найден.")
        return

    user["status"] = "active"
    save_users()

    await src_msg.reply_text(f"Пользователь {user.get('username')} успешно утвержден.")


@access_control(required_role="Admin")
async def reject_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    match = re.match(r"reject_user_(\d+)", query.data or "")
    if not match:
        await query.message.reply_text("Ошибка обработки данных пользователя.")
        return

    user_id = int(match.group(1))
    user = get_user_by_id(user_id)
    if not user:
        await query.message.reply_text("Пользователь не найден.")
        return

    users.remove(user)
    save_users()
    await query.message.reply_text(f"Пользователь {user.get('username')} успешно удален.")


@access_control()
async def user_devices_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    match = re.match(r"user_devices_(\d+)", query.data or "")
    if not match:
        await query.message.reply_text("Ошибка данных пользователя.")
        return
    user_id = int(match.group(1))

    user_devs = [d for d in devices if d.get("user_id") == user_id]
    if not user_devs:
        await query.message.reply_text(
            "У пользователя нет забронированных устройств.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Назад", callback_data=f"user_{user_id}")]]
            ),
        )
        return

    dev_list = "\n".join([f"{d['name']} (SN: {d['sn']})" for d in user_devs])
    await query.message.reply_text(
        f"Забронированные устройства пользователя:\n{dev_list}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Назад", callback_data=f"user_{user_id}")]]
        ),
    )


# ==============================
#   Неизвестные сообщения
# ==============================

async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Неизвестная команда или сообщение. Вот список доступных команд:\n"
    )
    await help_command(update, context)
    await return_to_main_menu(update, context)


# ==============================
#   Точка входа
# ==============================

def main() -> None:
    load_all_data()
    app = Application.builder().token(config["bot_token"]).build()

    # Команды
    app.add_handler(CommandHandler("start", return_to_main_menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("register", register_user))

    # Основные текстовые кнопки
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Назад$"), go_back))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Главное меню$"), return_to_main_menu))

    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Список устройств$"), list_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Бронирование$"), book_device))
    # тип устройства — любые строки из config["device_types"]
    type_pattern = "^(" + "|".join(re.escape(t) for t in config.get("device_types", [])) + ")$"
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(type_pattern), select_device))

    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r".* - ID \d+$"), book_specific_device))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Мои устройства$"), my_devices))

    # Освобождение устройств (пользователь)
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Освободить .* \\(SN: .*\\)$"), release_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Освободить все устройства$"), release_devices))
    app.add_handler(CallbackQueryHandler(release_devices, pattern="^release_.*"))
    app.add_handler(CallbackQueryHandler(release_devices, pattern="^release_all_devices$"))

    # Админ-панель
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Администрирование$"), admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Просмотр забронированных устройств$"), all_booked_devices))

    # Управление устройствами
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Управление устройствами$"), manage_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Добавить устройство$"), add_device))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Импортировать устройства$"), import_devices))
    app.add_handler(MessageHandler(filters.Document.FileExtension("csv"), process_import_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^.* \\(SN: .*\\)$"), manage_selected_device))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Изменить имя устройства \\(ID: .*\\)$"), edit_device_name))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Удалить устройство \\(ID: .*\\)$"), delete_device))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_new_device))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_edit_device_name))

    # Управление пользователями
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Управление пользователями$"), manage_users))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Список всех пользователей$"), view_all_users))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Включить регистрацию$"), toggle_registration))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Выключить регистрацию$"), toggle_registration))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Утвердить .*"), approve_user))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Удалить .*"), delete_user))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Добавить пользователя$"), add_user))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Пользователь:.*"), process_new_user))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Редактировать пользователя:.*"), process_edit_user))

    app.add_handler(CallbackQueryHandler(view_all_users, pattern="^view_all_users$"))
    app.add_handler(CallbackQueryHandler(manage_selected_user, pattern="^user_.*"))
    app.add_handler(CallbackQueryHandler(delete_user, pattern="^delete_user_.*"))
    app.add_handler(CallbackQueryHandler(user_devices_admin, pattern="^user_devices_.*"))

    # Неизвестные сообщения — в самом конце
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    app.run_polling()


if __name__ == "__main__":
    main()
