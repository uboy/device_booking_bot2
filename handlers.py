from __future__ import annotations

import io
import csv
import re
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from telegram.ext import ContextTypes

import storage
import utils
from access_control import access_control, main_menu_keyboard
from libs.device_importer import load_devices_from_file
from states import BotState
import json
import base64
import binascii

# Импорт для OCR (опционально, если библиотека установлена)
try:
    import easyocr
    import numpy as np
    from PIL import Image
    OCR_AVAILABLE = True
    # Глобальный OCR reader (инициализируется один раз)
    _ocr_reader = None
    
    def _get_ocr_reader():
        """Получает или создает OCR reader (ленивая инициализация)."""
        global _ocr_reader
        if _ocr_reader is None:
            _ocr_reader = easyocr.Reader(['en', 'ru'], gpu=True)
        return _ocr_reader
except ImportError:
    OCR_AVAILABLE = False
    _ocr_reader = None


# ==========
# Служебное
# ==========

def _get_state(context: ContextTypes.DEFAULT_TYPE) -> BotState:
    return context.user_data.get("state", BotState.NONE)


def _set_state(context: ContextTypes.DEFAULT_TYPE, state: BotState) -> None:
    context.user_data["state"] = state


def _format_groups_list() -> str:
    if not storage.groups:
        return "— группы не созданы —"
    lines = []
    for g in sorted(storage.groups, key=lambda x: x.get("id", 0)):
        lines.append(f"{g.get('id')}: {g.get('name', 'Без названия')}")
    return "\n".join(lines)


def _group_label(group_id: Optional[int]) -> str:
    if not group_id:
        return "Без группы"
    group = utils.get_group_by_id(group_id)
    if not group:
        return f"Группа ID {group_id}"
    return f"{group.get('name', 'Без названия')} (ID: {group_id})"


def _group_label_short(group_id: Optional[int]) -> str:
    label = _group_label(group_id)
    return label if len(label) <= 20 else label[:17] + "..."


async def _notify_admins_about_registration(context: ContextTypes.DEFAULT_TYPE, user_data: Dict[str, Any]) -> None:
    """Отправить уведомление администраторам о новой заявке."""
    admin_ids = storage.config.get("admin_ids", [])
    if not admin_ids:
        return
    text = (
        "🆕 Новая заявка на регистрацию\n"
        f"🆔 ID: {user_data.get('user_id')}\n"
        f"👤 {user_data.get('first_name', '')} {user_data.get('last_name', '')}\n"
        f"📛 username: @{user_data.get('username', 'N/A')}\n"
        f"👥 Группа ID: {user_data.get('group_id')}"
    )
    for admin_id in admin_ids:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            continue


# ==========
# Команды /help, /start, /register
# ==========

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/start - Главное меню\n"
        "/help - Справка\n"
        "/register - Отправить заявку на регистрацию\n"
        "/set_name Имя Фамилия - Установить отображаемое имя\n"
        "\nОсновные кнопки в меню зависят от вашей роли."
    )


@access_control()
async def set_name_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Позволяет пользователю задать отображаемое имя."""
    user_id = update.effective_user.id
    user = utils.get_user_by_id(user_id)
    if not user:
        await update.message.reply_text("Вы не зарегистрированы. Сначала отправьте /register.")
        return
    name_text = update.message.text.replace("/set_name", "", 1).strip()
    if not name_text:
        await update.message.reply_text("Используйте формат: /set_name Имя Фамилия")
        return
    user["display_name"] = name_text
    storage.save_users()
    await update.message.reply_text(f"Отображаемое имя обновлено: {name_text}")


@access_control(required_status=None, allow_unregistered=True)
async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_user = utils.get_user_by_id(user_id)
    _set_state(context, BotState.NONE)
    context.user_data.pop("scanning_mode", None)  # Выход из режима сканирования
    context.user_data.pop("pending_registration", None)
    if not db_user:
        await update.message.reply_text(
            f"Ваш Telegram ID: `{user_id}`\n"
            "Вы не зарегистрированы. Используйте /register для отправки заявки или /help для справки.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([["/register", "/help"]], resize_keyboard=True),
        )
        return
    await update.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard(user_id))


@access_control(required_status=None, allow_unregistered=True)
async def start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_user = utils.get_user_by_id(user_id)
    _set_state(context, BotState.NONE)
    context.user_data.pop("pending_registration", None)

    if not db_user:
        await update.message.reply_text(
            f"Ваш Telegram ID: `{user_id}`\n"
            "Вы не зарегистрированы. Используйте /register для отправки заявки или /help для справки.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([["/register", "/help"]], resize_keyboard=True),
        )
        return

    await update.message.reply_text(
        f"Главное меню (ваш ID: `{user_id}`):\n\n"
        "💡 Вы также можете ввести текст для поиска устройств\n"
        "(модель, название, тип, серийный номер)",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(user_id)
    )

    webapp_url = storage.config.get("webapp_url") or ""
    if webapp_url:
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Открыть WebApp", web_app=WebAppInfo(url=webapp_url))]]
        )
        await update.message.reply_text("Дополнительно:", reply_markup=kb)


async def register_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not storage.config.get("registration_enabled", False):
        await update.message.reply_text("Регистрация временно отключена.")
        return

    tg_user = update.effective_user
    user_id = tg_user.id

    if any(u.get("user_id") == user_id for u in storage.users):
        await update.message.reply_text(
            "Вы уже зарегистрированы или ваша заявка ожидает рассмотрения."
        )
        return

    if not storage.groups:
        await update.message.reply_text(
            "Регистрация временно недоступна. Администратор еще не создал ни одной группы."
        )
        return

    context.user_data.pop("pending_registration", None)
    context.user_data["pending_registration"] = {
        "user_id": user_id,
        "username": tg_user.username or "Не указано",
        "first_name": tg_user.first_name or "Не указано",
        "last_name": tg_user.last_name or "Не указано",
        "role": "User",
        "status": "pending",
    }
    _set_state(context, BotState.SELECTING_REG_GROUP)

    inline_buttons = []
    for group in sorted(storage.groups, key=lambda g: g.get("id", 0)):
        group_id = group.get("id")
        inline_buttons.append([
            InlineKeyboardButton(
                f"{group.get('name', 'Без названия')} (ID: {group_id})",
                callback_data=f"reg_group_{group_id}"
            )
        ])

    await update.message.reply_text(
        "Выберите группу, в которой хотите зарегистрироваться. "
        "После подтверждения администратором вы получите доступ к устройствам этой группы.",
        reply_markup=InlineKeyboardMarkup(inline_buttons),
    )


@access_control(required_status=None, allow_unregistered=True)
async def register_group_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор группы пользователем при регистрации."""
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("reg_group_"):
        return

    await query.answer()

    state = _get_state(context)
    if state != BotState.SELECTING_REG_GROUP:
        await query.edit_message_text(
            "Эта заявка устарела. Отправьте /register, чтобы начать заново."
        )
        return

    pending = context.user_data.get("pending_registration")
    if not pending or pending.get("user_id") != query.from_user.id:
        _set_state(context, BotState.NONE)
        context.user_data.pop("pending_registration", None)
        await query.edit_message_text(
            "Данные не найдены. Отправьте /register, чтобы начать регистрацию заново."
        )
        return

    if any(u.get("user_id") == pending["user_id"] for u in storage.users):
        _set_state(context, BotState.NONE)
        context.user_data.pop("pending_registration", None)
        await query.edit_message_text("Вы уже подали заявку или зарегистрированы.")
        return

    match = re.match(r"reg_group_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Некорректный формат выбора группы.")
        return

    group_id = int(match.group(1))
    group = utils.get_group_by_id(group_id)
    if not group:
        await query.edit_message_text("Выбранная группа не найдена. Попробуйте еще раз.")
        return

    storage.users.append(
        {
            "user_id": pending["user_id"],
            "username": pending.get("username"),
            "first_name": pending.get("first_name"),
            "last_name": pending.get("last_name"),
            "role": pending.get("role", "User"),
            "status": pending.get("status", "pending"),
            "group_id": group_id,
        }
    )
    storage.save_users()

    # Уведомляем админов
    await _notify_admins_about_registration(context, storage.users[-1])

    _set_state(context, BotState.NONE)
    context.user_data.pop("pending_registration", None)

        await query.edit_message_text(
            f"✅ Заявка отправлена.\nГруппа: {group.get('name', 'Без названия')}.\n"
            "Как только администратор подтвердит регистрацию, вы получите доступ к устройствам."
        )
    await _notify_admins_about_registration(context, storage.users[-1])


@access_control(required_role="Admin")
async def toggle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает режим регистрации. Работает и из сообщений, и из callback."""
    query = update.callback_query
    msg = query.message if query else update.message

    storage.config["registration_enabled"] = not storage.config.get("registration_enabled", False)
    storage.save_config()
    state_text = "включена" if storage.config["registration_enabled"] else "выключена"

    if query:
        await query.answer(f"Регистрация {state_text}")
        # не затираем меню, отправляем отдельным сообщением
        await msg.reply_text(f"Регистрация сейчас: {state_text}")
    else:
        await msg.reply_text(f"Регистрация сейчас: {state_text}")


# ==========
# Устройства – список / бронирование / мои / освобождение
# ==========

def _search_devices_by_text(search_text: str) -> List[Dict[str, Any]]:
    """Поиск устройств по тексту (модель, название, тип, серийный номер)."""
    search_text = search_text.strip().upper()
    if not search_text or len(search_text) < 2:
        return []
    
    results = []
    for device in storage.devices:
        # Поиск в названии
        if search_text in device.get("name", "").upper():
            results.append(device)
            continue
        # Поиск в типе
        if search_text in device.get("type", "").upper():
            results.append(device)
            continue
        # Поиск в серийном номере
        if search_text in device.get("sn", "").upper():
            results.append(device)
            continue
    
    return results


@access_control()
async def search_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск устройств по введенному тексту."""
    utils.cleanup_expired_bookings()
    
    search_text = update.message.text.strip()
    if len(search_text) < 2:
        await update.message.reply_text(
            "Введите минимум 2 символа для поиска.",
            reply_markup=main_menu_keyboard(update.effective_user.id)
        )
        return
    
    all_devices = _search_devices_by_text(search_text)
    
    # Фильтруем устройства по группе пользователя
    user_id = update.effective_user.id
    is_admin = utils.is_admin(user_id)
    devices = utils.filter_devices_by_user_group(user_id, all_devices)
    
    if not devices:
        await update.message.reply_text(
            f"❌ По запросу '{search_text}' ничего не найдено в вашей группе.\n\n"
            "Попробуйте другой запрос или используйте меню.",
            reply_markup=main_menu_keyboard(update.effective_user.id)
        )
        return
    
    # Показываем найденные устройства с кнопками
    lines = [f"🔍 Найдено устройств: {len(devices)}\n"]
    inline_buttons = []
    
    for device in devices:
        device_status = device.get("status", "free")
        device_user_id = device.get("user_id")
        sn = device.get("sn", "N/A")
        name = device.get("name", "Неизвестно")
        dev_type = device.get("type", "Неизвестно")
        group_name = _group_label(device.get("group_id"))
        
        status_emoji = "✅" if device_status == "free" else "🔒"
        lines.append(f"{status_emoji} **{name}** ({dev_type}) - SN: `{sn}` — 👥 {group_name}")
        
        if device_status == "free":
            row = [
                InlineKeyboardButton(
                    f"✅ {name} (SN: {sn})",
                    callback_data=f"book_dev_{device['id']}"
                )
            ]
            if is_admin:
                row.append(
                    InlineKeyboardButton(
                        "👑 На пользователя",
                        callback_data=f"admin_book_dev_{device['id']}",
                    )
                )
            inline_buttons.append(row)
        elif device_user_id == user_id:
            expiration = utils.format_datetime(device.get("booking_expiration"))
            inline_buttons.append([
                InlineKeyboardButton(
                    f"🔓 {name} (SN: {sn}) - Освободить",
                    callback_data=f"release_dev_{device['id']}"
                )
            ])
    
    text = "\n".join(lines)
    inline_buttons.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_to_main")])
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_buttons) if inline_buttons else None,
    )


@access_control()
async def list_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает типы устройств для выбора (фильтрованные по группе пользователя)."""
    utils.cleanup_expired_bookings()
    user_id = update.effective_user.id
    is_admin = utils.is_admin(user_id)
    
    # Фильтруем устройства по группе пользователя
    available_devices = utils.filter_devices_by_user_group(user_id, storage.devices)
    
    if not available_devices:
        user_group = utils.get_user_group(user_id)
        if not user_group:
            await update.message.reply_text(
                "❌ У вас не назначена группа. Обратитесь к администратору для назначения группы."
            )
        else:
            await update.message.reply_text("Нет устройств для отображения в вашей группе.")
        return

    # Группируем устройства по типам
    types = sorted(set(d.get("type", "Неизвестно") for d in available_devices))
    
    inline_buttons = []
    for dev_type in types:
        count = len([d for d in available_devices if d.get("type") == dev_type])
        inline_buttons.append([InlineKeyboardButton(f"📦 {dev_type} ({count})", callback_data=f"type_{dev_type}")])
    
    await update.message.reply_text(
        "📱 Выберите тип устройства:",
        reply_markup=InlineKeyboardMarkup(inline_buttons),
    )
    _set_state(context, BotState.VIEWING_DEVICE_MODELS)


@access_control()
async def book_device_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utils.cleanup_expired_bookings()
    user_id = update.effective_user.id
    available_devices = [
        d for d in utils.filter_devices_by_user_group(user_id, storage.devices)
        if d.get("status") == "free"
    ]
    if not available_devices:
        await update.message.reply_text("Нет доступных устройств для бронирования в вашей группе.")
        return
    types_available = sorted({d.get("type", "Неизвестно") for d in available_devices})

    kb = [[t] for t in types_available]
    kb.append(["Назад"])
    await update.message.reply_text(
        "Выберите тип устройства для бронирования:",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True),
    )


@access_control()
async def select_device_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает модели выбранного типа с кнопками действий (фильтрованные по группе пользователя)."""
    utils.cleanup_expired_bookings()
    text = update.message.text.strip()
    user_id = update.effective_user.id
    is_admin = utils.is_admin(user_id)
    
    # Убираем эмодзи и количество, если есть
    dev_type = re.sub(r'^📦\s*', '', text)
    dev_type = re.sub(r'\s*\(\d+\)$', '', dev_type).strip()
    
    # Получаем все устройства этого типа и фильтруем по группе пользователя
    all_devices = [d for d in storage.devices if d.get("type") == dev_type]
    devices = utils.filter_devices_by_user_group(user_id, all_devices)
    
    if not devices:
        await update.message.reply_text(
            f"Нет устройств типа {dev_type}.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True),
        )
        return

    # Группируем по моделям (name)
    models = {}
    for d in devices:
        model_name = d.get("name", "Неизвестно")
        if model_name not in models:
            models[model_name] = []
        models[model_name].append(d)
    
    # Формируем сообщение с моделями и кнопками
    lines = []
    inline_buttons = []
    
    for model_name in sorted(models.keys()):
        model_devices = models[model_name]
        free_count = len([d for d in model_devices if d.get("status") == "free"])
        total_count = len(model_devices)
        
        status_text = f"✅ {free_count}/{total_count} свободно" if free_count > 0 else "🔒 Все забронированы"
        lines.append(f"📱 **{model_name}** - {status_text}")
        
        # Добавляем кнопки для каждого устройства этой модели
        for device in sorted(model_devices, key=lambda x: x.get("sn", "")):
            device_status = device.get("status", "free")
            device_user_id = device.get("user_id")
            sn = device.get("sn", "N/A")
            group_name = _group_label(device.get("group_id"))
            
            if device_status == "free":
                # Кнопка забронировать
                row = [
                    InlineKeyboardButton(
                        f"✅ {model_name} (SN: {sn})",
                        callback_data=f"book_dev_{device['id']}"
                    )
                ]
                if is_admin:
                    row.append(
                        InlineKeyboardButton(
                            "👑 На пользователя",
                            callback_data=f"admin_book_dev_{device['id']}",
                        )
                    )
                inline_buttons.append(row)
            elif device_user_id == user_id:
                # Кнопка освободить (если забронировано пользователем)
                expiration = utils.format_datetime(device.get("booking_expiration"))
                inline_buttons.append([
                    InlineKeyboardButton(
                        f"🔓 {model_name} (SN: {sn}) - Освободить",
                        callback_data=f"release_dev_{device['id']}"
                    )
                ])
            else:
                # Устройство забронировано другим - показываем информацию
                other_user = utils.get_user_full_name(device_user_id)
                expiration = utils.format_datetime(device.get("booking_expiration"))
                inline_buttons.append([
                    InlineKeyboardButton(
                        f"🔒 {model_name} (SN: {sn}) - Забронировано",
                        callback_data=f"info_dev_{device['id']}"
                    )
                ])
    
    text = f"📦 **{dev_type}**\n\n" + "\n".join(lines)
    
    if inline_buttons:
        inline_buttons.append([InlineKeyboardButton("◀️ Назад к типам", callback_data="back_to_types")])
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_buttons),
        )
    else:
        await update.message.reply_text(
            text + "\n\nНет доступных действий.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True),
        )


