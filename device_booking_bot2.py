from datetime import datetime
import re
import csv
import json
import os
from typing import Any
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Флаг для включения регистрации
registration_enabled = False

# Загрузка данных с обработкой ошибок
def load_data(filename):
    if not os.path.exists(filename):
        return {} if filename == "devices.json" else []
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(filename: str, data: Any) -> None:
    with open(filename, "w", encoding="utf-8") as f:  # Явно указано, что это объект записи строк
        if isinstance(f, io.TextIOWrapper):          # Убедитесь, что файл открыт в режиме записи текста
            json.dump(data, f, indent=4, ensure_ascii=False)

# Загрузка конфигурации
config = load_data("config.json")
devices = load_data("devices.json")
users = load_data("users.json")


# Получение роли пользователя
def get_user_role(user_id):
    for user in users:
        if user["user_id"] == user_id and user["status"] == "active":
            return user["role"]
    return None


# Получение имени пользователя
def get_user_full_name(user_id):
    for user in users:
        if user["user_id"] == user_id:
            return f"{user.get('first_name', 'Неизвестно')} {user.get('last_name', 'Неизвестно')}"
    return "Неизвестно"


# Получение устройств пользователя
def get_user_devices(user_id):
    booked_devices = []
    for device_type, items in devices.items():
        for device in items:
            if device.get("user_id") == user_id:
                booked_devices.append(device)
    return booked_devices


