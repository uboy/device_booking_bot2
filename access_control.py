from __future__ import annotations

from typing import Optional

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

import utils
import storage


def _main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    keyboard = [
        ["Список устройств", "Бронирование"],
        ["Мои устройства", "📷 Сканирование"],
    ]
    if utils.is_admin(user_id):
        keyboard.append(["Администрирование"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def access_control(required_status: str = "active", required_role: Optional[str] = None, allow_unregistered: bool = False):
    """
    Декоратор для проверки:
    - есть ли пользователь в users.json,
    - статус (active/pending),
    - роль (Admin), если указана.
    Работает и для сообщений, и для callback'ов.
    """

    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user = update.effective_user
            user_id = user.id if user else None

            is_callback = update.callback_query is not None
            msg = update.callback_query.message if is_callback else update.message

            if user_id is None or msg is None:
                return

            db_user = utils.get_user_by_id(user_id)

            # Авто-регистрация админа по списку admin_ids из config.json
            if not db_user and user_id in storage.config.get("admin_ids", []):
                db_user = {
                    "user_id": user_id,
                    "username": user.username if user else "unknown",
                    "first_name": user.first_name if user else "",
                    "last_name": user.last_name if user else "",
                    "role": "Admin",
                    "status": "active",
                }
                storage.users.append(db_user)
                storage.save_users()

            if not db_user:
                if not allow_unregistered:
                    await msg.reply_text(
                        "Вы не зарегистрированы. Используйте /register для отправки заявки.",
                        reply_markup=ReplyKeyboardMarkup([["/help"]], resize_keyboard=True),
                    )
                    return
                else:
                    return await func(update, context, *args, **kwargs)

            # Игнорируем заблокированных пользователей
            if db_user.get("status") == "blocked":
                return

            status = db_user.get("status")
            if required_status and status != required_status:
                await msg.reply_text(
                    f"Ваш статус: {status}. "
                    f"Доступ разрешён только для пользователей со статусом: {required_status}.",
                    reply_markup=ReplyKeyboardMarkup([["/help"]], resize_keyboard=True),
                )
                return

            if required_role:
                role = db_user.get("role")
                if not (
                    role == required_role
                    or (required_role == "Admin" and utils.is_admin(user_id))
                ):
                    await msg.reply_text(
                        f"Доступ к этой функции разрешён только для пользователей с ролью: {required_role}.",
                        reply_markup=_main_menu_keyboard(user_id),
                    )
                    return

            return await func(update, context, *args, **kwargs)

        return wrapper

    return decorator


def main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    return _main_menu_keyboard(user_id)