@access_control()
async def book_specific_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utils.cleanup_expired_bookings()
    text = update.message.text.strip()
    
    # Проверяем, не является ли это выбором устройства при сканировании
    scanning_mode = context.user_data.get("scanning_mode", False)
    if scanning_mode and "📱" in text:
        # Убираем эмодзи для парсинга
        text = text.replace("📱 ", "").strip()
    
    try:
        device_id = int(text.split(" - ID ")[-1])
    except (ValueError, IndexError):
        await update.message.reply_text(
            "Ошибка: некорректный формат выбора устройства.",
            reply_markup=ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True),
        )
        return

    device = next((d for d in storage.devices if d.get("id") == device_id), None)
    if not device:
        await update.message.reply_text("Ошибка: устройство не найдено.")
        return
    
    # Если в режиме сканирования, обрабатываем все сценарии
    if scanning_mode:
        user_id = update.effective_user.id
        await _handle_device_found(update, context, device, user_id, message_for_reply=update.message)
        return

    # Обычная логика бронирования (только свободные устройства)
    if device.get("status") != "free":
        await update.message.reply_text("Ошибка: устройство не найдено или уже забронировано.")
        return

    user_id = update.effective_user.id
    
    # Проверка принадлежности к группе (для не-админов)
    if not utils.is_admin(user_id):
        if not utils.can_user_book_device(user_id, device_id):
            user_group = utils.get_user_group(user_id)
            device_group = utils.get_device_group(device_id)
            if not user_group:
                await update.message.reply_text(
                    "❌ У вас не назначена группа. Обратитесь к администратору."
                )
            elif not device_group:
                await update.message.reply_text(
                    "❌ Устройство не назначено ни в какую группу."
                )
            else:
                await update.message.reply_text(
                    f"❌ Вы не можете бронировать устройства из группы '{device_group.get('name')}'. "
                    f"Ваша группа: '{user_group.get('name')}'."
                )
            return
    
    # лимит устройств
    max_devices = storage.config.get("max_devices_per_user", 2)
    current_count = len([d for d in storage.devices if d.get("user_id") == user_id and d.get("status") == "booked"])
    if current_count >= max_devices:
        await update.message.reply_text(
            f"Нельзя забронировать больше {max_devices} устройств одновременно."
        )
        return

    default_days = device.get(
        "default_booking_period",
        storage.config.get("default_booking_period_days", 1),
    )
    now = datetime.now()
    expiration = now + timedelta(days=default_days)

    device["status"] = "booked"
    device["user_id"] = user_id
    device["booking_expiration"] = expiration.isoformat()
    storage.save_devices()

    await update.message.reply_text(
        f"Устройство {device['name']} (SN: {device['sn']}) "
        f"забронировано до {expiration.strftime('%Y-%m-%d %H:%M:%S')}."
    )

    utils.log_action(
        device["sn"],
        f"Забронировано пользователем {utils.get_user_full_name(user_id)} "
        f"до {expiration.strftime('%Y-%m-%d %H:%M:%S')}.",
    )

    # уведомление перед окончанием брони
    notify_before = storage.config.get("notify_before_minutes", 60)
    delta = expiration - datetime.now() - timedelta(minutes=notify_before)
    if delta.total_seconds() > 0:
        context.application.job_queue.run_once(
            notify_booking_expiring,
            when=delta,
            data={
                "chat_id": update.effective_chat.id,
                "device_name": device["name"],
                "sn": device["sn"],
                "expiration": expiration.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )


async def notify_booking_expiring(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    await context.bot.send_message(
        chat_id=data["chat_id"],
        text=(
            f"Напоминание: срок бронирования устройства {data['device_name']} "
            f"(SN: {data['sn']}) скоро истечёт.\n"
            f"Дата окончания: {data['expiration']}"
        ),
    )


@access_control()
async def my_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utils.cleanup_expired_bookings()
    user_id = update.effective_user.id
    my_devs = utils.get_user_devices(user_id)

    if not my_devs:
        await update.message.reply_text("У вас нет забронированных устройств.")
        return

    # Используем мобильный формат для лучшего отображения
    lines = []
    for d in my_devs:
        expiration = utils.format_datetime(d.get("booking_expiration"))
        device_info = (
            f"🔒 **{d['name']}**\n"
            f"🔢 SN: `{d['sn']}`\n"
            f"📅 До: {expiration}"
        )
        lines.append(device_info)

    text = "\n\n".join(lines)

    kb = [[f"Освободить {d['name']} (SN: {d['sn']})"] for d in my_devs]
    kb.append(["Освободить все устройства"])
    kb.append(["Назад"])

    await update.message.reply_text(
        f"📱 **Ваши устройства** ({len(my_devs)} шт.):\n\n{text}",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True),
    )


@access_control()
async def release_device_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Освобождение одного устройства пользователем по тексту 'Освободить ...'."""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    match = re.match(r"Освободить (.+?) \(SN: (.+?)\)", text)
    if not match:
        await update.message.reply_text("Ошибка: некорректный формат.")
        return
    name, sn = match.groups()

    dev = next(
        (
            d
            for d in storage.devices
            if d.get("name") == name
            and d.get("sn") == sn
            and d.get("user_id") == user_id
            and d.get("status") == "booked"
        ),
        None,
    )
    if not dev:
        await update.message.reply_text("Устройство не найдено среди ваших бронирований.")
        return

    dev["status"] = "free"
    dev.pop("user_id", None)
    dev.pop("booking_expiration", None)
    storage.save_devices()

    utils.log_action(dev["sn"], f"Освобождено пользователем {utils.get_user_full_name(user_id)}")

    await update.message.reply_text(
        f"Устройство {dev['name']} (SN: {dev['sn']}) успешно освобождено.",
        reply_markup=main_menu_keyboard(user_id),
    )


@access_control()
async def release_all_user_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    any_released = False
    for d in storage.devices:
        if d.get("user_id") == user_id and d.get("status") == "booked":
            d["status"] = "free"
            d.pop("user_id", None)
            d.pop("booking_expiration", None)
            utils.log_action(d["sn"], f"Освобождено пользователем {utils.get_user_full_name(user_id)}")
            any_released = True

    if any_released:
        storage.save_devices()
        await update.message.reply_text(
            "Все ваши устройства освобождены.",
            reply_markup=main_menu_keyboard(user_id),
        )
    else:
        await update.message.reply_text(
            "У вас нет забронированных устройств.",
            reply_markup=main_menu_keyboard(user_id),
        )


# ==========
# Админ-панель, просмотр забронированных
# ==========

@access_control(required_role="Admin")
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = update.callback_query
    if query:
        await query.answer()
        msg = query.message
    else:
        msg = update.message
    if msg is None:
        # fallback для случаев, когда message отсутствует (например, callback без message)
        await context.bot.send_message(chat_id=user_id, text="⚙️ Открываю меню администратора...")
        # получаем объект сообщения для дальнейших ответов
        msg = await context.bot.send_message(chat_id=user_id, text=" ")
    
    # Используем inline кнопки для лучшего UX
    inline_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Управление устройствами", callback_data="manage_devices_admin")],
        [InlineKeyboardButton("👥 Управление пользователями", callback_data="manage_users_admin")],
        [InlineKeyboardButton("👥 Управление группами", callback_data="manage_groups_admin")],
        [InlineKeyboardButton("🔒 Забронированные устройства", callback_data="view_booked_admin")],
        [
            InlineKeyboardButton("📥 Экспорт устройств", callback_data="export_devices_admin"),
            InlineKeyboardButton("📥 Экспорт пользователей", callback_data="export_users_admin")
        ],
        [InlineKeyboardButton("📥 Экспорт логов", callback_data="export_logs_admin")],
        [InlineKeyboardButton(
            f"🔄 Регистрация: {'Вкл' if storage.config.get('registration_enabled') else 'Выкл'}",
            callback_data="toggle_registration"
        )],
        [InlineKeyboardButton("📥 Импорт устройств", callback_data="import_devices_admin")],
    ])
    
    # Также оставляем текстовые кнопки для совместимости
    kb = [
        ["Управление устройствами", "Управление пользователями"],
        ["Управление группами"],
        ["Просмотр забронированных устройств"],
        ["Экспорт устройств CSV", "Экспорт пользователей CSV"],
        ["Экспорт логов CSV"],
        ["Включить регистрацию", "Выключить регистрацию"],
        ["Импортировать устройства"],
        ["Назад"],
    ]
    
    await msg.reply_text(
        "👑 **Меню администратора**",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True),
    )
    
    await msg.reply_text(
        "Или используйте кнопки:",
        reply_markup=inline_kb,
    )


async def manage_devices_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню управления устройствами (для callback)."""
    query = update.callback_query
    if query:
        await query.answer()
        msg = query.message
    else:
        msg = update.message
    
    utils.cleanup_expired_bookings()
    
    if not storage.devices:
        kb = [
            [InlineKeyboardButton("➕ Добавить устройство", callback_data="add_device")],
            [InlineKeyboardButton("📥 Импорт устройств", callback_data="import_devices_admin")],
        ]
        if query:
            await query.edit_message_text(
                "📋 Пока нет устройств.",
                reply_markup=InlineKeyboardMarkup(kb),
            )
        else:
            await msg.reply_text(
                "📋 Пока нет устройств.",
                reply_markup=InlineKeyboardMarkup(kb),
            )
        return
    
    # Показываем устройства с кнопками
    lines = []
    inline_buttons = []
    
    grouped = {}
    for device in sorted(storage.devices, key=lambda x: x.get("id", 0)):
        gkey = device.get("group_id") or 0
        grouped.setdefault(gkey, []).append(device)

    for gkey, devices in grouped.items():
        lines.append(f"👥 {_group_label(gkey if gkey != 0 else None)}")
        for device in devices:
            status_emoji = "✅" if device.get("status") == "free" else "🔒"
            device_info = (
                f"{status_emoji} **{device.get('name', 'Неизвестно')}**\n"
                f"🆔 ID: {device.get('id')} | 📦 {device.get('type', 'Неизвестно')} | 🔢 SN: `{device.get('sn', 'N/A')}`\n"
                f"📊 Статус: {'Свободно' if device.get('status') == 'free' else 'Забронировано'}"
            )
            lines.append(device_info)
            
            inline_buttons.append([
                InlineKeyboardButton(f"✏️ Изменить {device['id']}", callback_data=f"edit_device_{device['id']}"),
                InlineKeyboardButton(f"🗑️ Удалить {device['id']}", callback_data=f"delete_device_{device['id']}")
            ])
        lines.append("")
    
    text = f"📋 **Все устройства** ({len(storage.devices)} шт.)\n\n" + "\n\n".join(lines)
    inline_buttons.append([InlineKeyboardButton("➕ Добавить устройство", callback_data="add_device")])
    inline_buttons.append([InlineKeyboardButton("📥 Импорт устройств", callback_data="import_devices_admin")])
    
    if query:
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_buttons),
        )
    else:
        await msg.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_buttons),
        )


async def manage_devices_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback для управления устройствами - показывает выбор типов устройств."""
    query = update.callback_query
    if query:
        await query.answer()
    
    utils.cleanup_expired_bookings()
    
    if not storage.devices:
        kb = [
            [InlineKeyboardButton("➕ Добавить устройство", callback_data="add_device")],
            [InlineKeyboardButton("📥 Импорт устройств", callback_data="import_devices_admin")],
        ]
        if query:
            await query.edit_message_text(
                "📋 Пока нет устройств.",
                reply_markup=InlineKeyboardMarkup(kb),
            )
        else:
            await update.message.reply_text(
                "📋 Пока нет устройств.",
                reply_markup=InlineKeyboardMarkup(kb),
            )
        return
    
    # Группируем устройства по типам
    types = {}
    for device in storage.devices:
        dev_type = device.get("type", "Неизвестно")
        if dev_type not in types:
            types[dev_type] = 0
        types[dev_type] += 1
    
    # Создаем кнопки для каждого типа
    inline_buttons = []
    for dev_type in sorted(types.keys()):
        count = types[dev_type]
        inline_buttons.append([
            InlineKeyboardButton(
                f"📦 {dev_type} ({count})",
                callback_data=f"admin_type_{dev_type}"
            )
        ])
    
    # Добавляем кнопку "Все устройства"
    inline_buttons.append([
        InlineKeyboardButton(
            f"📋 Все устройства ({len(storage.devices)})",
            callback_data="admin_all_devices"
        )
    ])
    inline_buttons.append([InlineKeyboardButton("📥 Импорт устройств", callback_data="import_devices_admin")])
    
    # Кнопка добавления устройства
    inline_buttons.append([
        InlineKeyboardButton("➕ Добавить устройство", callback_data="add_device")
    ])
    
    # Кнопка назад в админ-панель
    inline_buttons.append([
        InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin")
    ])
    
    text = "📋 **Управление устройствами**\n\nВыберите тип устройств для управления:"
    
    if query:
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_buttons),
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_buttons),
        )


async def manage_users_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback для управления пользователями."""
    query = update.callback_query
    await query.answer()
    await manage_users_callback(update, context)


async def view_booked_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback для просмотра забронированных устройств."""
    query = update.callback_query
    await query.answer()
    
    utils.cleanup_expired_bookings()
    booked = [d for d in storage.devices if d.get("status") == "booked"]
    if not booked:
        await query.edit_message_text("Нет забронированных устройств.")
        return

    # Формируем список с кнопками
    lines = []
    inline_buttons = []
    
    for device in sorted(booked, key=lambda x: x.get("id", 0)):
        user_id = device.get("user_id")
        user_name = utils.get_user_full_name(user_id) if user_id else "Неизвестно"
        expiration = utils.format_datetime(device.get("booking_expiration"))
        
        device_info = (
            f"🔒 **{device.get('name', 'Неизвестно')}**\n"
            f"🆔 ID: {device.get('id')} | 📦 {device.get('type', 'Неизвестно')} | 🔢 SN: `{device.get('sn', 'N/A')}`\n"
            f"👤 Пользователь: {user_name}\n"
            f"📅 До: {expiration}"
        )
        lines.append(device_info)
        
        inline_buttons.append([
            InlineKeyboardButton(f"🔓 Освободить {device['id']}", callback_data=f"adm_rel_{device['id']}")
        ])
    
    text = f"🔒 **Забронированные устройства** ({len(booked)} шт.)\n\n" + "\n\n".join(lines)
    inline_buttons.append([InlineKeyboardButton("🔓 Освободить все", callback_data="adm_rel_all")])
    inline_buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin")])
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_buttons),
    )


@access_control(required_role="Admin")
async def view_all_booked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает забронированные устройства с кнопками."""
    utils.cleanup_expired_bookings()
    booked = [d for d in storage.devices if d.get("status") == "booked"]
    if not booked:
        await update.message.reply_text("Нет забронированных устройств.")
        return

    # Формируем список с кнопками
    lines = []
    inline_buttons = []
    
    for device in sorted(booked, key=lambda x: x.get("id", 0)):
        user_id = device.get("user_id")
        user_name = utils.get_user_full_name(user_id) if user_id else "Неизвестно"
        expiration = utils.format_datetime(device.get("booking_expiration"))
        
        device_info = (
            f"🔒 **{device.get('name', 'Неизвестно')}**\n"
            f"🆔 ID: {device.get('id')} | 📦 {device.get('type', 'Неизвестно')} | 🔢 SN: `{device.get('sn', 'N/A')}`\n"
            f"👤 Пользователь: {user_name}\n"
            f"📅 До: {expiration}"
        )
        lines.append(device_info)
        
        inline_buttons.append([
            InlineKeyboardButton(f"🔓 Освободить {device['id']}", callback_data=f"adm_rel_{device['id']}")
        ])
    
    text = f"🔒 **Забронированные устройства** ({len(booked)} шт.)\n\n" + "\n\n".join(lines)
    inline_buttons.append([InlineKeyboardButton("🔓 Освободить все", callback_data="adm_rel_all")])
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_buttons),
    )