# Управление пользователями
async def manage_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    pending_users = [user for user in users if user["status"] == "pending"]

    # Кнопки для управления заявками пользователей
    keyboard = [
        [
            InlineKeyboardButton(f"Утвердить {user['username']}", callback_data=f"approve_user_{user['user_id']}"),
            InlineKeyboardButton(f"Удалить {user['username']}", callback_data=f"reject_user_{user['user_id']}")
        ]
        for user in pending_users
    ]

    # Кнопка для переключения режима регистрации
    registration_status = "Выключить регистрацию" if registration_enabled else "Включить регистрацию"
    keyboard.append([InlineKeyboardButton(registration_status, callback_data="toggle_registration")])

    # Кнопка для просмотра всех пользователей
    keyboard.append([InlineKeyboardButton("Список всех пользователей", callback_data="view_all_users")])
    keyboard.append([InlineKeyboardButton("Назад", callback_data="admin_panel")])
    keyboard.append([InlineKeyboardButton("Главное меню", callback_data="main_menu")])

    # Проверяем, что query.message существует
    if query.message:
        await query.message.reply_text(
            "Управление пользователями:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # Обработка случая, когда message отсутствует
        print("Message object is None or inaccessible")


# Просмотр всех пользователей с кнопками и ролями
async def view_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not users:
        await query.message.reply_text("Список пользователей пуст.")
        return

    # Создаем кнопки для каждого пользователя с указанием роли
    keyboard = [
        [
            InlineKeyboardButton(f"{user['first_name']} {user['last_name']} ({user['role']})", callback_data=f"edit_user_{user['user_id']}"),
            InlineKeyboardButton("Удалить", callback_data=f"delete_user_{user['user_id']}")
        ]
        for user in users
    ]

    keyboard.append([InlineKeyboardButton("Назад", callback_data="manage_users")])

    await query.message.reply_text(
        "Список пользователей:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# Редактирование пользователя
async def edit_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        _, user_id = query.data.split("_", 1)
        user_id = int(user_id)
    except ValueError:
        await query.message.reply_text("Ошибка обработки данных пользователя.")
        return

    user = next((u for u in users if u["user_id"] == user_id), None)
    if not user:
        await query.message.reply_text("Пользователь не найден.")
        return

    context.user_data["action"] = f"edit_user_{user_id}"
    await query.message.reply_text(
        f"Редактирование пользователя {user['first_name']} {user['last_name']}.\n"
        "Введите новые данные в формате: Имя, Фамилия, Username, Роль"
    )


# Обработка редактирования пользователя
async def process_edit_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get("action")
    if action and action.startswith("edit_user_"):
        user_id = int(action.split("_")[-1])
        user = next((u for u in users if u["user_id"] == user_id), None)

        if not user:
            await update.message.reply_text("Пользователь не найден.")
            return

        try:
            first_name, last_name, username, role = map(str.strip, update.message.text.split(","))
        except ValueError:
            await update.message.reply_text("Некорректный формат. Используйте: Имя, Фамилия, Username, Роль")
            return

        # Обновление данных пользователя
        user.update({
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "role": role
        })
        save_data("users.json", users)
        await update.message.reply_text(f"Данные пользователя {first_name} {last_name} успешно обновлены.")
        del context.user_data["action"]  # Удаляем состояние
        await view_all_users(update, context)


# Удаление пользователя
async def delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, user_id = query.data.split("_")
    user_id = int(user_id)

    user = next((u for u in users if u["user_id"] == user_id), None)
    if not user:
        await query.message.reply_text("Пользователь не найден.")
        return

    users.remove(user)
    save_data("users.json", users)
    await query.message.reply_text(f"Пользователь {user['first_name']} {user['last_name']} успешно удален.")
    await view_all_users(update, context)  # Обновляем список пользователей


# Добавление нового пользователя
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["action"] = "add_user"
    await query.message.reply_text("Введите данные нового пользователя в формате: Имя, Фамилия, Username")


# Обработка ввода нового пользователя
async def process_new_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("action") == "add_user":
        try:
            first_name, last_name, username = map(str.strip, update.message.text.split(","))
        except ValueError:
            await update.message.reply_text("Некорректный формат. Используйте: Имя, Фамилия, Username")
            return

        new_user = {
            "user_id": max([u["user_id"] for u in users], default=0) + 1,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "role": "User",
            "status": "active"
        }
        users.append(new_user)
        save_data("users.json", users)
        await update.message.reply_text(f"Пользователь {first_name} {last_name} успешно добавлен.")


# Редактирование пользователя
async def edit_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, user_id = query.data.split("_")
    user_id = int(user_id)

    user = next((u for u in users if u["user_id"] == user_id), None)
    if not user:
        await query.message.reply_text("Пользователь не найден.")
        return

    context.user_data["action"] = f"edit_user_{user_id}"
    await query.message.reply_text(
        f"Редактирование пользователя {user['first_name']} {user['last_name']}.\n"
        "Введите новые данные в формате: Имя, Фамилия, Username, Роль"
    )


# Включение/выключение регистрации
async def toggle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global registration_enabled

    # Определяем источник вызова
    if update.message:
        user_id = update.effective_user.id
        sender = update.message
    elif update.callback_query:
        query = update.callback_query
        user_id = query.from_user.id
        sender = query.message
    else:
        return  # Неизвестный источник вызова

    if not is_admin(user_id):
        await sender.reply_text("У вас нет доступа к этой функции.")
        return

    registration_enabled = not registration_enabled
    status = "включен" if registration_enabled else "выключен"
    await sender.reply_text(f"Режим регистрации {status}.")


# Команда /register
async def register_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global registration_enabled

    if not registration_enabled:
        await update.message.reply_text("Регистрация временно отключена.")
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "Не указано"
    first_name = update.effective_user.first_name or "Не указано"
    last_name = update.effective_user.last_name or "Не указано"

    # Проверка, если пользователь уже существует
    for user in users:
        if user["user_id"] == user_id:
            await update.message.reply_text("Вы уже зарегистрированы или ваша заявка ожидает рассмотрения.")
            return

    # Добавление заявки в список пользователей
    users.append({
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "role": "User",
        "status": "pending"
    })
    save_data("users.json", users)
    await update.message.reply_text("Ваша заявка на регистрацию отправлена. Ожидайте подтверждения администратора.")


# Одобрение заявки пользователя
async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Используем регулярное выражение для извлечения user_id
    match = re.match(r"approve_user_(\d+)", query.data)
    if not match:
        await query.message.reply_text("Ошибка обработки данных пользователя.")
        return

    user_id = int(match.group(1))  # Извлекаем user_id

    user = next((u for u in users if u["user_id"] == user_id), None)
    if not user:
        await query.message.reply_text("Пользователь не найден.")
        return

    user["status"] = "active"
    save_data("users.json", users)
    await query.message.reply_text(f"Пользователь {user['username']} успешно утвержден.")



# Отклонение заявки пользователя
async def reject_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Используем регулярное выражение для извлечения user_id
    match = re.match(r"reject_user_(\d+)", query.data)
    if not match:
        await query.message.reply_text("Ошибка обработки данных пользователя.")
        return

    user_id = int(match.group(1))  # Извлекаем user_id

    user = next((u for u in users if u["user_id"] == user_id), None)
    if not user:
        await query.message.reply_text("Пользователь не найден.")
        return

    users.remove(user)
    save_data("users.json", users)
    await query.message.reply_text(f"Пользователь {user['username']} успешно удален.")


# Возврат в главное меню
async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = get_user_role(user_id)

    if role is None:
        if update.message:
            await update.message.reply_text("У вас нет доступа к боту. Пройдите регистрацию через /register.")
        elif update.callback_query:
            await update.callback_query.message.reply_text("У вас нет доступа к боту. Пройдите регистрацию через /register.")
        return

    keyboard = [
        [InlineKeyboardButton("Список устройств", callback_data="list_devices")],
        [InlineKeyboardButton("Бронирование", callback_data="book_device")],
        [InlineKeyboardButton("Мои устройства", callback_data="my_devices")],
        #[InlineKeyboardButton("Забронированные устройства", callback_data="all_booked_devices")]
    ]
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("Администрирование", callback_data="admin_panel")])

    if update.message:
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            "Главное меню:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def list_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    all_devices = []
    for device_type, items in devices.items():
        all_devices.append(f"Тип: {device_type}")
        for item in items:
            status = "Свободно" if item["status"] == "free" else "Забронировано"
            booked_by = f" (Забронировано: {get_user_full_name(item['user_id'])})" if item["status"] == "booked" else ""
            all_devices.append(f"- {item['name']} (SN: {item['sn']}, {status}){booked_by}")

    keyboard = [
        [InlineKeyboardButton("Главное меню", callback_data="main_menu")],
        [InlineKeyboardButton("Назад", callback_data="admin_panel" if is_admin(query.from_user.id) else "return_to_main_menu")]
    ]

    if not all_devices:
        await query.message.reply_text("Устройства отсутствуют.", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.message.reply_text("\n".join(all_devices), reply_markup=InlineKeyboardMarkup(keyboard))


# Бронирование устройства
async def book_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton(device_type, callback_data=f"select_device_type_{device_type}")]
        for device_type in devices.keys()
    ]
    await query.message.reply_text(
        "Выберите тип устройства для бронирования:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# Выбор устройства для бронирования
async def select_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    device_type = query.data.split("_")[-1]

    available_devices = [d for d in devices[device_type] if d["status"] == "free"]

    if not available_devices:
        keyboard = [
            [InlineKeyboardButton("Главное меню", callback_data="main_menu")],
            [InlineKeyboardButton("Назад", callback_data="select_device")]
        ]
        await query.message.reply_text(f"Нет доступных устройств типа {device_type}.",reply_markup=InlineKeyboardMarkup(keyboard))
        return

    keyboard = [
        [InlineKeyboardButton(f"{d['name']} (SN: {d['sn']})", callback_data=f"book_{device_type}_{d['id']}")]
        for d in available_devices
    ]
    await query.message.reply_text(
        "Выберите устройство для бронирования:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# Подтверждение бронирования устройства
async def book_specific_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, device_type, device_id = query.data.split("_")
    device_id = int(device_id)

    for device in devices[device_type]:
        if device["id"] == device_id and device["status"] == "free":
            device["status"] = "booked"
            device["user_id"] = query.from_user.id
            save_data("devices.json", devices)
            log_action("BOOKED", query.from_user.id, device["name"], device["sn"])
            await query.message.reply_text(f"Устройство {device['name']} {device["sn"]} успешно забронировано.")
            await return_to_main_menu(update, context)
            return

    await query.message.reply_text("Ошибка при бронировании устройства.")


async def my_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    booked_devices = get_user_devices(user_id)
    if not booked_devices:
        await query.message.reply_text("У вас нет забронированных устройств.")
        return

    # Кнопки для освобождения каждого устройства
    keyboard = [
        [InlineKeyboardButton(f"Освободить {d['name']} (SN: {d['sn']})",
                              callback_data=f"release_device_{device_type}_{d['id']}")]
        for device_type, items in devices.items()
        for d in items if d.get("user_id") == user_id
    ]
    # Кнопка для освобождения всех устройств
    keyboard.append([InlineKeyboardButton("Освободить все устройства", callback_data="release_all_user_devices")])
    keyboard.append([InlineKeyboardButton("Главное меню", callback_data="main_menu")])

    device_list = "\n".join([f"{d['name']} (SN: {d['sn']})" for d in booked_devices])

    await query.message.reply_text(
        f"Ваши забронированные устройства:\n{device_list}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def release_all_user_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    released_any = False

    for device_type, items in devices.items():
        for device in items:
            if device.get("user_id") == user_id:
                log_action("RELEASED", user_id, device["name"], device["sn"])
                device["status"] = "free"
                device.pop("user_id", None)
                released_any = True

    if released_any:
        save_data("devices.json", devices)
        await query.message.reply_text("Все ваши устройства успешно освобождены.")
    else:
        await query.message.reply_text("У вас нет забронированных устройств.")
        return  # Завершаем выполнение, чтобы избежать вызова my_devices

    # Проверяем, остались ли устройства перед вызовом my_devices
    if get_user_devices(user_id):
        await my_devices(update, context)


async def release_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Используем регулярное выражение для извлечения device_type и device_id
    match = re.match(r"release_device_(\w+)_(\d+)", query.data)
    if not match:
        await query.message.reply_text("Ошибка: некорректные данные.")
        return

    device_type, device_id = match.groups()
    device_id = int(device_id)

    user_id = query.from_user.id

    # Проверяем устройства конкретного типа
    for device in devices.get(device_type, []):
        if device["id"] == device_id:
            # Если пользователь — User, проверяем, является ли он владельцем устройства
            if not is_admin(user_id) and device.get("user_id") != user_id:
                await query.message.reply_text("Ошибка: вы не можете освободить это устройство.")
                return

            # Логирование действия
            action = "ADMIN RELEASED" if is_admin(user_id) else "USER RELEASED"
            log_action(action, user_id, device["name"], device["sn"])

            # Освобождаем устройство
            device["status"] = "free"
            device.pop("user_id", None)
            save_data("devices.json", devices)

            keyboard = [
                [InlineKeyboardButton("Главное меню", callback_data="main_menu")],
                [InlineKeyboardButton("Назад", callback_data="my_devices")]
            ]

            await query.message.reply_text(
                f"Устройство {device['name']} (SN: {device['sn']}) успешно освобождено.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

    await query.message.reply_text("Ошибка: устройство не найдено.")




# Панель администрирования
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("Управление устройствами", callback_data="manage_devices")],
        [InlineKeyboardButton("Управление пользователями", callback_data="manage_users")],
        [InlineKeyboardButton("Забронированные устройства", callback_data="all_booked_devices")],
        [InlineKeyboardButton("Назад в меню", callback_data="main_menu")]
    ]
    await query.message.reply_text(
        "Панель администрирования:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def all_booked_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not is_admin(user_id):
        await query.message.reply_text("У вас нет доступа к этой функции.")
        return

    booked_devices = []
    for device_type, items in devices.items():
        for device in items:
            if device["status"] == "booked":
                user_name = get_user_full_name(device["user_id"])
                booked_devices.append({
                    "device": device,
                    "user_name": user_name
                })

    if not booked_devices:
        await query.message.reply_text("Нет забронированных устройств.")
        return

    # Кнопки для освобождения каждого устройства
    keyboard = [
        [InlineKeyboardButton(f"Освободить {d['device']['name']} (SN: {d['device']['sn']}) - {d['user_name']}",
                              callback_data=f"admin_release_device_{d['device']['id']}_{d['device']['sn']}")]
        for d in booked_devices
    ]
    # Кнопка для освобождения всех устройств
    keyboard.append([InlineKeyboardButton("Освободить все устройства", callback_data="admin_release_all_devices")])
    keyboard.append([InlineKeyboardButton("Назад", callback_data="admin_panel")])

    device_list = "\n".join([
        f"{d['device']['name']} (SN: {d['device']['sn']}) - {d['user_name']}"
        for d in booked_devices
    ])

    await query.message.reply_text(
        f"Забронированные устройства:\n{device_list}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_release_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Извлекаем device_id и sn из callback_data
    _, device_id_str, device_sn = query.data.split("_", 2)
    device_id = int(device_id_str)

    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.message.reply_text("У вас нет доступа к этой функции.")
        return

    for device_type, items in devices.items():
        for device in items:
            if device["id"] == device_id and device["sn"] == device_sn and device["status"] == "booked":
                log_action("ADMIN RELEASED", device["user_id"], device["name"], device["sn"])
                device["status"] = "free"
                device.pop("user_id", None)
                save_data("devices.json", devices)
                await query.message.reply_text(f"Устройство {device['name']} (SN: {device['sn']}) освобождено.")
                await all_booked_devices(update, context)
                return

    await query.message.reply_text("Ошибка: устройство не найдено или уже освобождено.")


async def admin_release_all_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.message.reply_text("У вас нет доступа к этой функции.")
        return

    released_any = False

    for device_type, items in devices.items():
        for device in items:
            if device["status"] == "booked":
                log_action("ADMIN RELEASED", device["user_id"], device["name"], device["sn"])
                device["status"] = "free"
                device.pop("user_id", None)
                released_any = True

    if released_any:
        save_data("devices.json", devices)
        await query.message.reply_text("Все устройства успешно освобождены.")
    else:
        await query.message.reply_text("Нет забронированных устройств.")

    await all_booked_devices(update, context)


# Освобождение всех устройств (для администраторов)
async def release_all_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.message.reply_text("У вас нет доступа к этой функции.")
        return

    for device_type, items in devices.items():
        for device in items:
            if device["status"] == "booked":
                log_action("RELEASED", device["user_id"], device["name"], device["sn"])
                device["status"] = "free"
                device.pop("user_id", None)

    save_data("devices.json", devices)
    await query.message.reply_text("Все устройства успешно освобождены.")
    await return_to_main_menu(update, context)


# Управление устройствами
async def manage_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton(f"{device['name']} (SN: {device['sn']})", callback_data=f"edit_device_{device_type}_{device['id']}"),
            InlineKeyboardButton("История", callback_data=f"history_{device['sn']}")
        ]
        for device_type, items in devices.items()
        for device in items
    ]
    keyboard.append([InlineKeyboardButton("Добавить устройство", callback_data="add_device")])
    keyboard.append([InlineKeyboardButton("Импортировать устройства", callback_data="import_devices")])

    await query.message.reply_text(
        "Управление устройствами:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )



# Добавление устройства
async def add_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["action"] = "add_device"
    await query.message.reply_text("Введите данные нового устройства в формате: SN, Name, Type")


# Обработка импорта устройств
async def import_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["action"] = "import_devices"
    await query.message.reply_text("Отправьте CSV файл с колонками: SN, Name, Type")


# Просмотр истории бронирований устройства
async def view_device_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, device_sn = query.data.split("_")

    try:
        with open("device_logs.txt", "r", encoding="utf-8") as f:
            logs = f.readlines()
        device_logs = [log for log in logs if f"SN={device_sn}" in log]
        if device_logs:
            await query.message.reply_text(
                f"История устройства (SN: {device_sn}):\n" + "".join(device_logs)
            )
        else:
            await query.message.reply_text("История устройства отсутствует.")
    except FileNotFoundError:
        await query.message.reply_text("Файл истории не найден.")


# Обработка ввода нового устройства
async def process_new_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("action") == "add_device":
        try:
            sn, name, device_type = map(str.strip, update.message.text.split(","))
        except ValueError:
            await update.message.reply_text("Некорректный формат. Используйте: SN, Name, Type")
            return

        if device_type not in devices:
            devices[device_type] = []

        devices[device_type].append({
            "id": len(devices[device_type]) + 1,
            "name": name,
            "sn": sn,
            "status": "free"
        })
        save_data("devices.json", devices)
        await update.message.reply_text(f"Устройство {name} успешно добавлено.")
        await return_to_main_menu(update, context)


def log_action(action_type, user_id, device_name, device_sn):
    user_full_name = get_user_full_name(user_id)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("device_logs.txt", "a", encoding="utf-8") as f:
        f.write(f"{timestamp} | {action_type}: {user_full_name} (UserID={user_id}), Device={device_name}, SN={device_sn}\n")

def is_admin(user_id):
    return get_user_role(user_id) == "Admin"


# Обработка неизвестных сообщений
async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Неизвестная команда или сообщение. Вот список доступных команд:\n"
    )
    await help_command(update, context)
    await return_to_main_menu(update, context)

# Справка
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/start - Главное меню\n"
        "/help - Справка\n"
        "/register - Зарегистрироваться\n"
        "\nДоступные функции зависят от вашей роли."
    )

# Обработка импорта устройств из CSV
async def process_import_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("action") == "import_devices":
        file = update.message.document
        file_object = await file.get_file()  # Асинхронный метод получения файла
        file_path = await file_object.download_to_drive()

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                # Проверка колонок
                required_columns = {"SN", "Name", "Type"}
                if not required_columns.issubset(set(reader.fieldnames)):
                    raise ValueError("Неверный формат файла CSV. Отсутствуют обязательные колонки: SN, Name, Type.")
                for row in reader:
                    device_type = row["Type"].strip()
                    if device_type not in devices:
                        devices[device_type] = []

                    devices[device_type].append({
                        "id": len(devices[device_type]) + 1,
                        "name": row["Name"].strip(),
                        "sn": row["SN"].strip(),
                        "status": "free"
                    })

            save_data("devices.json", devices)
            await update.message.reply_text("Устройства успешно импортированы.")
        except FileNotFoundError:
            await update.message.reply_text("Ошибка: файл не найден.")
        except ValueError as ve:
            await update.message.reply_text(f"Ошибка: {ve}")
        finally:
            os.remove(file_path)  # Удаляем временный файл



# Основная функция
def main():
    app = Application.builder().token(config["bot_token"]).build()

    # Обработчики команд
    app.add_handler(CommandHandler("start", return_to_main_menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))
    app.add_handler(CallbackQueryHandler(list_devices, pattern="list_devices"))
    app.add_handler(CallbackQueryHandler(book_device, pattern="book_device"))
    app.add_handler(CallbackQueryHandler(select_device, pattern="select_device_type_.*"))
    app.add_handler(CallbackQueryHandler(book_specific_device, pattern="book_.*"))
    app.add_handler(CallbackQueryHandler(my_devices, pattern="my_devices"))
    app.add_handler(CallbackQueryHandler(all_booked_devices, pattern="all_booked_devices"))
    app.add_handler(CallbackQueryHandler(release_all_devices, pattern="release_all_devices"))
    app.add_handler(CallbackQueryHandler(release_device, pattern=r"release_device_\w+_\d+"))
    app.add_handler(CallbackQueryHandler(release_all_user_devices, pattern="release_all_user_devices"))
    app.add_handler(CallbackQueryHandler(admin_release_all_devices, pattern="admin_release_all_devices"))

    # Управление устройствами
    app.add_handler(CallbackQueryHandler(manage_devices, pattern="manage_devices"))
    app.add_handler(CallbackQueryHandler(add_device, pattern="add_device"))
    app.add_handler(CallbackQueryHandler(import_devices, pattern="import_devices"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_new_device))
    app.add_handler(MessageHandler(filters.Document.FileExtension("csv"), process_import_devices))

    # Панель администрирования
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="admin_panel"))
    app.add_handler(CallbackQueryHandler(return_to_main_menu, pattern="main_menu"))
    app.add_handler(CallbackQueryHandler(view_device_history, pattern="history_.*"))
    app.add_handler(CallbackQueryHandler(toggle_registration, pattern="toggle_registration"))

    # Управление пользователями
    app.add_handler(CallbackQueryHandler(manage_users, pattern="manage_users"))
    app.add_handler(CallbackQueryHandler(approve_user, pattern="approve_user_.*"))
    app.add_handler(CallbackQueryHandler(reject_user, pattern="reject_user_.*"))
    app.add_handler(CommandHandler("register", register_user))
    app.add_handler(CommandHandler("toggle_registration", toggle_registration))
    app.add_handler(CallbackQueryHandler(view_all_users, pattern="view_all_users"))
    app.add_handler(CallbackQueryHandler(add_user, pattern="add_user"))
    app.add_handler(CallbackQueryHandler(edit_user, pattern="edit_user_.*"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_new_user))
    app.add_handler(CallbackQueryHandler(view_all_users, pattern="view_all_users"))
    app.add_handler(CallbackQueryHandler(delete_user, pattern="delete_user_.*"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_edit_user))

    app.run_polling()

if __name__ == "__main__":
    main()
