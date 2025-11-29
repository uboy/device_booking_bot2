from __future__ import annotations

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram import Update

import storage
from handlers import (
    help_command,
    start_menu,
    register_user,
    go_back,
    list_devices,
    book_device_menu,
    select_device_type,
    book_specific_device,
    my_devices,
    release_device_text,
    release_all_user_devices,
    admin_panel,
    view_all_booked,
    view_booked_admin_callback,
    admin_release_callback,
    manage_devices,
    manage_devices_callback,
    manage_devices_admin_callback,
    admin_type_callback,
    admin_all_devices_callback,
    show_admin_devices_by_type,
    add_device_callback,
    edit_device_callback,
    delete_device_callback,
    admin_devices_text,
    handle_state_message,
    import_devices_csv,
    process_devices_csv,
    manage_users,
    manage_users_callback,
    manage_users_admin_callback,
    list_all_users_callback,
    add_user_callback,
    approve_user_callback,
    reject_user_callback,
    edit_user_callback,
    delete_user_callback,
    back_to_admin_callback,
    admin_users_text,
    handle_state_user_message,
    toggle_registration,
    export_devices,
    export_devices_callback,
    export_users,
    export_users_callback,
    export_logs,
    export_logs_callback,
    scan_code_menu,
    handle_code_scan,
    handle_photo_scan,
    handle_web_app_data,
    search_devices,
    scan_book_callback,
    scan_release_callback,
    scan_transfer_callback,
    transfer_confirm_callback,
    transfer_reject_callback,
    scan_cancel_callback,
    book_device_callback,
    release_device_callback,
    info_device_callback,
    back_to_types_callback,
    back_to_main_callback,
    select_device_type_callback,
    unknown_message,
)


def main():
    storage.load_all()

    app = Application.builder().token(storage.config["bot_token"]).build()

    # Команды
    app.add_handler(CommandHandler("start", start_menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("register", register_user))

    # Кнопки навигации
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Назад$"), go_back))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Главное меню$"), start_menu))

    # Пользовательские действия
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Список устройств$"), list_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Бронирование$"), book_device_menu))
    # типы устройств — любые строки, совпадающие с известными типами
    # проще поймать по тексту: если это одно слово из config["device_types"]
    # (на практике можно сделать отдельный Regex, но оставляем так)
    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex("^(" + "|".join(storage.config["device_types"]) + ")$"),
            select_device_type,
        )
    )
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r".* - ID \d+$"), book_specific_device))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^📱 .* - ID \d+$"), book_specific_device))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Мои устройства$"), my_devices))
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex(r"^Освободить .* \(SN: .*?\)$"), release_device_text)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex("^Освободить все устройства$"), release_all_user_devices)
    )
    
    # Сканирование QR/штрих-кодов
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📷 Сканирование$"), scan_code_menu))
    app.add_handler(CallbackQueryHandler(scan_book_callback, pattern="^scan_book_.*"))
    app.add_handler(CallbackQueryHandler(scan_release_callback, pattern="^scan_release_.*"))
    app.add_handler(CallbackQueryHandler(scan_transfer_callback, pattern="^scan_transfer_.*"))
    app.add_handler(CallbackQueryHandler(transfer_confirm_callback, pattern="^transfer_confirm_.*"))
    app.add_handler(CallbackQueryHandler(transfer_reject_callback, pattern="^transfer_reject_.*"))
    app.add_handler(CallbackQueryHandler(scan_cancel_callback, pattern="^scan_cancel$"))
    
    # Обработчики кнопок устройств
    app.add_handler(CallbackQueryHandler(book_device_callback, pattern="^book_dev_.*"))
    app.add_handler(CallbackQueryHandler(release_device_callback, pattern="^release_dev_.*"))
    app.add_handler(CallbackQueryHandler(info_device_callback, pattern="^info_dev_.*"))
    app.add_handler(CallbackQueryHandler(back_to_types_callback, pattern="^back_to_types$"))
    app.add_handler(CallbackQueryHandler(back_to_main_callback, pattern="^back_to_main$"))
    app.add_handler(CallbackQueryHandler(select_device_type_callback, pattern="^type_.*"))

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
    app.add_handler(CallbackQueryHandler(view_booked_admin_callback, pattern="^view_booked_admin$"))
    app.add_handler(CallbackQueryHandler(add_device_callback, pattern="^add_device$"))
    app.add_handler(CallbackQueryHandler(edit_device_callback, pattern="^edit_device_.*"))
    app.add_handler(CallbackQueryHandler(delete_device_callback, pattern="^delete_device_.*"))
    app.add_handler(CallbackQueryHandler(export_devices_callback, pattern="^export_devices_admin$"))
    app.add_handler(CallbackQueryHandler(export_users_callback, pattern="^export_users_admin$"))
    app.add_handler(CallbackQueryHandler(export_logs_callback, pattern="^export_logs_admin$"))

    # Управление устройствами
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Управление устройствами$"), manage_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^(add|del|rename).*$"), admin_devices_text))
    app.add_handler(MessageHandler(filters.Document.FileExtension("csv"), process_devices_csv))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Импортировать устройства$"), import_devices_csv))

    # Управление пользователями
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Управление пользователями$"), manage_users))
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex("^(approve|reject|adduser|edituser|deluser).*$"), admin_users_text)
    )

    # Переключение регистрации
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^(Включить|Выключить) регистрацию$"), toggle_registration))

    # Экспорт
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Экспорт устройств CSV$"), export_devices))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Экспорт пользователей CSV$"), export_users))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Экспорт логов CSV$"), export_logs))

    # FSM-сообщения (должны стоять после команд управления устройствами/пользователями)
    # Проверка состояния будет внутри функций - если NONE, функции вернутся без обработки
    # Но это не позволит сообщению пройти дальше, поэтому используем другой подход:
    # unknown_message будет проверять состояние и вызывать FSM-обработчики при необходимости
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_state_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_state_user_message))

    # Обработка фото для сканирования (перед unknown_message)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_scan))
    
    # Обработка данных от Web App (сканер)
    # Web App данные приходят как сообщения с web_app_data
    # Используем фильтр StatusUpdate.WEB_APP_DATA для обработки данных от Web App
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))

    # Неизвестные сообщения — в самом конце
    app.add_handler(MessageHandler(filters.ALL, unknown_message))

    # Добавляем обработку ошибок для более надежной работы
    import logging
    from telegram.error import NetworkError, TimedOut
    
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    # Запускаем бота с обработкой сетевых ошибок
    try:
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            close_loop=False
        )
    except (NetworkError, TimedOut) as e:
        logging.error(f"Network error occurred: {e}")
        logging.info("Bot will attempt to reconnect automatically...")
        # Бот автоматически переподключится при следующем запуске
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