@access_control(required_role="Admin")
async def admin_release_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "adm_rel_all":
        released = False
        for d in storage.devices:
            if d.get("status") == "booked":
                d["status"] = "free"
                d.pop("user_id", None)
                d.pop("booking_expiration", None)
                utils.log_action(d["sn"], "Освобождено администратором (массово)")
                released = True
        if released:
            storage.save_devices()
            await query.edit_message_text("Все устройства освобождены.")
        else:
            await query.edit_message_text("Нет забронированных устройств.")
        return

    match = re.match(r"adm_rel_(\d+)", data)
    if not match:
        await query.edit_message_text("Некорректный формат команды.")
        return

    dev_id = int(match.group(1))
    dev = next((d for d in storage.devices if d.get("id") == dev_id and d.get("status") == "booked"), None)
    if not dev:
        await query.edit_message_text("Устройство уже освобождено или не найдено.")
        return

    dev["status"] = "free"
    dev.pop("user_id", None)
    dev.pop("booking_expiration", None)
    storage.save_devices()
    utils.log_action(dev["sn"], "Освобождено администратором")

    await query.edit_message_text(
        f"Устройство {dev['name']} (SN: {dev['sn']}) освобождено администратором."
    )


# ==========
# Управление устройствами (админ) + FSM добавления
# ==========

@access_control(required_role="Admin")
async def manage_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление устройствами - вызывает manage_devices_admin_callback."""
    # Используем новую логику с выбором типов
    await manage_devices_admin_callback(update, context)


@access_control(required_role="Admin")
async def admin_devices_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == "add":
        if not storage.groups:
            await update.message.reply_text(
                "❌ Сначала создайте хотя бы одну группу в разделе 'Управление группами'."
            )
            return
        context.user_data["new_device_data"] = {}
        _set_state(context, BotState.ADDING_DEVICE_NAME)
        await update.message.reply_text(
            "➕ **Добавление устройства**\n\n"
            "Введите название устройства:",
            parse_mode="Markdown"
        )
        return

    # del ID
    match_del = re.match(r"del\s+(\d+)", text, re.IGNORECASE)
    if match_del:
        dev_id = int(match_del.group(1))
        dev = next((d for d in storage.devices if d.get("id") == dev_id), None)
        if not dev:
            await update.message.reply_text("Устройство не найдено.")
            return
        storage.devices.remove(dev)
        storage.save_devices()
        await update.message.reply_text(f"Устройство {dev['name']} (SN: {dev['sn']}) удалено.")
        return

    # rename ID new name
    match_ren = re.match(r"rename\s+(\d+)\s+(.+)", text, re.IGNORECASE)
    if match_ren:
        dev_id = int(match_ren.group(1))
        new_name = match_ren.group(2).strip()
        dev = next((d for d in storage.devices if d.get("id") == dev_id), None)
        if not dev:
            await update.message.reply_text("Устройство не найдено.")
            return
        old = dev["name"]
        dev["name"] = new_name
        storage.save_devices()
        await update.message.reply_text(f"Имя устройства изменено: {old} → {new_name}")
        return

    await update.message.reply_text("Неизвестная команда управления устройствами.")


@access_control(required_role="Admin")
async def handle_state_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик сообщений с учетом FSM."""
    state = _get_state(context)
    
    # Если состояние NONE, не обрабатываем - пусть сообщение пройдет дальше к unknown_message для поиска
    if state == BotState.NONE:
        # Возвращаемся без обработки, чтобы сообщение могло пройти к следующему обработчику
        # Но в python-telegram-bot это не работает так - нужно использовать другой подход
        # Вместо этого, просто не обрабатываем и позволяем пройти дальше через исключение или другой механизм
        return
    
    text = update.message.text.strip()

    if state == BotState.ADDING_DEVICE_NAME:
        device_name = text.strip()
        if len(device_name) < 2:
            await update.message.reply_text("Название устройства должно содержать минимум 2 символа.")
            return
        context.user_data.setdefault("new_device_data", {})["name"] = device_name
        _set_state(context, BotState.ADDING_DEVICE_SN)
        await update.message.reply_text(
            "Введите серийный номер устройства:"
        )
        return

    if state == BotState.ADDING_DEVICE_SN:
        sn = text.strip()
        if not sn:
            await update.message.reply_text("Серийный номер не может быть пустым.")
            return
        context.user_data.setdefault("new_device_data", {})["sn"] = sn
        device_types = storage.config.get("device_types", [])
        _set_state(context, BotState.ADDING_DEVICE_TYPE)
        types_text = ", ".join(device_types) if device_types else "типов нет"
        await update.message.reply_text(
            "Введите тип устройства.\n"
            f"Доступные типы: {types_text}"
        )
        return

    if state == BotState.ADDING_DEVICE_TYPE:
        dev_type = text.strip()
        device_types = storage.config.get("device_types", [])
        if device_types and dev_type not in device_types:
            await update.message.reply_text(
                "Неизвестный тип. Используйте один из доступных: "
                + ", ".join(device_types)
            )
            return
        context.user_data.setdefault("new_device_data", {})["type"] = dev_type
        if not storage.groups:
            await update.message.reply_text(
                "❌ Нет доступных групп. Создайте группу и начните добавление заново."
            )
            context.user_data.pop("new_device_data", None)
            _set_state(context, BotState.NONE)
            return
        _set_state(context, BotState.ADDING_DEVICE_GROUP)
        groups_text = _format_groups_list()
        await update.message.reply_text(
            "Введите ID группы, к которой будет относиться устройство:\n"
            f"{groups_text}"
        )
        return

    if state == BotState.ADDING_DEVICE_GROUP:
        device_data = context.user_data.get("new_device_data")
        if not device_data:
            await update.message.reply_text("Данные устройства не найдены. Начните заново.")
            _set_state(context, BotState.NONE)
            return
        try:
            group_id = int(text)
        except ValueError:
            await update.message.reply_text("ID группы должен быть числом. Попробуйте снова.")
            return
        group = utils.get_group_by_id(group_id)
        if not group:
            await update.message.reply_text("Группа не найдена. Введите корректный ID.")
            return

        new_id = max([d.get("id", 0) for d in storage.devices], default=0) + 1
        device = {
            "id": new_id,
            "name": device_data.get("name"),
            "sn": device_data.get("sn"),
            "type": device_data.get("type"),
            "status": "free",
            "group_id": group_id,
        }
        storage.devices.append(device)
        storage.save_devices()
        group_name = group.get("name", "Без названия")
        _set_state(context, BotState.NONE)
        context.user_data.pop("new_device_data", None)
        await update.message.reply_text(
            "✅ Устройство добавлено:\n"
            f"🆔 ID: {new_id}\n"
            f"📱 {device['name']}\n"
            f"🔢 SN: {device['sn']}\n"
            f"📦 Тип: {device['type']}\n"
            f"👥 Группа: {group_name}"
        )
        await show_admin_devices_by_type(update, context, device["type"])
        return

    if state == BotState.ADDING_DEVICE:
        # Используется для редактирования устройств или старого формата добавления
        edit_device_id = context.user_data.get("edit_device_id")
        
        if edit_device_id:
            # Редактирование устройства
            device = next((d for d in storage.devices if d.get("id") == edit_device_id), None)
            if not device:
                await update.message.reply_text("Устройство не найдено.")
                _set_state(context, BotState.NONE)
                context.user_data.pop("edit_device_id", None)
                return
            
            parts = [p.strip() for p in text.split(",")]
            if len(parts) not in (3, 4):
                await update.message.reply_text("Неверный формат. Используйте: Название, SN, Тип [, GroupID]")
                return
            name, sn, dev_type = parts[0], parts[1], parts[2]
            group_id = device.get("group_id")
            if len(parts) == 4:
                group_part = parts[3]
                if group_part == "":
                    group_id = None
                else:
                    try:
                        group_id_int = int(group_part)
                        if utils.get_group_by_id(group_id_int):
                            group_id = group_id_int
                        else:
                            await update.message.reply_text("Группа с таким ID не найдена. Укажите существующий ID или оставьте поле пустым.")
                            return
                    except ValueError:
                        await update.message.reply_text("ID группы должно быть числом. Попробуйте снова.")
                        return
            
            old_type = device.get("type", "Неизвестно")
            device["name"] = name
            device["sn"] = sn
            device["type"] = dev_type
            device["group_id"] = group_id
            storage.save_devices()
            
            _set_state(context, BotState.NONE)
            edit_device_type = context.user_data.pop("edit_device_type", old_type)
            context.user_data.pop("edit_device_id", None)
            
            # Используем новый тип устройства для возврата
            return_type = dev_type
            
            # Отправляем сообщение об успехе
            group_name = "Не назначена"
            if group_id:
                group = utils.get_group_by_id(group_id)
                group_name = group.get("name", f"ID: {group_id}") if group else f"ID: {group_id}"
            await update.message.reply_text(
                f"✅ Устройство обновлено:\n"
                f"🆔 ID: {edit_device_id}\n"
                f"📱 Название: {name}\n"
                f"🔢 SN: {sn}\n"
                f"📦 Тип: {dev_type}\n"
                f"👥 Группа: {group_name}"
            )
            
            # Показываем список устройств того же типа
            await show_admin_devices_by_type(update, context, return_type)
            return
        
        # Старый формат добавления (для обратной совместимости)
        try:
            sn, name, dev_type = map(str.strip, text.split(","))
        except ValueError:
            await update.message.reply_text("Неверный формат. Используйте: SN, Name, Type")
            return

        new_id = max([d.get("id", 0) for d in storage.devices], default=0) + 1
        storage.devices.append(
            {
                "id": new_id,
                "name": name,
                "sn": sn,
                "type": dev_type,
                "status": "free",
                "group_id": None,
            }
        )
        storage.save_devices()
        _set_state(context, BotState.NONE)
        await update.message.reply_text(f"Устройство {name} добавлено.")
        return

    if state == BotState.ADDING_GROUP_NAME:
        group_name = text.strip()
        if not group_name:
            await update.message.reply_text("Название группы не может быть пустым.")
            return
        
        # Проверяем, переименование или создание
        rename_group_id = context.user_data.get("rename_group_id")
        
        if rename_group_id:
            # Переименование группы
            group = utils.get_group_by_id(rename_group_id)
            if not group:
                await update.message.reply_text("❌ Группа не найдена.")
                _set_state(context, BotState.NONE)
                context.user_data.pop("rename_group_id", None)
                return
            
            # Проверяем, не существует ли уже группа с таким именем
            existing_group = utils.get_group_by_name(group_name)
            if existing_group and existing_group.get("id") != rename_group_id:
                await update.message.reply_text(f"Группа с названием '{group_name}' уже существует.")
                return
            
            old_name = group.get("name")
            group["name"] = group_name
            storage.save_groups()
            _set_state(context, BotState.NONE)
            context.user_data.pop("rename_group_id", None)
            
            await update.message.reply_text(
                f"✅ Группа переименована:\n"
                f"Было: {old_name}\n"
                f"Стало: {group_name}"
            )
            return
        
        # Создание новой группы
        # Проверяем, не существует ли уже группа с таким именем
        if utils.get_group_by_name(group_name):
            await update.message.reply_text(f"Группа с названием '{group_name}' уже существует.")
            _set_state(context, BotState.NONE)
            return
        
        # Создаем новую группу
        new_id = max([g.get("id", 0) for g in storage.groups], default=0) + 1
        storage.groups.append({
            "id": new_id,
            "name": group_name
        })
        storage.save_groups()
        _set_state(context, BotState.NONE)
        
        await update.message.reply_text(
            f"✅ Группа '{group_name}' создана (ID: {new_id}).\n\n"
            f"Теперь вы можете назначить пользователей и устройства этой группе."
        )
        return
    
    # если состояние другое (ADD_USER/EDIT_USER) — обработаем ниже в блоке управления пользователями
    # если никаких спец-состояний — ничего не делаем
    return


# ==========
# Импорт устройств из CSV (админ)
# ==========

@access_control(required_role="Admin")
async def import_devices_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос на импорт устройств (CSV/XLSX). Работает из сообщения и из callback."""
    query = update.callback_query
    msg = query.message if query else update.message
    if msg is None:
        msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="Импорт устройств")
    if query:
        await query.answer()
    await msg.reply_text("Отправьте CSV или XLSX с колонками: SN, Name, Type.")
    context.user_data["awaiting_devices_csv"] = True
    # только если исходное сообщение есть
    if update.message:
        await update.message.reply_text("Можно загрузить CSV или XLSX.")


@access_control(required_role="Admin")
async def process_devices_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_devices_csv"):
        return

    file = update.message.document
    if not file:
        await update.message.reply_text("Ошибка: ожидается файл.")
        return

    file_obj = await file.get_file()
    file_path = await file_obj.download_to_drive()

    added = 0
    try:
        rows = load_devices_from_file(file_path)
        max_id = max([d.get("id", 0) for d in storage.devices], default=0)
        for row in rows:
            if not row["SN"] and not row["Name"]:
                continue
            group_id_raw = row.get("GroupId", "").strip()
            group_id = None
            if group_id_raw:
                try:
                    group_id_int = int(group_id_raw)
                    # проверим, есть ли группа
                    if utils.get_group_by_id(group_id_int):
                        group_id = group_id_int
                except ValueError:
                    pass
            max_id += 1
            storage.devices.append(
                {
                    "id": max_id,
                    "name": row["Name"],
                    "sn": row["SN"],
                    "type": row["Type"],
                    "status": "free",
                    "group_id": group_id,
                }
            )
            added += 1
        storage.save_devices()
        await update.message.reply_text(f"Устройства импортированы. Добавлено: {added}.")
    except ValueError as err:
        await update.message.reply_text(f"Ошибка импорта: {err}")
    finally:
        try:
            os.remove(file_path)
        except OSError:
            pass

    context.user_data["awaiting_devices_csv"] = False


# ==========
# Управление пользователями (админ)
# ==========

@access_control(required_role="Admin")
async def manage_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление пользователями с кнопками действий."""
    pending = [u for u in storage.users if u.get("status") == "pending"]
    
    # Показываем ожидающие заявки
    if pending:
        lines = []
        inline_buttons = []
    for u in pending:
        user_info = (
                f"👤 **{u.get('first_name', '')} {u.get('last_name', '')}**\n"
                f"🆔 ID: {u['user_id']} | @{u.get('username', 'N/A')}\n"
            )
        phone = u.get("phone", "")
        if phone:
            user_info += f"📱 Телефон: {phone}\n"
        group = utils.get_group_by_id(u.get("group_id"))
        if group:
            user_info += f"👥 Группа: {group.get('name', 'Без названия')} (ID: {group.get('id')})\n"
        else:
            user_info += "👥 Группа: не назначена\n"
        lines.append(user_info)
            
            inline_buttons.append([
                InlineKeyboardButton(f"✅ Утвердить {u['user_id']}", callback_data=f"approve_user_{u['user_id']}"),
                InlineKeyboardButton(f"❌ Отклонить {u['user_id']}", callback_data=f"reject_user_{u['user_id']}")
            ])
        
        text = "⏳ **Ожидающие заявки**\n\n" + "\n".join(lines)
        inline_buttons.append([InlineKeyboardButton("➕ Добавить пользователя", callback_data="add_user")])
        inline_buttons.append([InlineKeyboardButton("📋 Все пользователи", callback_data="list_all_users")])
        
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_buttons),
        )
    else:
        # Нет ожидающих заявок, показываем кнопку добавления и список всех
        kb = [
            [InlineKeyboardButton("➕ Добавить пользователя", callback_data="add_user")],
            [InlineKeyboardButton("📋 Все пользователи", callback_data="list_all_users")],
        ]
        await update.message.reply_text(
            "✅ Нет ожидающих заявок.",
            reply_markup=InlineKeyboardMarkup(kb),
        )


