from prettytable import PrettyTable  # Убедитесь, что библиотека установлена: pip install prettytable
from datetime import datetime, timedelta
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


def access_control(required_status="active", required_role=None):
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id
            user = next((u for u in users if u["user_id"] == user_id), None)

            if not user:
                await update.message.reply_text(
                    "Вы не зарегистрированы. Используйте /register для отправки заявки.",
                    reply_markup=ReplyKeyboardMarkup([["/help"]], resize_keyboard=True)
                )
                return

            if user["status"] != required_status:
                await update.message.reply_text(
                    f"Ваш статус: {user['status']}. Доступ разрешён только для пользователей со статусом: {required_status}.",
                    reply_markup=ReplyKeyboardMarkup([["/help"]], resize_keyboard=True)
                )
                return

            if required_role and user["role"] != required_role:
                await update.message.reply_text(
                    f"Доступ к этой функции разрешён только для пользователей с ролью: {required_role}.",
                    reply_markup=ReplyKeyboardMarkup([["/help"]], resize_keyboard=True)
                )
                return

            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator


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
@access_control(required_role="Admin")
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
            f"Утвердить {user['user_id']}",
            f"Удалить {user['user_id']}"
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
@access_control(required_role="Admin")
async def view_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "У вас нет доступа к списку пользователей.",
            reply_markup=ReplyKeyboardMarkup([["Главное меню"]], resize_keyboard=True)
        )
        return

    keyboard = [
        [InlineKeyboardButton(f"{user['first_name']} {user['last_name']} {user['user_id']} ({user['status']})", callback_data=f"user_{user['user_id']}")]
        for user in users
    ]
    keyboard.append([InlineKeyboardButton("Назад", callback_data="admin_panel")])

    await update.message.reply_text(
        "Список пользователей:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@access_control(required_role="Admin")
async def manage_selected_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Проверяем, соответствует ли `query.data` ожидаемому формату
    match = re.match(r"user_(\d+)", query.data)
    if not match:
        await query.message.reply_text("Ошибка: некорректные данные для выбора пользователя.")
        return

    # Извлекаем user_id из callback_data
    user_id = int(match.group(1))

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
        f"Управление пользователем:\nИмя: {selected_user['first_name']}\nФамилия: {selected_user['last_name']}\nСтатус: {selected_user['status']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# Обработка редактирования пользователя
@access_control(required_role="Admin")
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
@access_control(required_role="Admin")
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
        f"Пользователь {user['first_name']} {user['last_name']} удален.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="view_all_users")]])
    )


@access_control()
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
@access_control(required_role="Admin")
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
@access_control(required_role="Admin")
async def process_new_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_user_data"):
        return

    user_data = update.message.text.strip()
    try:
        # Разделяем введенный текст на части
        first_name, last_name, username = user_data.split()
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
        "first_name": first_name,
        "last_name": last_name,
        "username": username,
        "status": "approved"
    }
    users.append(new_user)
    save_data("users.json", users)

    # Подтверждение успешного добавления
    await update.message.reply_text(
        f"Пользователь {first_name} {last_name} ({username}) успешно добавлен.",
        reply_markup=ReplyKeyboardMarkup([["Главное меню"]], resize_keyboard=True)
    )
    context.user_data["awaiting_user_data"] = False


# Редактирование пользователя
@access_control(required_role="Admin")
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
@access_control(required_role="Admin")
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
@access_control(required_role="Admin")
async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query:
        await query.answer()  # Отвечаем на callback-запрос
        message_text = query.data
    else:
        # Если вызов был не через callback, используем текст сообщения
        message_text = update.message.text.strip()

    # Используем регулярное выражение для извлечения user_id
    match = re.match(r"Утвердить (\d+)", message_text)
    if not match:
        await update.message.reply_text("Ошибка обработки данных пользователя.")
        return

    user_id = int(match.group(1))  # Извлекаем user_id

    user = next((u for u in users if u["user_id"] == user_id), None)
    if not user:
        await update.message.reply_text("Пользователь не найден.")
        return

    # Обновляем статус пользователя на "active"
    user["status"] = "active"
    save_data("users.json", users)

    response_message = f"Пользователь {user['username']} успешно утвержден."
    if query:
        # Если вызов через callback, редактируем сообщение
        await query.edit_message_text(response_message)
    else:
        # Если вызов через текстовое сообщение, отправляем обычный ответ
        await update.message.reply_text(response_message)


