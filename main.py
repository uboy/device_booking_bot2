from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import storage
from handlers import (
    add_device_callback,
    add_group_callback,
    add_user_callback,
    admin_all_devices_callback,
    admin_book_cancel_callback,
    admin_book_device_callback,
    admin_book_select_user_callback,
    admin_devices_text,
    admin_panel,
    admin_release_callback,
    admin_type_callback,
    admin_users_text,
    approve_user_callback,
    assign_group_devices_callback,
    assign_group_users_callback,
    back_to_admin_callback,
    back_to_main_callback,
    back_to_types_callback,
    book_device_callback,
    book_device_menu,
    book_specific_device,
    delete_device_callback,
    delete_group_callback,
    delete_user_callback,
    edit_device_callback,
    edit_group_callback,
    edit_user_callback,
    block_user_callback,
    unblock_user_callback,
    export_devices,
    export_devices_callback,
    export_logs,
    export_logs_callback,
    export_users,
    export_users_callback,
    go_back,
    handle_code_scan,
    handle_photo_scan,
    handle_state_message,
    handle_state_user_message,
    handle_web_app_data,
    help_command,
    import_devices_csv,
    info_device_callback,
    list_all_users_callback,
    list_devices,
    manage_devices,
    manage_devices_admin_callback,
    manage_devices_callback,
    manage_groups_admin,
    manage_users,
    manage_users_admin_callback,
    manage_users_callback,
    my_devices,
    process_devices_csv,
    register_group_select_callback,
    register_user,
    release_all_user_devices,
    release_device_callback,
    release_device_text,
    reject_user_callback,
    rename_group_callback,
    scan_book_callback,
    scan_cancel_callback,
    scan_code_menu,
    scan_release_callback,
    scan_transfer_callback,
    search_devices,
    set_name_command,
    select_device_type,
    select_device_type_callback,
    show_admin_devices_by_type,
    start_menu,
    toggle_group_device_callback,
    toggle_group_user_callback,
    toggle_registration,
    transfer_confirm_callback,
    transfer_reject_callback,
    unknown_message,
    view_all_booked,
    view_booked_admin_callback,
)