async def list_all_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает всех пользователей с кнопками действий."""
    query = update.callback_query
    await query.answer()
    
    if not storage.users:
        await query.edit_message_text("Нет пользователей.")
        return
    
    lines = []
    inline_buttons = []
    
    for u in storage.users:
        status_emoji = "✅" if u.get("status") == "active" else "⏳"
        role_emoji = "👑" if u.get("role") == "Admin" else "👤"
        
        user_info = (
            f"{status_emoji} {role_emoji} **{u.get('first_name', '')} {u.get('last_name', '')}**\n"
            f"🆔 ID: {u['user_id']} | @{u.get('username', 'N/A')}\n"
        )
        phone = u.get("phone", "")
        if phone:
            user_info += f"📱 Телефон: {phone}\n"
        display_name = u.get("display_name")
        if display_name:
            user_info += f"📝 Имя: {display_name}\n"
        group = utils.get_group_by_id(u.get("group_id"))
        if group:
            user_info += f"👥 Группа: {group.get('name', 'Без названия')} (ID: {group.get('id')})\n"
        else:
            user_info += "👥 Группа: не назначена\n"
        user_info += f"📊 Роль: {u.get('role', 'User')} | Статус: {u.get('status', 'unknown')}"
        
        lines.append(user_info)
        
        inline_buttons.append([
            InlineKeyboardButton(f"✏️ Изменить {u['user_id']}", callback_data=f"edit_user_{u['user_id']}"),
            InlineKeyboardButton(f"🗑️ Удалить {u['user_id']}", callback_data=f"delete_user_{u['user_id']}"),
            InlineKeyboardButton(
                "🚫 Заблокировать" if u.get("status") != "blocked" else "🔓 Разблокировать",
                callback_data=("block_user_" if u.get("status") != "blocked" else "unblock_user_") + str(u["user_id"])
            )
        ])
    
    text = f"👥 **Все пользователи** ({len(storage.users)} шт.)\n\n" + "\n\n".join(lines)
    inline_buttons.append([InlineKeyboardButton("➕ Добавить пользователя", callback_data="add_user")])
    inline_buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin")])
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_buttons),
    )


async def add_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс добавления пользователя."""
    query = update.callback_query
    await query.answer()

    if not storage.groups:
        await query.edit_message_text(
            "❌ Сначала создайте хотя бы одну группу в разделе 'Управление группами'."
        )
        return
    
    _set_state(context, BotState.ADDING_USER_ID)
    await query.edit_message_text(
        "➕ **Добавление пользователя**\n\n"
        "Введите Telegram User ID пользователя:",
        parse_mode="Markdown"
    )


@access_control(required_role="Admin")
async def admin_users_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # approve <id>
    m = re.match(r"approve\s+(\d+)", text, re.IGNORECASE)
    if m:
        user_id = int(m.group(1))
        user = utils.get_user_by_id(user_id)
        if not user:
            await update.message.reply_text("Пользователь не найден.")
            return
        user["status"] = "active"
        storage.save_users()
        await update.message.reply_text(f"Пользователь @{user.get('username')} утверждён.")
        return

    # reject <id>
    m = re.match(r"reject\s+(\d+)", text, re.IGNORECASE)
    if m:
        user_id = int(m.group(1))
        user = utils.get_user_by_id(user_id)
        if not user:
            await update.message.reply_text("Пользователь не найден.")
            return
        storage.users.remove(user)
        storage.save_users()
        await update.message.reply_text(f"Заявка пользователя @{user.get('username')} отклонена и удалена.")
        return

    # adduser
    if text.lower() == "adduser":
        if not storage.groups:
            await update.message.reply_text(
                "❌ Нет доступных групп. Сначала создайте группу в разделе 'Управление группами'."
            )
            return
        _set_state(context, BotState.ADDING_USER)
        await update.message.reply_text(
            "Введите пользователя в формате: Имя, Фамилия, username, роль\n"
            "Пример:\nИван, Иванов, ivan123, Admin"
        )
        return

    # edituser <id>
    m = re.match(r"edituser\s+(\d+)", text, re.IGNORECASE)
    if m:
        user_id = int(m.group(1))
        user = utils.get_user_by_id(user_id)
        if not user:
            await update.message.reply_text("Пользователь не найден.")
            return
        context.user_data["edit_user_id"] = user_id
        _set_state(context, BotState.EDITING_USER)
        await update.message.reply_text(
            f"Редактирование пользователя {user_id}. Введите данные:\n"
            "Имя, Фамилия, username, роль, статус(active/pending)\n"
        )
        return

    # deluser <id>
    m = re.match(r"deluser\s+(\d+)", text, re.IGNORECASE)
    if m:
        user_id = int(m.group(1))
        user = utils.get_user_by_id(user_id)
        if not user:
            await update.message.reply_text("Пользователь не найден.")
            return
        storage.users.remove(user)
        storage.save_users()
        await update.message.reply_text("Пользователь удалён.")
        return

    # blockuser <id>
    m = re.match(r"blockuser\s+(\d+)", text, re.IGNORECASE)
    if m:
        user_id = int(m.group(1))
        user = utils.get_user_by_id(user_id)
        if not user:
            await update.message.reply_text("Пользователь не найден.")
            return
        user["status"] = "blocked"
        storage.save_users()
        await update.message.reply_text(f"Пользователь @{user.get('username')} заблокирован.")
        return

    # unblockuser <id>
    m = re.match(r"unblockuser\s+(\d+)", text, re.IGNORECASE)
    if m:
        user_id = int(m.group(1))
        user = utils.get_user_by_id(user_id)
        if not user:
            await update.message.reply_text("Пользователь не найден.")
            return
        user["status"] = "active"
        storage.save_users()
        await update.message.reply_text(f"Пользователь @{user.get('username')} разблокирован.")
        return

    await update.message.reply_text("Неизвестная команда управления пользователями.")


@access_control(required_role="Admin")
async def handle_state_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = _get_state(context)
    
    # Если состояние NONE, не обрабатываем - пусть сообщение пройдет дальше к unknown_message для поиска
    if state == BotState.NONE:
        return
    
    text = update.message.text.strip()

    if state == BotState.ADDING_USER_ID:
        # Ожидаем user_id
        try:
            user_id = int(text)
        except ValueError:
            await update.message.reply_text("Неверный формат. Введите числовой User ID.")
            return
        
        # Проверяем, не существует ли уже пользователь
        if utils.get_user_by_id(user_id):
            await update.message.reply_text(f"Пользователь с ID {user_id} уже существует.")
            _set_state(context, BotState.NONE)
            return
        
        # Пытаемся получить информацию о пользователе из Telegram
        try:
            tg_user = await context.bot.get_chat(user_id)
            first_name = tg_user.first_name or "Не указано"
            last_name = tg_user.last_name or "Не указано"
            username = tg_user.username or "Не указано"
        except Exception:
            # Если не удалось получить, используем значения по умолчанию
            first_name = "Не указано"
            last_name = "Не указано"
            username = "Не указано"
        
        if not storage.groups:
            await update.message.reply_text(
                "❌ Нет доступных групп. Сначала создайте группу, затем добавьте пользователя."
            )
            _set_state(context, BotState.NONE)
            return
        
        context.user_data["pending_user"] = {
            "user_id": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "role": "User",
            "status": "active",
            "phone": "",
            "source": "tg_id",
        }
        _set_state(context, BotState.ADDING_USER_GROUP)
        groups_text = _format_groups_list()
        await update.message.reply_text(
            "Введите ID группы для пользователя:\n"
            f"{groups_text}"
        )
        return

    if state == BotState.ADDING_USER:
        try:
            first_name, last_name, username, role = map(str.strip, text.split(","))
        except ValueError:
            await update.message.reply_text(
                "Неверный формат. Используйте: Имя, Фамилия, username, роль"
            )
            return

        if not storage.groups:
            await update.message.reply_text(
                "❌ Нет доступных групп. Сначала создайте группу, затем добавьте пользователя."
            )
            _set_state(context, BotState.NONE)
            return
        
        new_id = max([u.get("user_id", 0) for u in storage.users], default=0) + 1
        context.user_data["pending_user"] = {
            "user_id": new_id,
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "role": role,
            "status": "active",
            "phone": "",
            "source": "manual",
        }
        _set_state(context, BotState.ADDING_USER_GROUP)
        groups_text = _format_groups_list()
        await update.message.reply_text(
            "Введите ID группы для пользователя:\n"
            f"{groups_text}"
        )
        return

    if state == BotState.EDITING_USER:
        user_id = context.user_data.get("edit_user_id")
        user = utils.get_user_by_id(user_id)
        if not user:
            await update.message.reply_text("Пользователь не найден.")
            _set_state(context, BotState.NONE)
            return
        try:
            first_name, last_name, username, role, status = map(str.strip, text.split(","))
        except ValueError:
            await update.message.reply_text(
                "Неверный формат. Используйте: Имя, Фамилия, username, роль, статус"
            )
            return
        # Обновляем данные, сохраняя телефон если он был
        phone = user.get("phone", "")
        user.update(
            {
                "first_name": first_name,
                "last_name": last_name,
                "username": username,
                "role": role,
                "status": status,
                "phone": phone,  # Сохраняем телефон
            }
        )
        storage.save_users()
        _set_state(context, BotState.NONE)
        await update.message.reply_text("Данные пользователя обновлены.")
        return

    if state == BotState.ADDING_USER_GROUP:
        pending_user = context.user_data.get("pending_user")
        if not pending_user:
            await update.message.reply_text("Нет данных пользователя. Начните заново.")
            _set_state(context, BotState.NONE)
            return
        try:
            group_id = int(text)
        except ValueError:
            await update.message.reply_text("ID группы должен быть числом. Попробуйте еще раз.")
            return
        group = utils.get_group_by_id(group_id)
        if not group:
            await update.message.reply_text("Группа не найдена. Введите корректный ID.")
            return
        
        pending_user["group_id"] = group_id
        storage.users.append({k: v for k, v in pending_user.items() if k != "source"})
        storage.save_users()
        
        source = pending_user.get("source")
        _set_state(context, BotState.NONE)
        context.user_data.pop("pending_user", None)
        group_name = group.get("name", "Без названия")
        
        if source == "tg_id":
            await update.message.reply_text(
                f"✅ Пользователь добавлен:\n"
                f"🆔 ID: {pending_user['user_id']}\n"
                f"👤 {pending_user.get('first_name')} {pending_user.get('last_name')}\n"
                f"📱 @{pending_user.get('username')}\n"
                f"👥 Группа: {group_name}\n\n"
                f"Используйте 'Изменить пользователя' для добавления телефона или изменения роли."
            )
        else:
            await update.message.reply_text(
                f"Пользователь @{pending_user.get('username')} добавлен в группу '{group_name}'."
            )
        return


# ==========
# Обработчики callback для управления пользователями
# ==========

async def approve_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Утверждение пользователя."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"approve_user_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    user_id = int(match.group(1))
    user = utils.get_user_by_id(user_id)
    if not user:
        await query.edit_message_text("Пользователь не найден.")
        return
    
    user["status"] = "active"
    storage.save_users()
    await query.edit_message_text(f"✅ Пользователь @{user.get('username')} утверждён.")
    
    # Обновляем список
    await manage_users_callback(update, context)


async def reject_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отклонение заявки пользователя."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"reject_user_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    user_id = int(match.group(1))
    user = utils.get_user_by_id(user_id)
    if not user:
        await query.edit_message_text("Пользователь не найден.")
        return
    
    username = user.get('username', 'N/A')
    storage.users.remove(user)
    storage.save_users()
    await query.edit_message_text(f"❌ Заявка пользователя @{username} отклонена и удалена.")
    
    # Обновляем список
    await manage_users_callback(update, context)


async def block_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Блокировка пользователя (игнорируется ботом)."""
    query = update.callback_query
    await query.answer()
    match = re.match(r"block_user_(\d+)", query.data)
    if not match:
        return
    user_id = int(match.group(1))
    user = utils.get_user_by_id(user_id)
    if not user:
        await query.edit_message_text("Пользователь не найден.")
        return
    user["status"] = "blocked"
    storage.save_users()
    await query.edit_message_text(f"🚫 Пользователь @{user.get('username')} заблокирован.")
    await manage_users_callback(update, context)


async def unblock_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Разблокировка пользователя (делаем active)."""
    query = update.callback_query
    await query.answer()
    match = re.match(r"unblock_user_(\d+)", query.data)
    if not match:
        return
    user_id = int(match.group(1))
    user = utils.get_user_by_id(user_id)
    if not user:
        await query.edit_message_text("Пользователь не найден.")
        return
    user["status"] = "active"
    storage.save_users()
    await query.edit_message_text(f"🔓 Пользователь @{user.get('username')} разблокирован.")
    await manage_users_callback(update, context)


async def edit_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает редактирование пользователя."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"edit_user_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    user_id = int(match.group(1))
    user = utils.get_user_by_id(user_id)
    if not user:
        await query.edit_message_text("Пользователь не найден.")
        return
    
    context.user_data["edit_user_id"] = user_id
    _set_state(context, BotState.EDITING_USER)
    
    phone = user.get("phone", "")
    await query.edit_message_text(
        f"✏️ **Редактирование пользователя**\n\n"
        f"Текущие данные:\n"
        f"Имя: {user.get('first_name')}\n"
        f"Фамилия: {user.get('last_name')}\n"
        f"Username: @{user.get('username')}\n"
        f"Роль: {user.get('role')}\n"
        f"Статус: {user.get('status')}\n"
        f"Телефон: {phone if phone else 'Не указан'}\n\n"
        f"Введите новые данные в формате:\n"
        f"Имя, Фамилия, username, роль, статус, телефон\n"
        f"Пример:\nИван, Иванов, ivan123, Admin, active, +79001234567",
        parse_mode="Markdown"
    )


async def delete_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление пользователя."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"delete_user_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    user_id = int(match.group(1))
    user = utils.get_user_by_id(user_id)
    if not user:
        await query.edit_message_text("Пользователь не найден.")
        return
    
    username = user.get('username', 'N/A')
    storage.users.remove(user)
    storage.save_users()
    await query.edit_message_text(f"🗑️ Пользователь @{username} удалён.")
    
    # Обновляем список
    await list_all_users_callback(update, context)


async def manage_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню управления пользователями (для callback)."""
    query = update.callback_query
    if query:
        await query.answer()
        msg = query.message
    else:
        msg = update.message
    
    pending = [u for u in storage.users if u.get("status") == "pending"]
    
    if pending:
        lines = []
        inline_buttons = []
        for u in pending:
            user_info = (
                f"👤 **{u.get('first_name', '')} {u.get('last_name', '')}**\n"
                f"🆔 ID: {u['user_id']} | @{u.get('username', 'N/A')}\n"
            )
            phone = u.get("phone", "")
            if phone:
                user_info += f"📱 Телефон: {phone}\n"
            lines.append(user_info)
            
            inline_buttons.append([
                InlineKeyboardButton(f"✅ Утвердить {u['user_id']}", callback_data=f"approve_user_{u['user_id']}"),
                InlineKeyboardButton(f"❌ Отклонить {u['user_id']}", callback_data=f"reject_user_{u['user_id']}"),
                InlineKeyboardButton(f"🚫 Блокировать", callback_data=f"block_user_{u['user_id']}")
            ])
        
        text = "⏳ **Ожидающие заявки**\n\n" + "\n".join(lines)
        inline_buttons.append([InlineKeyboardButton("➕ Добавить пользователя", callback_data="add_user")])
        inline_buttons.append([InlineKeyboardButton("📋 Все пользователи", callback_data="list_all_users")])
        
        if query:
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_buttons),
            )
        else:
            await msg.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_buttons),
            )
    else:
        kb = [
            [InlineKeyboardButton("➕ Добавить пользователя", callback_data="add_user")],
            [InlineKeyboardButton("📋 Все пользователи", callback_data="list_all_users")],
        ]
        if query:
            await query.edit_message_text(
                "✅ Нет ожидающих заявок.",
                reply_markup=InlineKeyboardMarkup(kb),
            )
        else:
            await msg.reply_text(
                "✅ Нет ожидающих заявок.",
                reply_markup=InlineKeyboardMarkup(kb),
            )


async def back_to_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в админ-панель."""
    query = update.callback_query
    await query.answer()
    _set_state(context, BotState.NONE)
    
    await admin_panel(update, context)


