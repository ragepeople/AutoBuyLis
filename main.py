"""Главный модуль приложения"""
import asyncio
import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram import Update

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from tracker import CSGOSkinTracker
from handlers import start_command, handle_purchase_callback
from utils.logger import setup_logger

logger = setup_logger(__name__)


async def main():
    """Главная функция приложения"""
    # Создаем Telegram приложение
    telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Добавляем обработчики
    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CallbackQueryHandler(handle_purchase_callback))
    
    logger.info("📱 Инициализация Telegram бота...")
    
    # Инициализируем telegram polling
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    logger.info("✅ Telegram бот запущен и готов принимать команды")
    
    # Создаем и запускаем трекер
    # Создаем и запускаем трекер
    tracker = CSGOSkinTracker(telegram_app)
    
    try:
        # Запускаем трекер
        await tracker.track_skins()
            
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки...")
        tracker.stop()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        
        # Пробуем отправить уведомление об ошибке
        try:
            await telegram_app.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"❌ <b>Критическая ошибка бота</b>\n\n{str(e)[:200]}...\n\nБот будет перезапущен.",
                parse_mode="HTML"
            )
        except:
            pass
    finally:
        logger.info("Завершение работы...")
        
        # Останавливаем трекер
        tracker.stop()
        
        # Останавливаем Telegram
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
        
        logger.info("✅ Программа завершена")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Программа прервана пользователем")
    except Exception as e:
        logger.error(f"Фатальная ошибка: {e}")
        import traceback
        traceback.print_exc()