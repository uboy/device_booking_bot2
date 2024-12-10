import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import re
import csv
import json
import os
from typing import Any
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Флаг для включения регистрации
registration_enabled = False

scheduler = AsyncIOScheduler()


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
    return [device for device in devices if device.get("user_id") == user_id]



# Управление пользователями
async def manage_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "У вас нет доступа к управлению пользователями.",
            reply_markup=ReplyKeyboardMarkup([["Главное меню"]], resize_keyboard=True)
        )
        return

    pending_users = [user for user in users if user["status"] == "pending"]

    keyboard = [
        [
            f"Утвердить {user['username']}",
            f"Удалить {user['username']}"
        ]
        for user in pending_users
    ]

    # Добавляем опции управления регистрацией
    registration_status = "Выключить регистрацию" if registration_enabled else "Включить регистрацию"
    keyboard.append([registration_status])
    keyboard.append(["Список всех пользователей", "Назад"])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Управление пользователями:",
        reply_markup=reply_markup
    )


# Просмотр всех пользователей с кнопками и ролями
async def view_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "У вас нет доступа к списку пользователей.",
            reply_markup=ReplyKeyboardMarkup([["Главное меню"]], resize_keyboard=True)
        )
        return

    keyboard = [
        [InlineKeyboardButton(f"{user['name']} {user['surname']} ({user['status']})", callback_data=f"user_{user['user_id']}")]
        for user in users
    ]
    keyboard.append([InlineKeyboardButton("Назад", callback_data="admin_panel")])

    await update.message.reply_text(
        "Список пользователей:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def manage_selected_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Извлекаем ID пользователя из callback_data
    user_id = int(query.data.split("_")[1])

    # Поиск пользователя по ID
    selected_user = next((u for u in users if u["user_id"] == user_id), None)

    if not selected_user:
        await query.message.reply_text("Пользователь не найден.")
        return

    # Меню для управления пользователем
    keyboard = [
        [InlineKeyboardButton("Удалить пользователя", callback_data=f"delete_user_{user_id}")],
        [InlineKeyboardButton("Забронированные устройства", callback_data=f"user_devices_{user_id}")],
        [InlineKeyboardButton("Назад", callback_data="view_all_users")]
    ]

    await query.message.reply_text(
        f"Управление пользователем:\nИмя: {selected_user['name']}\nФамилия: {selected_user['surname']}\nСтатус: {selected_user['status']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
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

    # Извлекаем ID пользователя из callback_data
    user_id = int(query.data.split("_")[2])

    # Поиск пользователя по ID
    user = next((u for u in users if u["user_id"] == user_id), None)

    if not user:
        await query.message.reply_text("Пользователь не найден.")
        return

    users.remove(user)
    save_data("users.json", users)

    await query.message.reply_text(
        f"Пользователь {user['name']} {user['surname']} удален.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="view_all_users")]])
    )


async def user_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Извлекаем ID пользователя из callback_data
    user_id = int(query.data.split("_")[2])

    # Поиск устройств, забронированных пользователем
    booked_devices = [device for device in devices if device.get("user_id") == user_id]

    if not booked_devices:
        await query.message.reply_text(
            "У пользователя нет забронированных устройств.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data=f"user_{user_id}")]])
        )
        return

    device_list = "\n".join([f"{d['name']} (SN: {d['sn']})" for d in booked_devices])

    await query.message.reply_text(
        f"Забронированные устройства пользователя:\n{device_list}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data=f"user_{user_id}")]])
    )


# Добавление нового пользователя
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "У вас нет доступа к добавлению пользователей.",
            reply_markup=ReplyKeyboardMarkup([["Главное меню"]], resize_keyboard=True)
        )
        return

    # Сообщение для ввода данных нового пользователя
    await update.message.reply_text(
        "Введите данные пользователя в формате:\n"
        "Имя Фамилия Username\n\nПример:\nИван Иванов ivan123",
        reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
    )
    context.user_data["awaiting_user_data"] = True


# Обработка ввода нового пользователя
async def process_new_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_user_data"):
        return

    user_data = update.message.text.strip()
    try:
        # Разделяем введенный текст на части
        name, surname, username = user_data.split()
    except ValueError:
        await update.message.reply_text(
            "Ошибка: данные должны быть введены в формате:\nИмя Фамилия Username\nПопробуйте еще раз.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
        )
        return

    # Проверка на уникальность username
    if any(user["username"] == username for user in users):
        await update.message.reply_text(
            f"Ошибка: пользователь с username {username} уже существует.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
        )
        return

    # Добавляем нового пользователя
    new_user = {
        "user_id": max(user["user_id"] for user in users) + 1 if users else 1,
        "name": name,
        "surname": surname,
        "username": username,
        "status": "approved"
    }
    users.append(new_user)
    save_data("users.json", users)

    # Подтверждение успешного добавления
    await update.message.reply_text(
        f"Пользователь {name} {surname} ({username}) успешно добавлен.",
        reply_markup=ReplyKeyboardMarkup([["Главное меню"]], resize_keyboard=True)
    )
    context.user_data["awaiting_user_data"] = False


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
    registration_enabled = not registration_enabled

    status = "включена" if registration_enabled else "выключена"
    await update.message.reply_text(f"Регистрация {status}.")


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
    user_text = update.message.text.strip()

    if not user_text.startswith("Утвердить"):
        return

    username = user_text.replace("Утвердить", "").strip()
    user = next((u for u in users if u["username"] == username and u["status"] == "pending"), None)

    if not user:
        await update.message.reply_text("Пользователь не найден или уже утвержден.")
        return

    user["status"] = "approved"
    save_data("users.json", users)

    await update.message.reply_text(f"Пользователь {username} утвержден.")


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
    keyboard = [["Список устройств", "Бронирование"], ["Мои устройства"]]
    if is_admin(update.effective_user.id):
        keyboard.append(["Администрирование"])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Главное меню:", reply_markup=reply_markup)


async def join_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Извлекаем ID устройства
    device_id = int(query.data.split("_")[2])
    user_id = update.effective_user.id

    # Поиск устройства
    device = next((d for d in devices if d["id"] == device_id), None)

    if not device:
        await query.message.reply_text("Устройство не найдено.")
        return

    if user_id in device["queue"]:
        await query.message.reply_text("Вы уже находитесь в очереди на это устройство.")
        return

    device["queue"].append(user_id)
    save_data("devices.json", devices)

    await query.message.reply_text(f"Вы встали в очередь на устройство {device['name']} (SN: {device['sn']}).")


async def check_booking_expiration(application):
    now = datetime.now()

    for device in devices:
        if device["status"] == "booked" and device["booking_expiration"]:
            expiration_date = datetime.fromisoformat(device["booking_expiration"])

            if expiration_date <= now:
                user_id = device["user_id"]
                device["status"] = "free"
                device["user_id"] = None
                device["booking_expiration"] = None

                save_data("devices.json", devices)

                # Уведомляем пользователя
                asyncio.create_task(application.bot.send_message(
                    chat_id=user_id,
                    text=f"Срок брони устройства {device['name']} (SN: {device['sn']}) истек."
                ))

                log_action(device["sn"], "Срок брони истек, устройство освобождено.")



async def list_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    all_devices = []

    for device in devices:
        status = "Свободно" if device["status"] == "free" else "Забронировано"
        booked_by = f" (Забронировано: {get_user_full_name(device['user_id'])})" if device["status"] == "booked" else ""
        all_devices.append(f"- {device['name']} (SN: {device['sn']}, Тип: {device['type']}, {status}){booked_by}")

    if not all_devices:
        await update.message.reply_text("Устройства отсутствуют.")
    else:
        await update.message.reply_text("\n".join(all_devices))


# Бронирование устройства
async def book_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    device_types = list(set(device["type"] for device in devices if device["status"] == "free"))

    if not device_types:
        await update.message.reply_text("Нет доступных устройств для бронирования.")
        return

    # Клавиатура для выбора типа устройства
    keyboard = [[device_type] for device_type in device_types]
    keyboard.append(["Назад"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Выберите тип устройства для бронирования:", reply_markup=reply_markup)


async def select_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    device_type = update.message.text.strip()  # Получаем текст выбранного типа устройства

    # Фильтрация доступных устройств
    available_devices = [d for d in devices if d["type"] == device_type and d["status"] == "free"]

    if not available_devices:
        await update.message.reply_text(
            f"Нет доступных устройств типа {device_type}.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
        )
        return

    # Генерация кнопок для выбора устройств
    keyboard = [
        [f"{d['name']} ({d['type']}) - ID {d['id']}"] for d in available_devices
    ]
    keyboard.append(["Назад"])  # Кнопка для возврата
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text("Выберите устройство для бронирования:", reply_markup=reply_markup)


# Подтверждение бронирования устройства
async def book_specific_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    device_text = update.message.text.strip()  # Получаем текст кнопки
    print(f"Получен текст кнопки: {device_text}")  # Логирование для отладки

    try:
        # Извлечение ID устройства из текста кнопки
        device_id = int(device_text.split(" - ID ")[-1])  # Парсим ID из текста
    except (ValueError, IndexError):
        await update.message.reply_text(
            "Ошибка: некорректный формат данных устройства.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
        )
        return

    # Поиск устройства по ID
    device = next((d for d in devices if d["id"] == device_id and d["status"] == "free"), None)

    if not device:
        await update.message.reply_text(
            "Ошибка: устройство не найдено или уже забронировано.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
        )
        return

    # Получите данные устройства...
    booking_period = device.get("default_booking_period", 1)
    expiration_date = datetime.now() + timedelta(days=booking_period)

    device["status"] = "booked"
    device["user_id"] = update.effective_user.id
    device["booking_expiration"] = expiration_date.isoformat()

    save_data("devices.json", devices)

    await update.message.reply_text(
        f"Устройство {device['name']} (SN: {device['sn']}) забронировано до {expiration_date.strftime('%Y-%m-%d %H:%M:%S')}."
    )

    log_action(device["sn"], f"Устройство забронировано пользователем {get_user_full_name(update.effective_user.id)} до {expiration_date.strftime('%Y-%m-%d %H:%M:%S')}.")


# Мои устройства
async def my_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    booked_devices = [device for device in devices if device.get("user_id") == user_id]

    if not booked_devices:
        await update.message.reply_text("У вас нет забронированных устройств.")
        return

    # Генерация кнопок для освобождения устройств
    keyboard = [
        [f"Освободить {d['name']} (SN: {d['sn']})"] for d in booked_devices
    ]
    keyboard.append(["Освободить все устройства", "Назад"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    device_list = "\n".join([f"{d['name']} (SN: {d['sn']})" for d in booked_devices])
    await update.message.reply_text(
        f"Ваши забронированные устройства:\n{device_list}",
        reply_markup=reply_markup
    )


async def release_all_user_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Фильтруем устройства, принадлежащие пользователю
    user_devices = [device for device in devices if device.get("user_id") == user_id]

    if not user_devices:
        await update.message.reply_text(
            "У вас нет забронированных устройств.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
        )
        return

    # Освобождаем устройства
    for device in user_devices:
        device["status"] = "free"
        device.pop("user_id", None)

    # Сохраняем изменения
    save_data("devices.json", devices)

    await update.message.reply_text(
        "Все ваши устройства успешно освобождены.",
        reply_markup=ReplyKeyboardMarkup([["Главное меню"]], resize_keyboard=True)
    )


# Освободить устройство
async def release_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    device_id = ...  # Получите ID устройства
    device = next((d for d in devices if d["id"] == device_id), None)

    if not device:
        await update.message.reply_text("Устройство не найдено.")
        return

    device["status"] = "free"
    user_queue = device.pop("queue", [])

    if user_queue:
        next_user_id = user_queue.pop(0)
        device["queue"] = user_queue
        save_data("devices.json", devices)

        # Уведомляем следующего в очереди
        await context.bot.send_message(
            chat_id=next_user_id,
            text=f"Устройство {device['name']} (SN: {device['sn']}) теперь доступно для бронирования."
        )

    save_data("devices.json", devices)
    await update.message.reply_text("Устройство успешно освобождено.")


# Панель администрирования
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("У вас нет доступа к административному меню.", reply_markup=ReplyKeyboardMarkup([["Главное меню"]], resize_keyboard=True))
        return

    # Клавиатура для администрирования
    keyboard = [
        ["Управление устройствами", "Управление пользователями"],
        ["Просмотр забронированных устройств", "Назад"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text("Меню администрирования:", reply_markup=reply_markup)


# Просмотр забронированных устройств
async def all_booked_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Список забронированных устройств
    booked_devices = [
        {
            "device": device,
            "user_name": get_user_full_name(device["user_id"])
        }
        for device in devices if device["status"] == "booked"
    ]
    keyboard = [
        [
            InlineKeyboardButton(
                f"{device['name']} (SN: {device['sn']}) - {get_user_full_name(device['user_id'])}",
                callback_data=f"queue_{device['id']}"
            )
        ]
        for device in devices if device["status"] == "booked"
    ]
    if not booked_devices:
        await update.message.reply_text("Нет забронированных устройств.", reply_markup=ReplyKeyboardMarkup([["Главное меню"]], resize_keyboard=True))
        return

    device_list = "\n".join([
        f"{d['device']['name']} (SN: {d['device']['sn']}) - {d['user_name']}"
        for d in booked_devices
    ])
    await update.message.reply_text(f"Забронированные устройства:\n{device_list}")


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

    for device_type, items in devices:
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
    await return_to_main_menu(update, context)


async def admin_release_all_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.message.reply_text("У вас нет доступа к этой функции.")
        return

    # Флаг для проверки, были ли устройства освобождены
    released_any = False

    for device in devices:
        if device["status"] == "booked":
            log_action("ADMIN RELEASED", device["user_id"], device["name"], device["sn"])
            device["status"] = "free"
            device.pop("user_id", None)
            released_any = True

    if released_any:
        save_data("devices.json", devices)
        await query.message.reply_text("Все забронированные устройства успешно освобождены.")
    else:
        await query.message.reply_text("Нет забронированных устройств.")
    await return_to_main_menu(update, context)


# Освобождение всех устройств (для администраторов)
async def release_all_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.message.reply_text("У вас нет доступа к этой функции.")
        return

    for device_type, items in devices:
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
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "У вас нет доступа к управлению устройствами.",
            reply_markup=ReplyKeyboardMarkup([["Главное меню"]], resize_keyboard=True)
        )
        return

    keyboard = [
        [
            f"{device['name']} (SN: {device['sn']})",
            f"История {device['name']}"
        ]
        for device in devices
    ]
    keyboard.append(["Добавить устройство", "Импортировать устройства"])
    keyboard.append(["Назад"])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Управление устройствами:",
        reply_markup=reply_markup
    )


async def manage_selected_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    device_text = update.message.text.strip()

    try:
        # Извлекаем название и SN устройства из текста
        name_part, sn_part = device_text.split("(SN:")
        device_name = name_part.strip()
        device_sn = sn_part.replace(")", "").strip()
    except ValueError:
        await update.message.reply_text(
            "Ошибка: некорректный формат данных устройства.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
        )
        return

    # Поиск устройства в списке
    device = next((d for d in devices if d["name"] == device_name and d["sn"] == device_sn), None)

    if not device:
        await update.message.reply_text("Устройство не найдено.")
        return

    # Меню управления устройством
    keyboard = [
        [f"Изменить имя устройства (ID: {device['id']})"],
        [f"Удалить устройство (ID: {device['id']})"],
        ["Назад"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        f"Управление устройством:\nНазвание: {device['name']}\nSN: {device['sn']}\nТип: {device['type']}",
        reply_markup=reply_markup
    )


async def edit_device_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    device_id_text = update.message.text.strip()

    try:
        # Извлекаем ID устройства
        device_id = int(device_id_text.split("(ID:")[1].replace(")", "").strip())
    except (ValueError, IndexError):
        await update.message.reply_text("Ошибка: некорректный формат ID устройства.")
        return

    device = next((d for d in devices if d["id"] == device_id), None)

    if not device:
        await update.message.reply_text("Устройство не найдено.")
        return

    context.user_data["editing_device_id"] = device_id
    await update.message.reply_text(
        "Введите новое имя устройства:",
        reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True)
    )


async def edit_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Извлечение ID устройства
    device_id = int(query.data.split("_")[1])

    # Поиск устройства по ID
    device = next((d for d in devices if d["id"] == device_id), None)

    if not device:
        await query.message.reply_text("Устройство не найдено.")
        return

    await query.message.reply_text(
        f"Редактирование устройства {device['name']} (SN: {device['sn']}):",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Изменить имя", callback_data=f"edit_name_{device_id}")],
            [InlineKeyboardButton("Изменить SN", callback_data=f"edit_sn_{device_id}")],
            [InlineKeyboardButton("Удалить устройство", callback_data=f"delete_device_{device_id}")],
            [InlineKeyboardButton("Назад", callback_data="manage_devices")]
        ])
    )


# Добавление устройства
async def add_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Введите данные устройства в формате:\n"
        "Название Тип SN\n\nПример:\nDevice-1 Phone SN001",
        reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
    )
    context.user_data["awaiting_device_data"] = True


async def delete_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    device_id_text = update.message.text.strip()

    try:
        # Извлекаем ID устройства
        device_id = int(device_id_text.split("(ID:")[1].replace(")", "").strip())
    except (ValueError, IndexError):
        await update.message.reply_text("Ошибка: некорректный формат ID устройства.")
        return

    device = next((d for d in devices if d["id"] == device_id), None)

    if not device:
        await update.message.reply_text("Устройство не найдено.")
        return

    devices.remove(device)
    save_data("devices.json", devices)

    await update.message.reply_text(
        f"Устройство {device['name']} (SN: {device['sn']}) успешно удалено.",
        reply_markup=ReplyKeyboardMarkup([["Главное меню"]], resize_keyboard=True)
    )


# Обработка импорта устройств
async def import_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["action"] = "import_devices"
    await query.message.reply_text("Отправьте CSV файл с колонками: SN, Name, Type")


def load_logs(filename="device_logs.json"):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}  # Возвращает пустой словарь, если файл не найден

logs = load_logs()


# Просмотр истории бронирований устройства
async def view_device_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    device_name = update.message.text.replace("История", "").strip()
    device = next((d for d in devices if d["name"] == device_name), None)

    if not device:
        await update.message.reply_text("Устройство не найдено.")
        return

    device_sn = device["sn"]
    history = logs.get(device_sn, [])

    if not history:
        await update.message.reply_text(
            f"История устройства {device_name} (SN: {device_sn}) отсутствует.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
        )
        return

    # Форматируем историю
    history_text = "\n".join(
        f"{entry['timestamp']}: {entry['action']}" for entry in history
    )

    await update.message.reply_text(
        f"История устройства {device_name} (SN: {device_sn}):\n{history_text}",
        reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
    )



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


def log_action(device_sn, action):
    if device_sn not in logs:
        logs[device_sn] = []
    logs[device_sn].append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action
    })
    save_logs()