# ==========
# Обработчики callback для управления устройствами (админ)
# ==========

async def add_device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс добавления устройства."""
    query = update.callback_query
    await query.answer()

    if not storage.groups:
        await query.edit_message_text(
            "❌ Сначала создайте хотя бы одну группу, чтобы назначать устройства."
        )
        return
    
    context.user_data["new_device_data"] = {}
    
    _set_state(context, BotState.ADDING_DEVICE_NAME)
    await query.edit_message_text(
        "➕ **Добавление устройства**\n\n"
        "Введите название устройства:",
        parse_mode="Markdown"
    )


async def edit_device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает редактирование устройства."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"edit_device_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    device_id = int(match.group(1))
    device = next((d for d in storage.devices if d.get("id") == device_id), None)
    
    if not device:
        await query.edit_message_text("Устройство не найдено.")
        return

    group_id = device.get("group_id")
    group_name = "Не назначена"
    if group_id:
        group = utils.get_group_by_id(group_id)
        group_name = f"{group.get('name', 'Без названия')} (ID: {group_id})" if group else f"ID: {group_id}"
    
    # Показываем текущие данные и предлагаем изменить
    device_info = (
        f"✏️ **Редактирование устройства**\n\n"
        f"Текущие данные:\n"
        f"🆔 ID: {device_id}\n"
        f"📱 Название: {device.get('name')}\n"
        f"🔢 SN: {device.get('sn')}\n"
        f"📦 Тип: {device.get('type')}\n"
        f"👥 Группа: {group_name}\n\n"
        f"Введите новые данные в формате:\n"
        f"Название, SN, Тип, GroupID (опционально)\n"
        f"Примеры:\n"
        f"iPhone 12, SN-123456, Phone, 2\n"
        f"iPhone 12, SN-123456, Phone  (если оставить группу без изменений)"
    )
    
    context.user_data["edit_device_id"] = device_id
    context.user_data["edit_device_type"] = device.get("type", "Неизвестно")  # Сохраняем тип для возврата
    _set_state(context, BotState.ADDING_DEVICE)  # Используем состояние для редактирования
    
    await query.edit_message_text(device_info, parse_mode="Markdown")


async def delete_device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление устройства."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"delete_device_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    device_id = int(match.group(1))
    device = next((d for d in storage.devices if d.get("id") == device_id), None)
    
    if not device:
        await query.edit_message_text("Устройство не найдено.")
        return
    
    device_name = device.get("name", "Неизвестно")
    device_sn = device.get("sn", "N/A")
    device_type = device.get("type", "Неизвестно")
    
    storage.devices.remove(device)
    storage.save_devices()
    
    await query.edit_message_text(
        f"🗑️ Устройство **{device_name}** (SN: `{device_sn}`) удалено.",
        parse_mode="Markdown"
    )
    
    # Возвращаемся к списку устройств того же типа или к выбору типов
    if device_type and device_type != "Неизвестно":
        # Показываем устройства этого типа
        await show_admin_devices_by_type(update, context, device_type)
    else:
        # Возвращаемся к выбору типов
        await manage_devices_admin_callback(update, context)


async def show_admin_devices_by_type(update: Update, context: ContextTypes.DEFAULT_TYPE, dev_type: str = None):
    """Показывает список устройств для управления (по типу или все)."""
    query = update.callback_query
    if query:
        await query.answer()
    
    utils.cleanup_expired_bookings()
    
    # Получаем устройства
    if dev_type:
        devices = [d for d in storage.devices if d.get("type") == dev_type]
        title = f"📦 **{dev_type}** ({len(devices)} шт.)"
    else:
        devices = sorted(storage.devices, key=lambda x: x.get("id", 0))
        title = f"📋 **Все устройства** ({len(devices)} шт.)"
    
    if not devices:
        text = f"Нет устройств типа {dev_type}." if dev_type else "Нет устройств."
        inline_buttons = [[InlineKeyboardButton("◀️ Назад к типам", callback_data="manage_devices_admin")]]
        if query:
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_buttons),
            )
        return
    
    # Формируем список устройств только с кнопками (без текста)
    inline_buttons = []
    
    for device in sorted(devices, key=lambda x: x.get("id", 0)):
        status_emoji = "✅" if device.get("status") == "free" else "🔒"
        device_name = device.get("name", "Неизвестно")
        device_id = device.get("id")
        device_type = device.get("type", "Неизвестно")
        device_sn = device.get("sn", "N/A")
        
        # Формируем текст для кнопки редактирования (вся информация на кнопке)
        # Telegram ограничивает длину кнопки до 64 байт, поэтому используем компактный формат
        # Формат: ✅ Название\nID:30 📦 RKBoard 🔢 SN-502910
        group_short = _group_label_short(device.get("group_id"))
        button_text = f"{status_emoji} {device_name}\n🆔 ID:{device_id} 📦 {device_type} 🔢 {device_sn}\n👥 {group_short}"
        
        # Если текст слишком длинный, сокращаем название устройства
        max_button_length = 64
        if len(button_text.encode('utf-8')) > max_button_length:
            # Вычисляем сколько места осталось для названия
            base_text = f"{status_emoji} \n🆔 ID:{device_id} 📦 {device_type} 🔢 {device_sn}\n👥 {group_short}"
            base_length = len(base_text.encode('utf-8'))
            available_length = max_button_length - base_length - 3  # -3 для "..."
            
            if available_length > 0:
                # Сокращаем название устройства
                device_name_bytes = device_name.encode('utf-8')
                if len(device_name_bytes) > available_length:
                    # Обрезаем по байтам, чтобы не сломать UTF-8
                    device_name_short = device_name_bytes[:available_length].decode('utf-8', errors='ignore')
                    # Убираем неполные символы в конце
                    while len(device_name_short.encode('utf-8')) > available_length:
                        device_name_short = device_name_short[:-1]
                    button_text = f"{status_emoji} {device_name_short}...\n🆔 ID:{device_id} 📦 {device_type} 🔢 {device_sn}"
                else:
                    button_text = f"{status_emoji} {device_name}\n🆔 ID:{device_id} 📦 {device_type} 🔢 {device_sn}"
            else:
                # Если все еще длинно, используем минимальный формат
                button_text = f"{status_emoji} {device_name[:15]}...\nID:{device_id}"
        
        # Кнопки: редактирование (с информацией) сверху, удаление снизу
        # Размещаем кнопки друг под другом - кнопка удаления будет меньше, так как текст короткий
        inline_buttons.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"edit_device_{device_id}"
            )
        ])
        inline_buttons.append([
            InlineKeyboardButton(
                "🗑️",
                callback_data=f"delete_device_{device_id}"
            )
        ])
    
    # Только заголовок, без текстового списка устройств
    text = f"{title}\n\nВыберите устройство для редактирования:"
    inline_buttons.append([InlineKeyboardButton("➕ Добавить устройство", callback_data="add_device")])
    inline_buttons.append([InlineKeyboardButton("◀️ Назад к типам", callback_data="manage_devices_admin")])
    
    if query:
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_buttons),
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_buttons),
        )


async def admin_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора типа устройств в админ-панели."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"admin_type_(.+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    dev_type = match.group(1)
    await show_admin_devices_by_type(update, context, dev_type)


async def admin_all_devices_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все устройства в админ-панели."""
    query = update.callback_query
    await query.answer()
    await show_admin_devices_by_type(update, context, None)


# ==========
# Экспорт CSV (только админ)
# ==========

def _build_csv_bytes(header: List[str], rows: List[List[Any]], filename: str) -> io.BytesIO:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    data = buf.getvalue().encode("utf-8-sig")
    bio = io.BytesIO(data)
    bio.name = filename
    return bio


async def export_devices_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback для экспорта устройств."""
    query = update.callback_query
    if query:
        await query.answer("Экспорт устройств...")
        msg = query.message
    else:
        msg = update.message
    
    await export_devices_internal(update, context, msg)


@access_control(required_role="Admin")
async def export_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт устройств (для текстовых команд)."""
    await export_devices_internal(update, context, update.message)


async def export_devices_internal(update: Update, context: ContextTypes.DEFAULT_TYPE, msg):
    """Внутренняя функция экспорта устройств."""
    rows = [
        [
            d.get("id"),
            d.get("name"),
            d.get("sn"),
            d.get("type"),
            d.get("status"),
            d.get("user_id"),
            d.get("booking_expiration"),
        ]
        for d in storage.devices
    ]
    bio = _build_csv_bytes(
        ["id", "name", "sn", "type", "status", "user_id", "booking_expiration"],
        rows,
        "devices_export.csv",
    )
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=bio,
        caption="Экспорт устройств",
    )


async def export_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback для экспорта пользователей."""
    query = update.callback_query
    if query:
        await query.answer("Экспорт пользователей...")
    await export_users_internal(update, context)


@access_control(required_role="Admin")
async def export_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт пользователей (для текстовых команд)."""
    await export_users_internal(update, context)


async def export_users_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Внутренняя функция экспорта пользователей."""
    rows = [
        [
            u.get("user_id"),
            u.get("first_name"),
            u.get("last_name"),
            u.get("username"),
            u.get("role"),
            u.get("status"),
            u.get("phone", ""),  # Добавляем телефон
        ]
        for u in storage.users
    ]
    bio = _build_csv_bytes(
        ["user_id", "first_name", "last_name", "username", "role", "status", "phone"],
        rows,
        "users_export.csv",
    )
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=bio,
        caption="Экспорт пользователей",
    )


async def export_logs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback для экспорта логов."""
    query = update.callback_query
    if query:
        await query.answer("Экспорт логов...")
    await export_logs_internal(update, context)


@access_control(required_role="Admin")
async def export_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт логов (для текстовых команд)."""
    await export_logs_internal(update, context)


async def export_logs_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Внутренняя функция экспорта логов."""
    rows: List[List[Any]] = []
    for sn, entries in storage.logs.items():
        for e in entries:
            rows.append([e.get("timestamp"), sn, e.get("action")])
    bio = _build_csv_bytes(
        ["timestamp", "device_sn", "action"],
        rows,
        "device_logs_export.csv",
    )
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=bio,
        caption="Экспорт логов бронирований",
    )


# ==========
# Сканирование QR/штрих-кодов
# ==========

def _find_devices_by_code(code: str) -> List[Dict[str, Any]]:
    """Поиск устройств по коду (полное или частичное совпадение SN)."""
    code = code.strip().upper()
    if not code:
        return []
    
    # Сначала ищем точное совпадение
    exact_matches = [d for d in storage.devices if d.get("sn", "").upper() == code]
    if exact_matches:
        return exact_matches
    
    # Затем ищем частичные совпадения
    partial_matches = [d for d in storage.devices if code in d.get("sn", "").upper()]
    return partial_matches


@access_control()
async def scan_code_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню сканирования: QR / Фото / WebApp."""

    user_id = update.effective_user.id
    context.user_data["scanning_mode"] = True

    # Получаем URL WebApp
    webapp_url = storage.config.get("webapp_url") or ""

    # Показываем кнопку НАЗАД
    reply_kb = ReplyKeyboardMarkup(
        [["Назад"]],
        resize_keyboard=True
    )

    # Inline-кнопка WebApp
    inline_buttons = None
    if webapp_url:
        inline_buttons = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📷 Открыть сканер", web_app=WebAppInfo(url=webapp_url))]
            ]
        )

    # Сообщение с инструкцией
    await update.message.reply_text(
        "📷 *Сканирование устройств*\n\n"
        "Чтобы сканер отправлял данные в бот, используйте кнопку ниже.\n"
        "_Открытие по ссылке ⚠️ не работает — Telegram не выдаёт WebApp API._\n\n"
        "Доступные способы:\n"
        "• 📱 QR-коды (встроенный сканер)\n"
        "• 🔤 Серийные номера с изображения\n"
        "• ✍️ Ввод кода вручную\n\n"
        "*Выберите метод:*",
        reply_markup=reply_kb,
        parse_mode="Markdown"
    )

    # Показываем inline WebApp кнопку ОТДЕЛЬНЫМ сообщением (важно!)
    if inline_buttons:
        await update.message.reply_text(
            "👇 *Открыть встроенный сканер (рекомендуется)*",
            reply_markup=inline_buttons,
            parse_mode="Markdown"
        )


def _extract_serial_number(text: str) -> Optional[str]:
    """Извлекает серийный номер из текста. Ищет паттерны SN-XXXXXX или просто номер."""
    if not text:
        return None
    
    # Очищаем текст от лишних пробелов
    text = ' '.join(text.split())
    
    # Паттерн 1: SN-XXXXXX или SN:XXXXXX или SN XXXXXX (где X - буквы/цифры)
    sn_patterns = [
        r'SN[-:\s]+([A-Z0-9\-]{3,})',  # SN-123456 или SN:123456
        r'S\/N[-:\s]+([A-Z0-9\-]{3,})',  # S/N-123456
        r'SERIAL[-:\s]+([A-Z0-9\-]{3,})',  # SERIAL-123456
    ]
    
    for pattern in sn_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            sn = match.group(1).strip().upper()
            # Убираем лишние дефисы в начале/конце
            sn = sn.strip('-')
            if len(sn) >= 3:  # Минимум 3 символа для серийного номера
                return sn
    
    # Паттерн 2: Если не найден паттерн с префиксом, ищем просто последовательность
    # Ищем последовательности из 4+ символов (буквы/цифры/дефисы)
    # Исключаем слишком короткие или слишком длинные (вероятно, не серийный номер)
    number_pattern = r'\b([A-Z0-9\-]{4,15})\b'
    matches = re.findall(number_pattern, text, re.IGNORECASE)
    if matches:
        # Фильтруем: исключаем числа без букв (вероятно, не серийный номер)
        # и слишком короткие последовательности
        filtered = [m for m in matches if len(m) >= 4 and not m.replace('-', '').isdigit()]
        if filtered:
            # Возвращаем самую длинную последовательность (вероятно, это серийный номер)
            sn = max(filtered, key=len).strip().upper()
            sn = sn.strip('-')
            return sn if len(sn) >= 4 else None
    
    return None


async def _recognize_text_from_photo(photo_bytes: bytes) -> Optional[str]:
    """Распознает текст из фото с помощью OCR."""
    if not OCR_AVAILABLE:
        return None
    
    try:
        # Получаем OCR reader (ленивая инициализация)
        reader = _get_ocr_reader()
        
        # Читаем изображение из байтов
        image = Image.open(io.BytesIO(photo_bytes))
        
        # Конвертируем в RGB, если нужно
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Конвертируем в numpy array
        image_array = np.array(image)
        
        # Распознаем текст
        results = reader.readtext(image_array)
        
        # Объединяем все распознанные тексты
        if results:
            recognized_text = ' '.join([result[1] for result in results])
            return recognized_text
        else:
            return None
            
    except Exception as e:
        print(f"Ошибка OCR: {e}")
        return None


@access_control()
async def handle_photo_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фото с QR/штрих-кодом или текстовым серийным номером."""
    scanning_mode = context.user_data.get("scanning_mode", False)
    
    if not scanning_mode:
        # Если не в режиме сканирования, не обрабатываем фото
        # Это позволит другим обработчикам обработать фото, если нужно
        return
    
    # Проверяем, есть ли текст в сообщении (Telegram мог автоматически распознать QR)
    # Иногда Telegram распознает QR и добавляет текст к сообщению
    if update.message.text and update.message.text.strip():
        # Если есть текст, обрабатываем как код
        await handle_code_scan(update, context)
        return
    
    # Если текста нет, но есть фото - пытаемся распознать с помощью OCR
    if update.message.photo:
        # Отправляем сообщение о начале обработки
        processing_msg = await update.message.reply_text("🔍 Обработка фото... Пожалуйста, подождите.")
        
        try:
            # Получаем фото (берем самое большое)
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            
            # Загружаем фото в память
            photo_bytes = await file.download_as_bytearray()
            
            # Пытаемся распознать текст с помощью OCR
            recognized_text = await _recognize_text_from_photo(photo_bytes)
            
            if recognized_text:
                # Ищем серийный номер в распознанном тексте
                serial_number = _extract_serial_number(recognized_text)
                
                if serial_number:
                    await processing_msg.edit_text(
                        f"✅ Распознан серийный номер: **{serial_number}**\n\n"
                        f"Распознанный текст: `{recognized_text[:100]}...`",
                        parse_mode="Markdown"
                    )
                    
                    # Обрабатываем найденный серийный номер как код напрямую
                    await _process_code_directly(update, context, serial_number, message_for_reply=processing_msg)
                    return
                else:
                    await processing_msg.edit_text(
                        f"⚠️ Текст распознан, но серийный номер не найден.\n\n"
                        f"Распознанный текст: `{recognized_text[:200]}`\n\n"
                        f"Пожалуйста, введите серийный номер вручную.",
                        parse_mode="Markdown"
                    )
                    return
            else:
                # OCR не доступен или не распознал текст
                if not OCR_AVAILABLE:
                    await processing_msg.edit_text(
                        "❌ OCR не доступен. Установите библиотеку easyocr:\n"
                        "`pip install easyocr`\n\n"
                        "Или введите серийный номер вручную.",
                        parse_mode="Markdown"
                    )
                else:
                    await processing_msg.edit_text(
                        "⚠️ Не удалось распознать текст на фото.\n\n"
                        "Пожалуйста:\n"
                        "• Убедитесь, что фото четкое и текст хорошо виден\n"
                        "• Введите серийный номер вручную\n"
                        "• Попробуйте отправить фото еще раз"
                    )
                return
                
        except Exception as e:
            await processing_msg.edit_text(
                f"❌ Ошибка при обработке фото: {str(e)}\n\n"
                "Пожалуйста, введите серийный номер вручную."
            )
            return
    
    # Если ничего не помогло
    await update.message.reply_text(
        "📷 Фото получено.\n\n"
        "Если Telegram автоматически распознал QR-код, вы увидите текст под фото.\n"
        "Пожалуйста, отправьте этот текст боту.\n\n"
        "Если QR-код не распознан автоматически, введите код вручную.\n"
        "Убедитесь, что QR-код четко виден на фото.\n\n"
        "💡 Совет: Вы также можете просто ввести серийный номер устройства вручную."
    )


