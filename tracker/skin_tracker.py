"""Основной класс трекера скинов"""
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from centrifuge import Client, ClientEventHandler, ConnectedContext, DisconnectedContext
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

from config import (
    API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
    WS_URL, WS_TOKEN_URL, WS_CHANNEL,
    MAX_RECONNECT_ATTEMPTS, RECONNECT_DELAY,
    HEARTBEAT_INTERVAL, NO_EVENTS_TIMEOUT,
    CACHE_CLEANUP_INTERVAL, CACHE_ITEM_TTL,
    FLOAT_RANGES
)
from models.skin_purchaser import SkinPurchaser
from handlers.websocket_handler import CSGOEventHandler
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ConnectionMonitor(ClientEventHandler):
    """Мониторинг состояния соединения"""
    def __init__(self, tracker):
        self.tracker = tracker
    
    async def on_connected(self, ctx: ConnectedContext) -> None:
        logger.info(f"✅ WebSocket подключен: client_id={ctx.client}, version={ctx.version}")
        self.tracker.is_connected = True
        
    async def on_disconnected(self, ctx: DisconnectedContext) -> None:
        logger.warning(f"❌ WebSocket отключен: code={ctx.code}, reason={ctx.reason}")
        self.tracker.is_connected = False
        
        # Коды ошибок, требующие переподключения
        reconnect_codes = [1, 3005, 3501, 1006]
        
        if ctx.code in reconnect_codes:
            logger.warning("🔄 Требуется переподключение из-за отключения WebSocket")
            self.tracker.needs_reconnect = True
            self.tracker.running = False  # Прерываем текущий цикл