def _register_handlers(app: Application) -> None:
    """Регистрирует все хендлеры в одном месте, без дублирования."""
    # Команды
    app.add_handler(CommandHandler("start", start_menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("register", register_user))
    app.add_handler(CommandHandler("set_name", set_name_command))

    # Кнопки навигации
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Назад$"), go_back))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Главное меню$"), start_menu))

    # Пользовательские действия
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Список устройств$"), list_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Бронирование$"), book_device_menu))
    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex("^(" + "|".join(storage.config["device_types"]) + ")$"),
            select_device_type,
        )
    )
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r".* - ID \d+$"), book_specific_device))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Мои устройства$"), my_devices))
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex(r"^Освободить .* \(SN: .*?\)$"), release_device_text)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex("^Освободить все устройства$"), release_all_user_devices)
    )

    # Сканирование QR/штрих-кодов
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^.*Сканирование$"), scan_code_menu))
    app.add_handler(CallbackQueryHandler(scan_book_callback, pattern="^scan_book_.*"))
    app.add_handler(CallbackQueryHandler(scan_release_callback, pattern="^scan_release_.*"))
    app.add_handler(CallbackQueryHandler(scan_transfer_callback, pattern="^scan_transfer_.*"))
    app.add_handler(CallbackQueryHandler(transfer_confirm_callback, pattern="^transfer_confirm_.*"))
    app.add_handler(CallbackQueryHandler(transfer_reject_callback, pattern="^transfer_reject_.*"))
    app.add_handler(CallbackQueryHandler(scan_cancel_callback, pattern="^scan_cancel$"))

    # Обработчики кнопок устройств
    app.add_handler(CallbackQueryHandler(book_device_callback, pattern="^book_dev_.*"))
    app.add_handler(CallbackQueryHandler(admin_book_device_callback, pattern="^admin_book_dev_.*"))
    app.add_handler(CallbackQueryHandler(admin_book_select_user_callback, pattern="^admin_book_select_.*"))
    app.add_handler(CallbackQueryHandler(admin_book_cancel_callback, pattern="^admin_book_cancel$"))
    app.add_handler(CallbackQueryHandler(release_device_callback, pattern="^release_dev_.*"))
    app.add_handler(CallbackQueryHandler(info_device_callback, pattern="^info_dev_.*"))
    app.add_handler(CallbackQueryHandler(back_to_types_callback, pattern="^back_to_types$"))
    app.add_handler(CallbackQueryHandler(back_to_main_callback, pattern="^back_to_main$"))
    app.add_handler(CallbackQueryHandler(select_device_type_callback, pattern="^type_.*"))
    app.add_handler(CallbackQueryHandler(register_group_select_callback, pattern="^reg_group_.*"))

    # Админ-панель
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Администрирование$"), admin_panel))
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex("^Просмотр забронированных устройств$"), view_all_booked)
    )
    app.add_handler(CallbackQueryHandler(admin_release_callback, pattern="^adm_rel_.*"))
    app.add_handler(CallbackQueryHandler(manage_devices_admin_callback, pattern="^manage_devices_admin$"))
    app.add_handler(CallbackQueryHandler(admin_type_callback, pattern="^admin_type_.*"))
    app.add_handler(CallbackQueryHandler(admin_all_devices_callback, pattern="^admin_all_devices$"))
    app.add_handler(CallbackQueryHandler(manage_users_admin_callback, pattern="^manage_users_admin$"))
    app.add_handler(CallbackQueryHandler(manage_users_callback, pattern="^manage_users$"))
    app.add_handler(CallbackQueryHandler(view_booked_admin_callback, pattern="^view_booked_admin$"))
    app.add_handler(CallbackQueryHandler(add_device_callback, pattern="^add_device$"))
    app.add_handler(CallbackQueryHandler(edit_device_callback, pattern="^edit_device_.*"))
    app.add_handler(CallbackQueryHandler(delete_device_callback, pattern="^delete_device_.*"))
    app.add_handler(CallbackQueryHandler(export_devices_callback, pattern="^export_devices_admin$"))
    app.add_handler(CallbackQueryHandler(export_users_callback, pattern="^export_users_admin$"))
    app.add_handler(CallbackQueryHandler(export_logs_callback, pattern="^export_logs_admin$"))
    app.add_handler(CallbackQueryHandler(manage_groups_admin, pattern="^manage_groups_admin$"))
    app.add_handler(CallbackQueryHandler(toggle_registration, pattern="^toggle_registration$"))
    app.add_handler(CallbackQueryHandler(import_devices_csv, pattern="^import_devices_admin$"))
    app.add_handler(CallbackQueryHandler(approve_user_callback, pattern="^approve_user_.*"))
    app.add_handler(CallbackQueryHandler(reject_user_callback, pattern="^reject_user_.*"))
    app.add_handler(CallbackQueryHandler(block_user_callback, pattern="^block_user_.*"))
    app.add_handler(CallbackQueryHandler(unblock_user_callback, pattern="^unblock_user_.*"))
    app.add_handler(CallbackQueryHandler(add_user_callback, pattern="^add_user$"))
    app.add_handler(CallbackQueryHandler(edit_user_callback, pattern="^edit_user_.*"))
    app.add_handler(CallbackQueryHandler(delete_user_callback, pattern="^delete_user_.*"))
    app.add_handler(CallbackQueryHandler(list_all_users_callback, pattern="^list_all_users$"))
    app.add_handler(CallbackQueryHandler(back_to_admin_callback, pattern="^back_to_admin$"))
    app.add_handler(CallbackQueryHandler(add_group_callback, pattern="^add_group$"))
    app.add_handler(CallbackQueryHandler(edit_group_callback, pattern="^edit_group_.*"))
    app.add_handler(CallbackQueryHandler(delete_group_callback, pattern="^delete_group_.*"))
    app.add_handler(CallbackQueryHandler(rename_group_callback, pattern="^rename_group_.*"))
    app.add_handler(CallbackQueryHandler(assign_group_users_callback, pattern="^assign_group_users_.*"))
    app.add_handler(CallbackQueryHandler(assign_group_devices_callback, pattern="^assign_group_devices_.*"))
    app.add_handler(CallbackQueryHandler(toggle_group_user_callback, pattern="^toggle_group_user_.*"))
    app.add_handler(CallbackQueryHandler(toggle_group_device_callback, pattern="^toggle_group_device_.*"))

    # Управление устройствами
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Управление устройствами$"), manage_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^(add|del|rename).*$"), admin_devices_text))
    app.add_handler(
        MessageHandler(
            filters.Document.FileExtension("csv")
            | filters.Document.FileExtension("xlsx")
            | filters.Document.FileExtension("xls"),
            process_devices_csv,
        )
    )
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Импортировать устройства$"), import_devices_csv))

    # Управление пользователями
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Управление пользователями$"), manage_users))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Управление группами$"), manage_groups_admin))
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex("^(approve|reject|adduser|edituser|deluser).*$"), admin_users_text)
    )

    # Переключение регистрации
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex("^(Включить|Выключить) регистрацию$"), toggle_registration)
    )

    # Экспорт
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Экспорт устройств CSV$"), export_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Экспорт пользователей CSV$"), export_users))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Экспорт логов CSV$"), export_logs))

    # FSM-сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_state_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_state_user_message))

    # Обработка фото/данных WebApp
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_scan))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))

    # Неизвестные сообщения - в самом конце
    app.add_handler(MessageHandler(filters.ALL, unknown_message))


def _build_app() -> Application:
    storage.load_all()
    token = storage.config.get("bot_token")
    if not token or token == "PUT_YOUR_TOKEN_HERE":
        raise RuntimeError("Bot token is not configured in config.json")
    logging.info(
        "Config loaded: admins=%s, device_types=%s, registration_enabled=%s, default_booking_period_days=%s, "
        "max_devices_per_user=%s, notify_before_minutes=%s, webapp_url=%s",
        storage.config.get("admin_ids"),
        storage.config.get("device_types"),
        storage.config.get("registration_enabled"),
        storage.config.get("default_booking_period_days"),
        storage.config.get("max_devices_per_user"),
        storage.config.get("notify_before_minutes"),
        storage.config.get("webapp_url"),
    )
    app = Application.builder().token(token).build()
    _register_handlers(app)
    return app


def main() -> None:
    from telegram.error import NetworkError, TimedOut

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    app = _build_app()

    try:
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            close_loop=False,
        )
    except (NetworkError, TimedOut) as e:
        logging.error(f"Network error occurred: {e}")
        logging.info("Bot will attempt to reconnect automatically...")
    except Exception as e:  # noqa: BLE001
        logging.error(f"Unexpected error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