async def _process_code_directly(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    code: str,
    message_for_reply=None
):
    """Обрабатывает код напрямую без необходимости в update.message.text.
    Ищет устройства по серийному номеру, названию, модели и типу."""
    utils.cleanup_expired_bookings()
    
    if not code or not code.strip():
        reply_target = message_for_reply or update.message
        await reply_target.reply_text("Код не распознан. Попробуйте еще раз.")
        return
    
    code = code.strip()
    reply_target = message_for_reply or update.message
    
    # Сначала ищем по серийному номеру (точное и частичное совпадение)
    devices_by_sn = _find_devices_by_code(code)
    
    # Затем ищем по тексту (название, модель, тип)
    devices_by_text = _search_devices_by_text(code)
    
    # Объединяем результаты, убирая дубликаты по ID
    all_devices = {}
    for device in devices_by_sn + devices_by_text:
        device_id = device.get("id")
        if device_id:
            all_devices[device_id] = device
    
    devices = list(all_devices.values())
    
    if not devices:
        await reply_target.reply_text(
            f"❌ Устройство с кодом '{code}' не найдено в базе.\n\n"
            "Проверьте правильность кода или обратитесь к администратору.",
            reply_markup=main_menu_keyboard(update.effective_user.id),
        )
        return
    
    user_id = update.effective_user.id
    
    # Если найдено несколько устройств
    if len(devices) > 1:
        kb = [[f"📱 {d['name']} (SN: {d['sn']}) - ID {d['id']}"] for d in devices]
        kb.append(["Назад"])
        context.user_data["scanning_mode"] = True  # Помечаем, что в режиме сканирования
        await reply_target.reply_text(
            f"🔍 Найдено {len(devices)} устройств по коду '{code}':\n\n"
            "Выберите нужное устройство:",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True),
        )
        return
    
    # Одно устройство найдено
    device = devices[0]
    await _handle_device_found(update, context, device, user_id, message_for_reply=reply_target)


@access_control()
async def handle_code_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка отсканированного или введенного кода."""
    # Проверяем, есть ли текст в сообщении
    if not update.message or not update.message.text:
        await update.message.reply_text("Код не распознан. Попробуйте еще раз.")
        return
    
    code = update.message.text.strip()
    await _process_code_directly(update, context, code)


async def _handle_device_found(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    device: Dict[str, Any],
    user_id: int,
    message_for_reply=None,
):
    """Обработка найденного устройства с разными сценариями."""
    device_status = device.get("status", "free")
    device_user_id = device.get("user_id")
    
    # Определяем, куда отправлять ответ
    reply_target = message_for_reply or update.message
    
    device_info = (
        f"📱 **{device['name']}**\n"
        f"🔢 SN: `{device['sn']}`\n"
        f"📦 Тип: {device['type']}\n"
        f"🆔 ID: {device['id']}\n\n"
    )
    
    # Сценарий 1: Устройство свободно
    if device_status == "free":
        kb = [
            [InlineKeyboardButton("✅ Забронировать", callback_data=f"scan_book_{device['id']}")],
            [InlineKeyboardButton("❌ Отмена", callback_data="scan_cancel")],
        ]
        await reply_target.reply_text(
            device_info + "✅ Устройство свободно и доступно для бронирования.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return
    
    # Сценарий 2: Устройство забронировано текущим пользователем
    if device_user_id == user_id:
        expiration = device.get("booking_expiration")
        exp_text = utils.format_datetime(expiration) if expiration else "Не указано"
        
        kb = [
            [InlineKeyboardButton("🔓 Освободить", callback_data=f"scan_release_{device['id']}")],
            [InlineKeyboardButton("❌ Отмена", callback_data="scan_cancel")],
        ]
        await reply_target.reply_text(
            device_info
            + f"🔒 Устройство забронировано вами.\n"
            f"📅 До: {exp_text}\n\n"
            "Вы можете освободить устройство.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return
    
    # Сценарий 3: Устройство забронировано другим пользователем
    other_user_name = utils.get_user_full_name(device_user_id)
    expiration = device.get("booking_expiration")
    exp_text = utils.format_datetime(expiration) if expiration else "Не указано"
    
    kb = [
        [
            InlineKeyboardButton(
                "🔄 Запросить передачу", callback_data=f"scan_transfer_{device['id']}"
            )
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="scan_cancel")],
    ]
    await reply_target.reply_text(
        device_info
        + f"⚠️ Устройство забронировано пользователем: **{other_user_name}**\n"
        f"📅 До: {exp_text}\n\n"
        "Вы можете запросить передачу устройства. "
        "Пользователь получит уведомление и сможет подтвердить передачу.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def scan_book_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка бронирования устройства через сканирование."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"scan_book_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    device_id = int(match.group(1))
    device = next((d for d in storage.devices if d.get("id") == device_id), None)
    
    if not device or device.get("status") != "free":
        await query.edit_message_text("❌ Устройство уже забронировано или не найдено.")
        return
    
    user_id = update.effective_user.id
    
    # Проверка принадлежности к группе (для не-админов)
    if not utils.is_admin(user_id):
        if not utils.can_user_book_device(user_id, device_id):
            user_group = utils.get_user_group(user_id)
            device_group = utils.get_device_group(device_id)
            if not user_group:
                await query.edit_message_text(
                    "❌ У вас не назначена группа. Обратитесь к администратору."
                )
            elif not device_group:
                await query.edit_message_text(
                    "❌ Устройство не назначено ни в какую группу."
                )
            else:
                await query.edit_message_text(
                    f"❌ Вы не можете бронировать устройства из группы '{device_group.get('name')}'. "
                    f"Ваша группа: '{user_group.get('name')}'."
                )
            return
    
    # Проверка лимита устройств
    max_devices = storage.config.get("max_devices_per_user", 2)
    current_count = len(
        [d for d in storage.devices if d.get("user_id") == user_id and d.get("status") == "booked"]
    )
    if current_count >= max_devices:
        await query.edit_message_text(
            f"❌ Нельзя забронировать больше {max_devices} устройств одновременно."
        )
        return
    
    # Бронирование
    default_days = device.get(
        "default_booking_period",
        storage.config.get("default_booking_period_days", 1),
    )
    now = datetime.now()
    expiration = now + timedelta(days=default_days)
    
    device["status"] = "booked"
    device["user_id"] = user_id
    device["booking_expiration"] = expiration.isoformat()
    storage.save_devices()
    
    await query.edit_message_text(
        f"✅ Устройство **{device['name']}** (SN: `{device['sn']}`) "
        f"забронировано до {expiration.strftime('%Y-%m-%d %H:%M:%S')}.",
        parse_mode="Markdown",
    )
    # Выход из режима сканирования после действия
    context.user_data.pop("scanning_mode", None)
    
    utils.log_action(
        device["sn"],
        f"Забронировано пользователем {utils.get_user_full_name(user_id)} "
        f"через сканирование до {expiration.strftime('%Y-%m-%d %H:%M:%S')}.",
    )
    
    # Уведомление перед окончанием брони
    notify_before = storage.config.get("notify_before_minutes", 60)
    delta = expiration - datetime.now() - timedelta(minutes=notify_before)
    if delta.total_seconds() > 0:
        context.application.job_queue.run_once(
            notify_booking_expiring,
            when=delta,
            data={
                "chat_id": update.effective_chat.id,
                "device_name": device["name"],
                "sn": device["sn"],
                "expiration": expiration.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )


async def scan_release_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка освобождения устройства через сканирование."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"scan_release_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    device_id = int(match.group(1))
    user_id = update.effective_user.id
    
    device = next(
        (
            d
            for d in storage.devices
            if d.get("id") == device_id
            and d.get("user_id") == user_id
            and d.get("status") == "booked"
        ),
        None,
    )
    
    if not device:
        await query.edit_message_text("❌ Устройство не найдено среди ваших бронирований.")
        return
    
    device["status"] = "free"
    device.pop("user_id", None)
    device.pop("booking_expiration", None)
    storage.save_devices()
    
    utils.log_action(
        device["sn"],
        f"Освобождено пользователем {utils.get_user_full_name(user_id)} через сканирование",
    )
    
    await query.edit_message_text(
        f"✅ Устройство **{device['name']}** (SN: `{device['sn']}`) успешно освобождено.",
        parse_mode="Markdown",
    )
    # Выход из режима сканирования после действия
    context.user_data.pop("scanning_mode", None)


async def scan_transfer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка запроса передачи устройства другому пользователю."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"scan_transfer_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    device_id = int(match.group(1))
    device = next((d for d in storage.devices if d.get("id") == device_id), None)
    
    if not device or device.get("status") != "booked":
        await query.edit_message_text("❌ Устройство не найдено или уже освобождено.")
        return
    
    current_owner_id = device.get("user_id")
    new_owner_id = update.effective_user.id
    
    if current_owner_id == new_owner_id:
        await query.edit_message_text("❌ Это устройство уже забронировано вами.")
        return
    
    # Сохраняем информацию о запросе передачи
    context.user_data["transfer_device_id"] = device_id
    context.user_data["transfer_current_owner"] = current_owner_id
    _set_state(context, BotState.WAITING_TRANSFER_CONFIRMATION)
    
    # Отправляем уведомление текущему владельцу
    current_owner_name = utils.get_user_full_name(new_owner_id)
    device_info = f"**{device['name']}** (SN: `{device['sn']}`)"
    
    transfer_kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Подтвердить передачу",
                    callback_data=f"transfer_confirm_{device_id}_{new_owner_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Отклонить", callback_data=f"transfer_reject_{device_id}_{new_owner_id}"
                )
            ],
        ]
    )
    
    try:
        await context.bot.send_message(
            chat_id=current_owner_id,
            text=(
                f"🔄 Запрос на передачу устройства\n\n"
                f"Пользователь **{current_owner_name}** запрашивает передачу устройства:\n"
                f"{device_info}\n\n"
                f"Подтвердите или отклоните запрос."
            ),
            parse_mode="Markdown",
            reply_markup=transfer_kb,
        )
    except Exception as e:
        await query.edit_message_text(
            f"❌ Не удалось отправить уведомление владельцу устройства. "
            f"Возможно, пользователь не начал диалог с ботом.\n\nОшибка: {str(e)}"
        )
        _set_state(context, BotState.NONE)
        return
    
    await query.edit_message_text(
        f"📨 Запрос на передачу устройства **{device['name']}** отправлен владельцу.\n\n"
        f"Ожидайте подтверждения...",
        parse_mode="Markdown",
    )
    # Выход из режима сканирования после действия
    context.user_data.pop("scanning_mode", None)


async def transfer_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка подтверждения передачи устройства."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"transfer_confirm_(\d+)_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    device_id = int(match.group(1))
    new_owner_id = int(match.group(2))
    current_owner_id = update.effective_user.id
    
    device = next(
        (
            d
            for d in storage.devices
            if d.get("id") == device_id
            and d.get("user_id") == current_owner_id
            and d.get("status") == "booked"
        ),
        None,
    )
    
    if not device:
        await query.edit_message_text("❌ Устройство не найдено или уже освобождено.")
        return
    
    # Проверка лимита для нового владельца
    max_devices = storage.config.get("max_devices_per_user", 2)
    new_owner_count = len(
        [d for d in storage.devices if d.get("user_id") == new_owner_id and d.get("status") == "booked"]
    )
    if new_owner_count >= max_devices:
        await query.edit_message_text(
            f"❌ Новый владелец уже имеет максимальное количество устройств ({max_devices})."
        )
        return
    
    # Передача устройства
    old_owner_name = utils.get_user_full_name(current_owner_id)
    new_owner_name = utils.get_user_full_name(new_owner_id)
    
    device["user_id"] = new_owner_id
    # Сохраняем срок бронирования
    storage.save_devices()
    
    utils.log_action(
        device["sn"],
        f"Передано от {old_owner_name} к {new_owner_name} через сканирование",
    )
    
    await query.edit_message_text(
        f"✅ Устройство **{device['name']}** (SN: `{device['sn']}`) "
        f"передано пользователю **{new_owner_name}**.",
        parse_mode="Markdown",
    )
    
    # Уведомление новому владельцу
    try:
        await context.bot.send_message(
            chat_id=new_owner_id,
            text=(
                f"✅ Устройство передано вам\n\n"
                f"**{device['name']}** (SN: `{device['sn']}`)\n"
                f"Передано от: **{old_owner_name}**"
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass  # Игнорируем ошибки отправки уведомления


async def transfer_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка отклонения передачи устройства."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"transfer_reject_(\d+)_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    device_id = int(match.group(1))
    requester_id = int(match.group(2))
    current_owner_id = update.effective_user.id
    
    device = next((d for d in storage.devices if d.get("id") == device_id), None)
    
    if not device:
        await query.edit_message_text("❌ Устройство не найдено.")
        return
    
    requester_name = utils.get_user_full_name(requester_id)
    device_name = device["name"]
    
    await query.edit_message_text(
        f"❌ Запрос на передачу устройства **{device_name}** отклонен.",
        parse_mode="Markdown",
    )
    
    # Уведомление запросившему
    try:
        await context.bot.send_message(
            chat_id=requester_id,
            text=(
                f"❌ Запрос на передачу устройства **{device_name}** отклонен владельцем."
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass


async def scan_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена действия при сканировании."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Действие отменено.")
    # Выход из режима сканирования
    context.user_data.pop("scanning_mode", None)


# ==========
# Обработчики callback для кнопок устройств
# ==========

async def book_device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка бронирования устройства через кнопку."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"book_dev_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    device_id = int(match.group(1))
    device = next((d for d in storage.devices if d.get("id") == device_id), None)
    
    if not device or device.get("status") != "free":
        await query.edit_message_text("❌ Устройство уже забронировано или не найдено.")
        return
    
    user_id = update.effective_user.id
    
    # Проверка принадлежности к группе (для не-админов)
    if not utils.is_admin(user_id):
        if not utils.can_user_book_device(user_id, device_id):
            user_group = utils.get_user_group(user_id)
            device_group = utils.get_device_group(device_id)
            if not user_group:
                await query.edit_message_text(
                    "❌ У вас не назначена группа. Обратитесь к администратору."
                )
            elif not device_group:
                await query.edit_message_text(
                    "❌ Устройство не назначено ни в какую группу."
                )
            else:
                await query.edit_message_text(
                    f"❌ Вы не можете бронировать устройства из группы '{device_group.get('name')}'. "
                    f"Ваша группа: '{user_group.get('name')}'."
                )
            return
    
    # Проверка лимита устройств
    max_devices = storage.config.get("max_devices_per_user", 2)
    current_count = len(
        [d for d in storage.devices if d.get("user_id") == user_id and d.get("status") == "booked"]
    )
    if current_count >= max_devices:
        await query.edit_message_text(
            f"❌ Нельзя забронировать больше {max_devices} устройств одновременно."
        )
        return
    
    # Бронирование
    default_days = device.get(
        "default_booking_period",
        storage.config.get("default_booking_period_days", 1),
    )
    now = datetime.now()
    expiration = now + timedelta(days=default_days)
    
    device["status"] = "booked"
    device["user_id"] = user_id
    device["booking_expiration"] = expiration.isoformat()
    storage.save_devices()
    
    await query.edit_message_text(
        f"✅ Устройство **{device['name']}** (SN: `{device['sn']}`) "
        f"забронировано до {expiration.strftime('%Y-%m-%d %H:%M:%S')}.",
        parse_mode="Markdown",
    )
    
    utils.log_action(
        device["sn"],
        f"Забронировано пользователем {utils.get_user_full_name(user_id)} "
        f"до {expiration.strftime('%Y-%m-%d %H:%M:%S')}.",
    )


@access_control(required_role="Admin")
async def admin_book_device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка пользователей для бронирования устройства администратором."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"admin_book_dev_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    device_id = int(match.group(1))
    device = next((d for d in storage.devices if d.get("id") == device_id), None)
    
    if not device or device.get("status") != "free":
        await query.answer("Устройство уже забронировано или не найдено.", show_alert=True)
        return
    
    active_users = [u for u in storage.users if u.get("status") == "active"]
    if not active_users:
        await query.message.reply_text("Нет активных пользователей для назначения.")
        return
    
    max_users = 30
    shown_users = active_users[:max_users]
    buttons = []
    for user in shown_users:
        user_id = user.get("user_id")
        if not user_id:
            continue
        full_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user.get("username", f"ID {user_id}")
        if len(full_name) > 32:
            full_name = full_name[:31] + "…"
        buttons.append([
            InlineKeyboardButton(
                f"{full_name} [{user_id}]",
                callback_data=f"admin_book_select_{device_id}_{user_id}",
            )
        ])
    
    if len(active_users) > max_users:
        extra = len(active_users) - max_users
        info_text = f"Показаны первые {max_users} пользователей. Еще: {extra}."
    else:
        info_text = ""
    
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="admin_book_cancel")])
    
    text = (
        f"👑 **Бронирование устройства на пользователя**\n\n"
        f"Устройство: **{device.get('name', 'Неизвестно')}**\n"
        f"SN: `{device.get('sn', 'N/A')}` | Тип: {device.get('type', 'N/A')}\n\n"
        "Выберите пользователя:\n"
    )
    if info_text:
        text += f"\n_{info_text}_"
    
    await query.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@access_control(required_role="Admin")
async def admin_book_select_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает бронирование устройства на выбранного пользователя."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"admin_book_select_(\d+)_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    device_id = int(match.group(1))
    target_user_id = int(match.group(2))
    
    device = next((d for d in storage.devices if d.get("id") == device_id), None)
    target_user = utils.get_user_by_id(target_user_id)
    
    if not device or device.get("status") != "free":
        await query.edit_message_text("❌ Устройство уже забронировано или не найдено.")
        return
    
    if not target_user or target_user.get("status") != "active":
        await query.edit_message_text("❌ Пользователь не найден или не активен.")
        return
    
    default_days = device.get(
        "default_booking_period",
        storage.config.get("default_booking_period_days", 1),
    )
    now = datetime.now()
    expiration = now + timedelta(days=default_days)
    
    device["status"] = "booked"
    device["user_id"] = target_user_id
    device["booking_expiration"] = expiration.isoformat()
    storage.save_devices()
    
    target_name = utils.get_user_full_name(target_user_id)
    admin_name = utils.get_user_full_name(update.effective_user.id)
    
    await query.edit_message_text(
        f"✅ Устройство **{device.get('name', 'N/A')}** (SN: `{device.get('sn', 'N/A')}`)\n"
        f"забронировано на пользователя **{target_name}** до {expiration.strftime('%d.%m.%Y %H:%M')}.\n\n"
        f"Инициатор: {admin_name}",
        parse_mode="Markdown",
    )
    
    utils.log_action(
        device.get("sn", "N/A"),
        f"Админ {admin_name} забронировал на пользователя {target_name} до {expiration.strftime('%Y-%m-%d %H:%M:%S')}.",
    )
    
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=(
                f"👑 Администратор назначил вам устройство **{device.get('name', 'N/A')}** "
                f"(SN: `{device.get('sn', 'N/A')}`) до {expiration.strftime('%d.%m.%Y %H:%M')}."
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass


@access_control(required_role="Admin")
async def admin_book_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена выбора пользователя при админском бронировании."""
    query = update.callback_query
    await query.answer("Отменено")
    await query.edit_message_text("❌ Бронирование отменено.")