class CSGOSkinTracker:
    """Основной класс трекера CS:GO скинов"""
    
    def __init__(self, telegram_app: Application):
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.telegram_app = telegram_app
        self.client = None
        self.running = True
        self.is_connected = False
        self.needs_reconnect = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = MAX_RECONNECT_ATTEMPTS
        self.reconnect_delay = RECONNECT_DELAY
        self.last_event_time = datetime.now()
        self.heartbeat_task = None
        self.events_count = 0
        self.purchaser = SkinPurchaser()
        
        # Кеши для дедупликации
        self.sent_new_items = {}
        self.sent_sold_items = {}
        self.cache_cleanup_interval = CACHE_CLEANUP_INTERVAL

    async def send_alert(self, message: str, item_id: Optional[int] = None, 
                        price: Optional[float] = None):
        """Отправка сообщения с кнопкой покупки"""
        try:
            keyboard = []
            
            if item_id:
                callback_data = f"buy_{item_id}"
                keyboard.append([InlineKeyboardButton("🛒 Купить", callback_data=callback_data)])
                
                # Сохраняем данные о предмете
                if not hasattr(self.telegram_app.bot_data, 'purchase_data'):
                    self.telegram_app.bot_data['purchase_data'] = {}
                    
                self.telegram_app.bot_data['purchase_data'][str(item_id)] = {
                    "id": item_id,
                    "price": price,
                    "timestamp": datetime.now().isoformat()
                }
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            await self.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=message,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Ошибка отправки в Telegram: {e}")

    async def get_websocket_token(self) -> str:
        """Получение токена для WebSocket"""
        headers = {"Authorization": f"Bearer {API_KEY}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(WS_TOKEN_URL, headers=headers) as response:
                response.raise_for_status()
                data = await response.json()
                return data['data']['token']

    def is_csgo_item(self, data: Dict[str, Any]) -> bool:
        """Проверка, является ли предмет из CS:GO"""
        return data.get('game_id') == 1

    async def heartbeat_monitor(self):
        """Мониторинг активности соединения"""
        while self.running:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                
                time_since_last_event = datetime.now() - self.last_event_time
                logger.info(f"📊 Статус: События обработано: {self.events_count}, "
                          f"Последнее событие: {time_since_last_event.seconds} сек назад")
                
                if time_since_last_event > timedelta(seconds=NO_EVENTS_TIMEOUT):
                    logger.warning("⚠️ Нет событий более 5 минут, инициируем переподключение...")
                    self.running = False
                    break
                        
            except Exception as e:
                logger.error(f"Ошибка в heartbeat: {e}")

    async def cleanup_cache(self):
        """Очистка старых записей из кеша"""
        while self.running:
            try:
                await asyncio.sleep(self.cache_cleanup_interval)
                current_time = datetime.now()
                cutoff_time = current_time - timedelta(seconds=CACHE_ITEM_TTL)
                
                # Очистка кешей
                self.sent_new_items = {
                    item_id: timestamp 
                    for item_id, timestamp in self.sent_new_items.items() 
                    if timestamp > cutoff_time
                }
                
                self.sent_sold_items = {
                    item_id: timestamp 
                    for item_id, timestamp in self.sent_sold_items.items() 
                    if timestamp > cutoff_time
                }
                
                logger.info(f"🧹 Очистка кеша: новых {len(self.sent_new_items)}, "
                          f"проданных {len(self.sent_sold_items)}")
            except Exception as e:
                logger.error(f"Ошибка очистки кеша: {e}")

    async def heartbeat_monitor(self):
        """Мониторинг активности соединения"""
        while self.running:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                
                time_since_last_event = datetime.now() - self.last_event_time
                logger.info(f"📊 Статус: События обработано: {self.events_count}, "
                          f"Последнее событие: {time_since_last_event.seconds} сек назад, "
                          f"Подключен: {self.is_connected}")
                
                # Если нет событий более 5 минут или соединение потеряно
                if time_since_last_event > timedelta(seconds=NO_EVENTS_TIMEOUT) or not self.is_connected:
                    logger.warning("⚠️ Проблема с соединением, инициируем переподключение...")
                    self.needs_reconnect = True
                    self.running = False
                    break
                        
            except Exception as e:
                logger.error(f"Ошибка в heartbeat: {e}")

    async def connect_and_subscribe(self):
        """Подключение и подписка с обработкой ошибок"""
        try:
            logger.info("🔑 Получение токена...")
            token = await self.get_websocket_token()
            logger.info("✅ Токен получен")
            
            # Создаем новый клиент
            self.client = Client(
                WS_URL,
                token=token,
                events=ConnectionMonitor(self)  # Передаем self для доступа к tracker
            )
            
            logger.info("📡 Создание подписки...")
            sub = self.client.new_subscription(
                WS_CHANNEL,
                events=CSGOEventHandler(self, FLOAT_RANGES)
            )
            
            logger.info("🔌 Подключение к WebSocket...")
            await self.client.connect()

            await asyncio.sleep(0.5)
            
            logger.info("📥 Подписка на канал...")
            await sub.subscribe()
            
            logger.info("✅ Успешно подключено к WebSocket")
            self.reconnect_attempts = 0
            self.is_connected = True
            self.needs_reconnect = False
            
            # Запускаем фоновые задачи
            if self.heartbeat_task:
                self.heartbeat_task.cancel()
                try:
                    await self.heartbeat_task
                except asyncio.CancelledError:
                    pass
                    
            self.heartbeat_task = asyncio.create_task(self.heartbeat_monitor())
            
            self.cache_cleanup_task = asyncio.create_task(self.cleanup_cache())
            
            logger.info("💓 Heartbeat мониторинг запущен")
            
            # Держим соединение
            while self.running and self.is_connected and not self.needs_reconnect:
                await asyncio.sleep(1)
                
            logger.info("🔚 Выход из цикла подключения")
                
        except Exception as e:
            logger.error(f"❌ Ошибка соединения: {str(e)}")
            import traceback
            traceback.print_exc()
            self.is_connected = False
            raise
        finally:
            # Отменяем фоновые задачи
            if self.heartbeat_task:
                self.heartbeat_task.cancel()
                try:
                    await self.heartbeat_task
                except asyncio.CancelledError:
                    pass
                
            if hasattr(self, 'cache_cleanup_task'):
                self.cache_cleanup_task.cancel()
                try:
                    await self.cache_cleanup_task
                except asyncio.CancelledError:
                    pass
                
            if self.client:
                try:
                    await self.client.disconnect()
                except:
                    pass
                self.client = None
    
    async def track_skins(self):
        """Основной цикл с автоматическим переподключением"""
        logger.info("🚀 Запуск трекера CS:GO предметов...")
        
        # Выводим настройки
        self._log_settings()
        
        while self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                logger.info(f"🔄 Попытка подключения {self.reconnect_attempts + 1}/{self.max_reconnect_attempts}")
                self.running = True
                self.is_connected = False
                self.needs_reconnect = False
                
                await self.connect_and_subscribe()
                
                # Если вышли из connect_and_subscribe из-за self.needs_reconnect
                if self.needs_reconnect:
                    logger.info("📡 Требуется переподключение...")
                    self.reconnect_attempts += 1
                    
                    if self.reconnect_attempts < self.max_reconnect_attempts:
                        delay = min(self.reconnect_delay * self.reconnect_attempts, 60)
                        logger.info(f"⏳ Переподключение через {delay} секунд...")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error("❌ Превышено максимальное количество попыток переподключения")
                        await self.send_alert("❌ <b>Бот остановлен</b>\nПревышено количество попыток переподключения")
                        break
                elif not self.running:
                    # Если остановка была вызвана извне (например, Ctrl+C)
                    logger.info("🛑 Остановка по запросу")
                    break
                    
            except Exception as e:
                self.reconnect_attempts += 1
                logger.error(f"❌ Соединение потеряно: {str(e)}")
                
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    delay = min(self.reconnect_delay * self.reconnect_attempts, 60)
                    logger.info(f"⏳ Переподключение через {delay} секунд...")
                    await asyncio.sleep(delay)
                else:
                    logger.error("❌ Превышено максимальное количество попыток переподключения")
                    await self.send_alert("❌ <b>Бот остановлен</b>\nПревышено количество попыток переподключения")
                    break
        
        logger.info("🔌 Трекер остановлен")
        self.running = False
        self.is_connected = False

    def stop(self):
        """Остановка трекера"""
        logger.info("🛑 Остановка трекера...")
        self.running = False

    def _log_settings(self):
        """Вывод текущих настроек"""
        from config import STICKER_KEYWORDS, CHARM_KEYWORDS
        
        logger.info(f"📋 Настройки:")
        logger.info(f"   API Key: {API_KEY[:10]}...")
        logger.info(f"   Float диапазоны: {FLOAT_RANGES}")
        logger.info(f"   Ключевые слова стикеров: {len(STICKER_KEYWORDS)} шт.")
        logger.info(f"   Ключевые слова чармов: {len(CHARM_KEYWORDS)} шт.")