# Отклонение заявки пользователя
@access_control(required_role="Admin")
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
@access_control()
async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Список устройств", "Бронирование"], ["Мои устройства"]]
    if is_admin(update.effective_user.id):
        keyboard.append(["Администрирование"])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Главное меню:", reply_markup=reply_markup)


@access_control()
async def list_devices(update: Update, context: ContextTypes.DEFAULT_TYPE, status="all", device_type=None):
    # Фильтрация устройств
    filtered_devices = devices
    if status != "all":
        filtered_devices = [device for device in devices if device["status"] == status]
    if device_type:
        filtered_devices = [device for device in filtered_devices if device["type"] == device_type]

    if not filtered_devices:
        await update.message.reply_text("Нет устройств для отображения.")
        return

    # Сортировка и группировка устройств
    grouped_devices = {}
    for device in filtered_devices:
        device_group = grouped_devices.setdefault(device["type"], [])
        device_group.append(device)

    # Создание таблицы
    response_message = "Список устройств:\n"
    for device_type, devices_group in sorted(grouped_devices.items()):
        table = PrettyTable()
        table.field_names = ["Название", "SN", "Статус", "Дата окончания брони", "Забронировано пользователем"]
        for device in devices_group:
            user_name = get_user_full_name(device.get("user_id")) if device.get("status") == "booked" else "-"
            booking_expiration = device.get("booking_expiration", "Не указано")
            if booking_expiration != "Не указано":
                booking_expiration = format_datetime(booking_expiration)

            table.add_row([
                device["name"],
                device["sn"],
                "Свободно" if device["status"] == "free" else "Забронировано",
                booking_expiration,
                user_name
            ])
        response_message += f"\n{device_type}:\n```\n{table}\n```\n"

    await update.message.reply_text(response_message, parse_mode="Markdown")


# Бронирование устройства
@access_control()
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


@access_control()
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
@access_control()
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
@access_control()
async def my_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Фильтруем устройства, забронированные текущим пользователем
    user_devices = [device for device in devices if device.get("user_id") == user_id]

    if not user_devices:
        await update.message.reply_text("У вас нет забронированных устройств.")
        return

    # Генерация кнопок для освобождения устройств
    reply_markup = ReplyKeyboardMarkup(
        [[f"Освободить {d['name']} (SN: {d['sn']})"] for d in user_devices] + [["Освободить все устройства"], ["Назад"]],
        resize_keyboard=True
    )
    # Создаём таблицу
    table = PrettyTable()
    table.field_names = ["Название", "SN", "Дата окончания брони"]
    for device in user_devices:
        table.add_row([
            device["name"],
            device["sn"],
            format_datetime(device["booking_expiration"])
        ])

    await update.message.reply_text(f"Ваши забронированные устройства:\n```\n{table}\n```", parse_mode="Markdown", reply_markup=reply_markup)


# Освободить устройство
@access_control()
async def release_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_role = get_user_role(user_id)

    # Определяем источник вызова (команда, сообщение или callback-кнопка)
    is_callback = hasattr(update, 'callback_query') and update.callback_query is not None
    command_source = update.callback_query if is_callback else update.message
    message_text = command_source.data if is_callback else command_source.text.strip()

    # Определяем контекст меню
    if is_callback and context.user_data.get("menu_context") != "admin_panel":
        menu_context = "admin_panel" if user_role == "Admin" else "user_devices"
    else:
        menu_context = context.user_data.get("menu_context", "user_devices")  # По умолчанию меню пользователя

    # Флаг освобождения всех устройств
    release_all = message_text == "release_all_devices" or message_text == "Освободить все устройства"

    # Освобождение всех устройств
    if release_all:
        devices_to_release = [
            device for device in devices
            if device["status"] == "booked" and
            (menu_context == "user_devices" and device["user_id"] == user_id or
             menu_context == "admin_panel" and user_role == "Admin")
        ]
    else:
        # Освобождение конкретного устройства
        if is_callback:
            # Получаем ID устройства из callback_data
            device_id = int(message_text.split("_")[1])
            devices_to_release = [
                device for device in devices
                if device["id"] == device_id and device["status"] == "booked" and
                (menu_context == "user_devices" and device["user_id"] == user_id or
                 menu_context == "admin_panel" and user_role == "Admin")
            ]
        else:
            # Для текстовых команд
            match = re.match(r"Освободить (.+?) \(SN: (.+?)\)", message_text)
            if not match:
                await command_source.reply_text(
                    "Ошибка: некорректный формат команды.",
                    reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
                )
                return
            device_name, device_sn = match.groups()
            devices_to_release = [
                device for device in devices
                if device["name"] == device_name and device["sn"] == device_sn and device["status"] == "booked" and
                (menu_context == "user_devices" and device["user_id"] == user_id or
                 menu_context == "admin_panel" and user_role == "Admin")
            ]

    if not devices_to_release:
        response_message = "Нет устройств для освобождения."
    else:
        # Освобождаем устройства
        for device in devices_to_release:
            device["status"] = "free"
            device.pop("user_id", None)
            device.pop("booking_expiration", None)
            log_action(device["sn"], f"Освобождено {'администратором' if user_role == 'Admin' else 'пользователем'} {get_user_full_name(user_id)}")

        save_data("devices.json", devices)

        response_message = (
            "Все устройства успешно освобождены."
            if release_all else
            f"Устройство {devices_to_release[0]['name']} (SN: {devices_to_release[0]['sn']}) успешно освобождено."
        )

    # Ответ пользователю
    if is_callback:
        await command_source.edit_message_text(response_message)
    else:
        await command_source.reply_text(
            response_message,
            reply_markup=ReplyKeyboardMarkup([["Главное меню"]], resize_keyboard=True)
        )

    # Возвращение к списку устройств, если вызов из меню администратора
    if menu_context == "admin_panel" and is_callback:
        await all_booked_devices(update, context)