async def release_device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка освобождения устройства через кнопку."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"release_dev_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    device_id = int(match.group(1))
    user_id = update.effective_user.id
    
    device = next(
        (
            d
            for d in storage.devices
            if d.get("id") == device_id
            and d.get("user_id") == user_id
            and d.get("status") == "booked"
        ),
        None,
    )
    
    if not device:
        await query.edit_message_text("❌ Устройство не найдено среди ваших бронирований.")
        return
    
    device["status"] = "free"
    device.pop("user_id", None)
    device.pop("booking_expiration", None)
    storage.save_devices()
    
    utils.log_action(
        device["sn"],
        f"Освобождено пользователем {utils.get_user_full_name(user_id)}",
    )
    
    await query.edit_message_text(
        f"✅ Устройство **{device['name']}** (SN: `{device['sn']}`) успешно освобождено.",
        parse_mode="Markdown",
    )


async def info_device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию об устройстве, забронированном другим пользователем."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"info_dev_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    device_id = int(match.group(1))
    device = next((d for d in storage.devices if d.get("id") == device_id), None)
    
    if not device:
        await query.edit_message_text("❌ Устройство не найдено.")
        return
    
    device_user_id = device.get("user_id")
    other_user_name = utils.get_user_full_name(device_user_id)
    expiration = utils.format_datetime(device.get("booking_expiration"))
    
    device_info = (
        f"📱 **{device['name']}**\n"
        f"🔢 SN: `{device['sn']}`\n"
        f"📦 Тип: {device['type']}\n"
        f"🆔 ID: {device['id']}\n\n"
        f"⚠️ Устройство забронировано пользователем: **{other_user_name}**\n"
        f"📅 До: {expiration}\n\n"
        "Вы можете запросить передачу устройства."
    )
    
    kb = [
        [InlineKeyboardButton("🔄 Запросить передачу", callback_data=f"scan_transfer_{device['id']}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")],
    ]
    
    await query.edit_message_text(
        device_info,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def back_to_types_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к списку типов устройств."""
    query = update.callback_query
    await query.answer()
    
    # Вызываем list_devices через создание временного update
    # Проще просто отправить новое сообщение
    user_id = update.effective_user.id
    await query.edit_message_text("Загрузка...")
    
    # Группируем устройства по типам
    types = sorted(set(d.get("type", "Неизвестно") for d in storage.devices))
    
    kb = []
    for dev_type in types:
        count = len([d for d in storage.devices if d.get("type") == dev_type])
        kb.append([InlineKeyboardButton(f"📦 {dev_type} ({count})", callback_data=f"type_{dev_type}")])
    
    text = "📱 Выберите тип устройства:"
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb),
    )
    _set_state(context, BotState.VIEWING_DEVICE_MODELS)


async def back_to_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню."""
    query = update.callback_query
    await query.answer()
    _set_state(context, BotState.NONE)
    
    user_id = update.effective_user.id
    await query.edit_message_text(
        "Главное меню:\n\n"
        "💡 Вы также можете ввести текст для поиска устройств\n"
        "(модель, название, тип, серийный номер)",
        reply_markup=main_menu_keyboard(user_id)
    )


async def select_device_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора типа устройства через inline кнопку."""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    # Извлекаем тип устройства из callback_data
    # Формат: "type_PC", "type_Phone" и т.д.
    if not query.data or not query.data.startswith("type_"):
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    dev_type = query.data[5:]  # Убираем префикс "type_"
    utils.cleanup_expired_bookings()
    user_id = update.effective_user.id
    is_admin = utils.is_admin(user_id)
    
    # Получаем все устройства этого типа и фильтруем по группе пользователя
    all_devices = [d for d in storage.devices if d.get("type") == dev_type]
    devices = utils.filter_devices_by_user_group(user_id, all_devices)
    
    if not devices:
        await query.edit_message_text(
            f"Нет устройств типа {dev_type}.\n\n"
            f"Debug: callback_data = {query.data}"
        )
        return

    # Группируем по моделям (name)
    models = {}
    for d in devices:
        model_name = d.get("name", "Неизвестно")
        if model_name not in models:
            models[model_name] = []
        models[model_name].append(d)
    
    # Формируем сообщение с моделями и кнопками
    lines = [f"📦 **{dev_type}**\n"]
    inline_buttons = []
    
    for model_name in sorted(models.keys()):
        model_devices = models[model_name]
        free_count = len([d for d in model_devices if d.get("status") == "free"])
        total_count = len(model_devices)
        
        status_text = f"✅ {free_count}/{total_count} свободно" if free_count > 0 else "🔒 Все забронированы"
        lines.append(f"📱 **{model_name}** - {status_text}")
        
        # Добавляем кнопки для каждого устройства этой модели
        for device in sorted(model_devices, key=lambda x: x.get("sn", "")):
            device_status = device.get("status", "free")
            device_user_id = device.get("user_id")
            sn = device.get("sn", "N/A")
            group_name = _group_label(device.get("group_id"))
            
            if device_status == "free":
                # Кнопка забронировать
                row = [
                    InlineKeyboardButton(
                        f"✅ {model_name} (SN: {sn})",
                        callback_data=f"book_dev_{device['id']}"
                    )
                ]
                if is_admin:
                    row.append(
                        InlineKeyboardButton(
                            "👑 На пользователя",
                            callback_data=f"admin_book_dev_{device['id']}",
                        )
                    )
                inline_buttons.append(row)
            elif device_user_id == user_id:
                # Кнопка освободить (если забронировано пользователем)
                expiration = utils.format_datetime(device.get("booking_expiration"))
                inline_buttons.append([
                    InlineKeyboardButton(
                        f"🔓 {model_name} (SN: {sn}) - Освободить",
                        callback_data=f"release_dev_{device['id']}"
                    )
                ])
            else:
                # Устройство забронировано другим - показываем информацию
                other_user = utils.get_user_full_name(device_user_id)
                expiration = utils.format_datetime(device.get("booking_expiration"))
                inline_buttons.append([
                    InlineKeyboardButton(
                        f"🔒 {model_name} (SN: {sn}) - Забронировано",
                        callback_data=f"info_dev_{device['id']}"
                    )
                ])
    
    text = "\n".join(lines)
    
    if inline_buttons:
        inline_buttons.append([InlineKeyboardButton("◀️ Назад к типам", callback_data="back_to_types")])
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_buttons),
        )
    else:
        await query.edit_message_text(
            text + "\n\nНет доступных действий.",
            parse_mode="Markdown",
        )


async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка данных от Web App (сканер)."""
    print("=== handle_web_app_data вызван ===")
    
    # Проверяем наличие web_app_data
    if not update.message:
        print("Нет update.message")
        return
    
    print(f"update.message type: {type(update.message)}")
    print(f"update.message attributes: {dir(update.message)}")
    
    # В python-telegram-bot 20.x web_app_data может быть в разных местах
    web_app_data = None
    if hasattr(update.message, 'web_app_data') and update.message.web_app_data:
        web_app_data = update.message.web_app_data
        print(f"Найден web_app_data через web_app_data: {web_app_data}")
    elif hasattr(update.message, 'data') and update.message.data:
        # Альтернативный способ получения данных
        web_app_data = type('obj', (object,), {'data': update.message.data})()
        print(f"Найден web_app_data через data: {update.message.data}")
    else:
        print("web_app_data не найден. Проверяем все возможные атрибуты:")
        for attr in dir(update.message):
            if 'web' in attr.lower() or 'app' in attr.lower() or 'data' in attr.lower():
                try:
                    value = getattr(update.message, attr, None)
                    print(f"  {attr}: {value}")
                except:
                    pass
    
    if not web_app_data:
        print("web_app_data не найден, возвращаемся")
        # Пробуем получить данные напрямую из update
        if hasattr(update, 'web_app_data'):
            print(f"Найден web_app_data в update: {update.web_app_data}")
            web_app_data = update.web_app_data
        else:
            print("web_app_data не найден нигде")
            return
    
    # Проверяем доступ пользователя
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        print("Нет user_id")
        return
    
    print(f"User ID: {user_id}")
    
    db_user = utils.get_user_by_id(user_id)
    if not db_user or db_user.get("status") != "active":
        print(f"Пользователь не активен: {db_user}")
        await update.message.reply_text(
            "Вы не зарегистрированы или не активированы. Используйте /register для регистрации."
        )
        return
    
    scanning_mode = context.user_data.get("scanning_mode", False)
    print(f"scanning_mode: {scanning_mode}")
    if not scanning_mode:
        print("scanning_mode = False, запрашиваем активацию")
        await update.message.reply_text(
            "Пожалуйста, сначала нажмите '📷 Сканирование' в главном меню."
        )
        return
    
    try:
        # Получаем данные от Web App
        data_str = web_app_data.data
        print(f"Получены данные от Web App (строка): {data_str[:200]}...")
        
        data = json.loads(data_str)
        print(f"Распарсенные данные: {data}")
        
        data_type = data.get("type")
        print(f"Тип данных: {data_type}")
        
        if data_type == "code":
            # Получен код от QR-сканера
            code = data.get("data", "").strip()
            print(f"Извлеченный код: '{code}'")
            
            if code:
                # Отправляем подтверждение получения
                processing_msg = await update.message.reply_text(
                    f"✅ Получен код: `{code}`\n\n🔍 Ищу устройство...",
                    parse_mode="Markdown"
                )
                print(f"Отправлено подтверждение, вызываем _process_code_directly с кодом: '{code}'")
                # Обрабатываем как обычный код напрямую
                await _process_code_directly(update, context, code, message_for_reply=processing_msg)
                print("_process_code_directly завершен")
            else:
                print("Код пустой")
                await update.message.reply_text("Код не распознан. Попробуйте еще раз.")
        
        elif data_type == "photo":
            # Получено фото от камеры
            photo_data = data.get("data", "")
            if not photo_data:
                await update.message.reply_text("❌ Фото не получено. Попробуйте еще раз.")
                return
            
            # Удаляем префикс data:image/jpeg;base64, если есть
            if "," in photo_data:
                photo_data = photo_data.split(",")[1]
            
            # Проверяем размер данных
            data_size = len(photo_data)
            estimated_size = int(data_size * 3 / 4)  # Примерный размер в байтах
            print(f"Получено фото от Web App: размер base64={data_size}, примерный размер={estimated_size} байт")
            
            if estimated_size > 100000:  # Больше 100KB
                await update.message.reply_text(
                    "❌ Изображение слишком большое. Попробуйте сфотографировать ближе к тексту или используйте ручной ввод."
                )
                return
            
            try:
                # Декодируем base64
                photo_bytes = base64.b64decode(photo_data, validate=True)
                print(f"Фото декодировано: размер={len(photo_bytes)} байт")
                
                # Обрабатываем фото
                processing_msg = await update.message.reply_text("🔍 Обработка фото... Пожалуйста, подождите.")
                
                # Пытаемся распознать текст с помощью OCR
                recognized_text = await _recognize_text_from_photo(photo_bytes)
                
                if recognized_text:
                    print(f"OCR распознал текст: {recognized_text[:100]}...")
                    # Ищем серийный номер в распознанном тексте
                    serial_number = _extract_serial_number(recognized_text)
                    
                    if serial_number:
                        await processing_msg.edit_text(
                            f"✅ Распознан серийный номер: **{serial_number}**\n\n"
                            f"Распознанный текст: `{recognized_text[:100]}...`",
                            parse_mode="Markdown"
                        )
                        
                        # Обрабатываем найденный серийный номер как код напрямую
                        await _process_code_directly(update, context, serial_number, message_for_reply=processing_msg)
                        return
                    else:
                        await processing_msg.edit_text(
                            f"⚠️ Текст распознан, но серийный номер не найден.\n\n"
                            f"Распознанный текст: `{recognized_text[:200]}`\n\n"
                            f"Пожалуйста, введите серийный номер вручную.",
                            parse_mode="Markdown"
                        )
                        return
                else:
                    await processing_msg.edit_text(
                        "⚠️ Не удалось распознать текст на фото.\n\n"
                        "Пожалуйста, введите серийный номер вручную или попробуйте еще раз.\n\n"
                        "_Убедитесь, что текст на фото четкий и хорошо виден._",
                        parse_mode="Markdown"
                    )
                    return
                    
            except binascii.Error as e:
                print(f"Ошибка декодирования base64: {e}")
                await update.message.reply_text(
                    "❌ Ошибка: неверный формат изображения. Попробуйте еще раз."
                )
                return
            except Exception as e:
                print(f"Ошибка при обработке фото: {e}")
                await update.message.reply_text(
                    f"❌ Ошибка при обработке фото: {str(e)}\n\n"
                    "Пожалуйста, введите серийный номер вручную."
                )
        else:
            print(f"Неизвестный тип данных: {data_type}")
            await update.message.reply_text(f"❌ Неизвестный тип данных: {data_type}")
            
    except json.JSONDecodeError as e:
        print(f"Ошибка JSON декодирования: {e}")
        print(f"Данные, которые не удалось распарсить: {data_str[:500] if 'data_str' in locals() else 'N/A'}")
        await update.message.reply_text(
            f"❌ Ошибка при обработке данных от Web App (неверный формат JSON).\n\n"
            f"Попробуйте еще раз или используйте другой способ сканирования."
        )
    except Exception as e:
        print(f"Общая ошибка в handle_web_app_data: {e}")
        import traceback
        traceback.print_exc()
        await update.message.reply_text(
            f"❌ Ошибка при обработке данных: {str(e)}\n\n"
            f"Попробуйте еще раз или используйте другой способ сканирования."
        )


# ==========
# Управление группами
# ==========

@access_control(required_role="Admin")
async def manage_groups_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню управления группами."""
    query = update.callback_query
    if query:
        await query.answer()
        msg = query.message
    else:
        msg = update.message
    
    if not storage.groups:
        inline_buttons = [
            [InlineKeyboardButton("➕ Создать группу", callback_data="add_group")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin")]
        ]
        text = "👥 **Управление группами**\n\nПока нет групп. Создайте первую группу:"
    else:
        inline_buttons = []
        for group in sorted(storage.groups, key=lambda x: x.get("id", 0)):
            group_id = group.get("id")
            group_name = group.get("name", "Без названия")
            # Подсчитываем пользователей и устройства в группе
            users_count = len([u for u in storage.users if u.get("group_id") == group_id])
            devices_count = len([d for d in storage.devices if d.get("group_id") == group_id])
            inline_buttons.append([
                InlineKeyboardButton(
                    f"👥 {group_name} ({users_count} пользователей, {devices_count} устройств)",
                    callback_data=f"edit_group_{group_id}"
                )
            ])
        
        inline_buttons.append([InlineKeyboardButton("➕ Создать группу", callback_data="add_group")])
        inline_buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin")])
        
        text = f"👥 **Управление группами**\n\nВсего групп: {len(storage.groups)}\n\nВыберите группу для редактирования:"
    
    if query:
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_buttons),
        )
    else:
        await msg.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_buttons),
        )


@access_control(required_role="Admin")
async def add_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса создания группы."""
    query = update.callback_query
    await query.answer()
    
    _set_state(context, BotState.ADDING_GROUP_NAME)
    await query.edit_message_text(
        "➕ **Создание новой группы**\n\n"
        "Введите название группы:",
        parse_mode="Markdown"
    )


@access_control(required_role="Admin")
async def edit_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактирование группы."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"edit_group_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    group_id = int(match.group(1))
    group = utils.get_group_by_id(group_id)
    
    if not group:
        await query.edit_message_text("❌ Группа не найдена.")
        return
    
    group_name = group.get("name", "Без названия")
    users_count = len([u for u in storage.users if u.get("group_id") == group_id])
    devices_count = len([d for d in storage.devices if d.get("group_id") == group_id])
    
    inline_buttons = [
        [InlineKeyboardButton("✏️ Изменить название", callback_data=f"rename_group_{group_id}")],
        [InlineKeyboardButton("👥 Назначить пользователям", callback_data=f"assign_group_users_{group_id}")],
        [InlineKeyboardButton("📱 Назначить устройствам", callback_data=f"assign_group_devices_{group_id}")],
        [InlineKeyboardButton("🗑️ Удалить группу", callback_data=f"delete_group_{group_id}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="manage_groups_admin")]
    ]
    
    text = (
        f"👥 **Группа: {group_name}**\n\n"
        f"🆔 ID: {group_id}\n"
        f"👥 Пользователей: {users_count}\n"
        f"📱 Устройств: {devices_count}\n\n"
        f"Выберите действие:"
    )
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_buttons),
    )


@access_control(required_role="Admin")
async def delete_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление группы."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"delete_group_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    group_id = int(match.group(1))
    group = utils.get_group_by_id(group_id)
    
    if not group:
        await query.edit_message_text("❌ Группа не найдена.")
        return
    
    group_name = group.get("name", "Без названия")
    
    # Удаляем группу из пользователей и устройств
    users_updated = 0
    devices_updated = 0
    for user in storage.users:
        if user.get("group_id") == group_id:
            user.pop("group_id", None)
            users_updated += 1
    
    for device in storage.devices:
        if device.get("group_id") == group_id:
            device.pop("group_id", None)
            devices_updated += 1
    
    # Удаляем группу
    storage.groups.remove(group)
    storage.save_groups()
    storage.save_users()
    storage.save_devices()
    
    await query.edit_message_text(
        f"✅ Группа '{group_name}' удалена.\n\n"
        f"У {users_updated} пользователей и {devices_updated} устройств снята принадлежность к группе."
    )
    
    # Возвращаемся к списку групп
    await manage_groups_admin(update, context)


@access_control(required_role="Admin")
async def rename_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса переименования группы."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"rename_group_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    group_id = int(match.group(1))
    group = utils.get_group_by_id(group_id)
    
    if not group:
        await query.edit_message_text("❌ Группа не найдена.")
        return
    
    context.user_data["rename_group_id"] = group_id
    _set_state(context, BotState.ADDING_GROUP_NAME)
    
    await query.edit_message_text(
        f"✏️ **Переименование группы**\n\n"
        f"Текущее название: {group.get('name')}\n\n"
        f"Введите новое название группы:",
        parse_mode="Markdown"
    )


@access_control(required_role="Admin")
async def assign_group_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Назначение/снятие пользователей группы."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"assign_group_users_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    group_id = int(match.group(1))
    await _render_group_assignment(query, group_id, mode="users")


@access_control(required_role="Admin")
async def assign_group_devices_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Назначение/снятие устройств группы."""
    query = update.callback_query
    await query.answer()
    
    match = re.match(r"assign_group_devices_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    group_id = int(match.group(1))
    await _render_group_assignment(query, group_id, mode="devices")


@access_control(required_role="Admin")
async def toggle_group_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает принадлежность пользователя к группе."""
    query = update.callback_query
    
    match = re.match(r"toggle_group_user_(\d+)_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    group_id = int(match.group(1))
    user_id = int(match.group(2))
    
    group = utils.get_group_by_id(group_id)
    user = utils.get_user_by_id(user_id)
    
    if not group or not user:
        await query.edit_message_text("❌ Группа или пользователь не найдены.")
        return
    
    current_group_id = user.get("group_id")
    if current_group_id == group_id:
        user.pop("group_id", None)
        response = f"Пользователь {utils.get_user_full_name(user_id)} удален из группы."
    else:
        user["group_id"] = group_id
        response = f"Пользователь {utils.get_user_full_name(user_id)} назначен в группу '{group.get('name')}'."
    storage.save_users()
    
    await query.answer(response[:200])
    await _render_group_assignment(query, group_id, mode="users")


@access_control(required_role="Admin")
async def toggle_group_device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает принадлежность устройства к группе."""
    query = update.callback_query
    
    match = re.match(r"toggle_group_device_(\d+)_(\d+)", query.data)
    if not match:
        await query.edit_message_text("Ошибка: некорректный формат команды.")
        return
    
    group_id = int(match.group(1))
    device_id = int(match.group(2))
    
    group = utils.get_group_by_id(group_id)
    device = next((d for d in storage.devices if d.get("id") == device_id), None)
    
    if not group or not device:
        await query.edit_message_text("❌ Группа или устройство не найдены.")
        return
    
    current_group_id = device.get("group_id")
    if current_group_id == group_id:
        device.pop("group_id", None)
        response = f"Устройство {device.get('name')} удалено из группы."
    else:
        device["group_id"] = group_id
        response = f"Устройство {device.get('name')} назначено в группу '{group.get('name')}'."
    storage.save_devices()
    
    await query.answer(response[:200])
    await _render_group_assignment(query, group_id, mode="devices")


async def _render_group_assignment(query, group_id: int, mode: str) -> None:
    """Показывает список пользователей/устройств для назначения группе."""
    group = utils.get_group_by_id(group_id)
    if not group:
        await query.edit_message_text("❌ Группа не найдена.")
        return
    
    group_name = group.get("name", "Без названия")
    inline_buttons = []
    
    def _shorten(text: str, limit: int = 32) -> str:
        return text if len(text) <= limit else text[: limit - 1] + "…"
    
    if mode == "users":
        items = sorted(
            storage.users,
            key=lambda u: (u.get("first_name", ""), u.get("last_name", ""), u.get("user_id", 0)),
        )
        if not items:
            text = (
                f"👥 **Группа: {group_name}**\n\n"
                "Нет пользователей. Добавьте пользователей перед назначением в группу."
            )
        else:
            lines = [
                f"👥 **Группа: {group_name}**",
                "📝 Нажмите на пользователя, чтобы добавить или убрать из группы.",
                "✅ — в группе, 🔁 — в другой группе, ➕ — без группы.",
                "",
            ]
            inline_buttons = []
            for user in items:
                user_id = user.get("user_id")
                if not user_id:
                    continue
                full_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user.get("username", "Без имени")
                full_name = _shorten(full_name)
                current_group_id = user.get("group_id")
                if current_group_id == group_id:
                    prefix = "✅"
                elif current_group_id:
                    other_group = utils.get_group_by_id(current_group_id)
                    other_name = other_group.get("name") if other_group else "Другая группа"
                    prefix = "🔁"
                    full_name = f"{full_name} • {_shorten(other_name, 14)}"
                else:
                    prefix = "➕"
                inline_buttons.append([
                    InlineKeyboardButton(
                        f"{prefix} {full_name} [{user_id}]",
                        callback_data=f"toggle_group_user_{group_id}_{user_id}",
                    )
                ])
            text = "\n".join(lines)
    else:  # devices
        items = sorted(
            storage.devices,
            key=lambda d: (d.get("type", ""), d.get("name", ""), d.get("sn", "")),
        )
        if not items:
            text = (
                f"📱 **Группа: {group_name}**\n\n"
                "Нет устройств. Добавьте устройства перед назначением в группу."
            )
        else:
            lines = [
                f"📱 **Группа: {group_name}**",
                "📝 Нажмите на устройство, чтобы добавить или убрать из группы.",
                "✅ — в группе, 🔁 — в другой группе, ➕ — без группы.",
                "",
            ]
            inline_buttons = []
            for device in items:
                device_id = device.get("id")
                if device_id is None:
                    continue
                name = _shorten(device.get("name", "Без названия"))
                sn = device.get("sn", "N/A")
                current_group_id = device.get("group_id")
                if current_group_id == group_id:
                    prefix = "✅"
                elif current_group_id:
                    other_group = utils.get_group_by_id(current_group_id)
                    other_name = other_group.get("name") if other_group else "Другая группа"
                    prefix = "🔁"
                    name = f"{name} • {_shorten(other_name, 14)}"
                else:
                    prefix = "➕"
                inline_buttons.append([
                    InlineKeyboardButton(
                        f"{prefix} {name} (SN: {sn})",
                        callback_data=f"toggle_group_device_{group_id}_{device_id}",
                    )
                ])
            text = "\n".join(lines)
    
    inline_buttons.append([InlineKeyboardButton("◀️ Назад", callback_data=f"edit_group_{group_id}")])
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_buttons),
    )


# ==========
# Неизвестные сообщения
# ==========

async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем, не является ли это кодом для сканирования
    state = _get_state(context)
    scanning_mode = context.user_data.get("scanning_mode", False)
    
    # Если пользователь в режиме сканирования и отправлено фото
    # (на случай, если обработчик фото не сработал)
    if scanning_mode and update.message and update.message.photo:
        # Пытаемся обработать фото через handle_photo_scan
        # Но сначала проверяем доступ через access_control
        user_id = update.effective_user.id if update.effective_user else None
        if user_id:
            db_user = utils.get_user_by_id(user_id)
            if db_user and db_user.get("status") == "active":
                await handle_photo_scan(update, context)
                return
    
    # Если пользователь в режиме сканирования и отправлено фото, но доступ не разрешен
    if scanning_mode and update.message and update.message.photo:
        await update.message.reply_text(
            "Для использования сканирования необходимо быть зарегистрированным пользователем.\n"
            "Используйте /register для регистрации."
        )
        return

    if state == BotState.SELECTING_REG_GROUP and update.message and update.message.text:
        await update.message.reply_text(
            "Пожалуйста, выберите группу, используя кнопки под предыдущим сообщением.\n"
            "Отправьте /start для отмены регистрации."
        )
        return
    
    # Если пользователь в режиме сканирования или сообщение похоже на код
    if state == BotState.NONE and update.message and update.message.text:
        text = update.message.text.strip()
        # Проверяем, что это не команда
        if text and not text.startswith("/") and len(text) > 0:
            # Проверяем, что это не известная команда
            known_patterns = [
                "Назад", "Главное меню", "Список устройств", "Бронирование",
                "Мои устройства", "Администрирование", "📷 Сканирование",
                "Просмотр забронированных устройств", "Управление устройствами",
                "Управление пользователями", "Импортировать устройства",
                "Экспорт устройств CSV", "Экспорт пользователей CSV", "Экспорт логов CSV",
                "Включить регистрацию", "Выключить регистрацию"
            ]
            if text not in known_patterns and not any(
                pattern in text for pattern in [" - ID ", "Освободить", "Управление", "Экспорт"]
            ):
                # Если в режиме сканирования - обрабатываем как код
                if scanning_mode:
                    if any(c.isalnum() for c in text) and len(text) <= 50:
                        await handle_code_scan(update, context)
                        return
                else:
                    # Если не в режиме сканирования - ищем устройства по тексту
                    await search_devices(update, context)
                    return
    
    await update.message.reply_text(
        "Неизвестная команда/сообщение. Используйте кнопки или /help."
    )