def save_logs(filename="device_logs.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=4)


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


async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await return_to_main_menu(update, context)


# Основная функция
def main():
    app = Application.builder().token(config["bot_token"]).build()

    scheduler.add_job(check_booking_expiration, "interval", minutes=5, kwargs={"application": app})
    scheduler.start()

    # Обработчики команд
    app.add_handler(CommandHandler("start", return_to_main_menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("register", register_user))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Назад$"), go_back))

    # Текстовые кнопки
    app.add_handler(MessageHandler(filters.TEXT & (filters.Regex("^Список устройств$")), list_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r".* - ID \d+$"), book_specific_device))
    app.add_handler(MessageHandler(filters.TEXT & (filters.Regex("^Бронирование$")), book_device))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^(Phone|Tablet|PC|RKBoard)$"), select_device))
    app.add_handler(MessageHandler(filters.TEXT & (filters.Regex("^Мои устройства$")), my_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Администрирование$"), admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & (filters.Regex("^Назад$")), go_back))
    app.add_handler(MessageHandler(filters.TEXT & (filters.Regex("^Главное меню")), return_to_main_menu))
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex("^Освободить все устройства$"), release_all_user_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Освободить .* \\(SN: .*\\)$"), release_device))

    # CallbackQueryHandlers для инлайн-кнопок
    app.add_handler(CallbackQueryHandler(admin_release_all_devices, pattern="admin_release_all_devices"))

    # Управление устройствами
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Управление устройствами$"), manage_devices))
    app.add_handler(CallbackQueryHandler(add_device, pattern="add_device"))
    app.add_handler(CallbackQueryHandler(import_devices, pattern="import_devices"))
    app.add_handler(MessageHandler(filters.Document.FileExtension("csv"), process_import_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Устройство:.*"), process_new_device))
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex("^Просмотр забронированных устройств$"), all_booked_devices))
    app.add_handler(CallbackQueryHandler(view_device_history, pattern="history_.*"))
    app.add_handler(CallbackQueryHandler(edit_device, pattern="edit_device_.*"))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^.* \\(SN: .*\\)$"), manage_selected_device))
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex("^Изменить имя устройства \\(ID: .*\\)$"), edit_device_name))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Удалить устройство \\(ID: .*\\)$"), delete_device))

    # Управление пользователями
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Включить регистрацию$"), toggle_registration))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Выключить регистрацию$"), toggle_registration))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Управление пользователями$"), manage_users))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Утвердить .*"), approve_user))
    app.add_handler(CallbackQueryHandler(reject_user, pattern="reject_user_.*"))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Список всех пользователей$"), view_all_users))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Добавить пользователя$"), add_user))
    app.add_handler(CallbackQueryHandler(edit_user, pattern="edit_user_.*"))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Удалить .*"), delete_user))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Пользователь:.*"), process_new_user))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Редактировать пользователя:.*"), process_edit_user))

    app.add_handler(CallbackQueryHandler(view_all_users, pattern="view_all_users"))
    app.add_handler(CallbackQueryHandler(manage_selected_user, pattern="user_.*"))
    app.add_handler(CallbackQueryHandler(delete_user, pattern="delete_user_.*"))
    app.add_handler(CallbackQueryHandler(user_devices, pattern="user_devices_.*"))

    # Обработчик для неизвестных сообщений должен быть последним
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    app.run_polling()

if __name__ == "__main__":
    main()