# Панель администрирования
@access_control(required_role="Admin")
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
@access_control(required_role="Admin")
async def all_booked_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Определяем источник вызова
    is_callback = hasattr(update, 'callback_query') and update.callback_query is not None
    command_source = update.callback_query if is_callback else update.message

    # Фильтруем только забронированные устройства
    booked_devices = [device for device in devices if device["status"] == "booked"]

    if not booked_devices:
        response_message = "Нет забронированных устройств."
        if is_callback:
            await command_source.edit_message_text(response_message)
        else:
            await command_source.reply_text(response_message)
        return

    # Создаём таблицу
    table = PrettyTable()
    table.field_names = ["Название", "SN", "Дата окончания брони", "Забронировано пользователем"]
    for device in booked_devices:
        user_name = get_user_full_name(device.get("user_id"))
        booking_expiration = format_datetime(device.get("booking_expiration", "Не указано"))
        table.add_row([
            device["name"],
            device["sn"],
            booking_expiration,
            user_name
        ])

    # Формируем кнопки для освобождения устройств
    keyboard = [
        [InlineKeyboardButton(f"Освободить {device['name']} (SN: {device['sn']})", callback_data=f"release_{device['id']}")]
        for device in booked_devices
    ]
    keyboard.append([InlineKeyboardButton("Освободить все устройства", callback_data="release_all_devices")])
    keyboard.append([InlineKeyboardButton("Назад", callback_data="admin_panel")])

    response_message = f"Список забронированных устройств:\n```\n{table}\n```"
    if is_callback:
        await command_source.edit_message_text(
            response_message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await command_source.reply_text(
            response_message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )



@access_control(required_role="Admin")
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


@access_control(required_role="Admin")
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


@access_control(required_role="Admin")
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


@access_control(required_role="Admin")
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


@access_control(required_role="Admin")
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
@access_control(required_role="Admin")
async def add_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Введите данные устройства в формате:\n"
        "Название Тип SN\n\nПример:\nDevice-1 Phone SN001",
        reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
    )
    context.user_data["awaiting_device_data"] = True


@access_control(required_role="Admin")
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
@access_control(required_role="Admin")
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
@access_control(required_role="Admin")
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
@access_control(required_role="Admin")
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
@access_control(required_role="Admin")
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


def format_datetime(iso_datetime):
    if not iso_datetime:
        return "Не указано"
    dt = datetime.fromisoformat(iso_datetime)
    return dt.strftime("%d.%m.%Y %H:%M")

@access_control()
async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await return_to_main_menu(update, context)


# Основная функция
def main():
    app = Application.builder().token(config["bot_token"]).build()

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
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Освободить .* \\(SN: .*\\)$"), release_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Освободить все устройства$"), release_devices))
    app.add_handler(CallbackQueryHandler(release_devices, pattern="release_.*"))
    app.add_handler(CallbackQueryHandler(release_devices, pattern="release_all_devices"))

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
