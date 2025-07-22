import asyncio
import aiohttp
from centrifuge import Client, SubscriptionEventHandler, ClientEventHandler
from centrifuge import PublicationContext, ConnectedContext, DisconnectedContext
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timedelta
import logging
import json
import uuid

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

API_KEY = "4e4c7ae1-9e45-4ee2-aef8-b8029f3cb97f"
TELEGRAM_TOKEN = "7726727524:AAEf82GMHiwXRfJkeZdH-t1Qlk5KOrOYc_c"
TELEGRAM_CHAT_ID = "758884131"

STEAM_PARTNER = "1057958433"  # Твой partner из Trade URL
STEAM_TOKEN = "0KqicsOy"      # Твой token из Trade URL

FLOAT_RANGES = [
    (0.00, 0.01),
    (0.07, 0.071),
    (0.99, 1.00)
]
STICKER_KEYWORDS = [
    "Howling Dawn",
    "Windged Defuser",
    "Crown (Foil)",
    "2013",
    "Katowice 2014",
    "Katowice 2015",
    "(Holo) | Cologne 2016",
    "(Foil) | Cologne 2016",
    "(Holo) | Atlanta 2017",
    "(Foil) | Atlanta 2017",
    "(Holo) | Boston 2018",
    "(Foil) | Boston 2018"
    # "(Holo) | Katowice 2019",
    # "(Foil) | Katowice 2019"
]
CHARM_KEYWORDS = [
    "Die-cast",
    "Semi-Precious",
    "Hot Howl",
    "Diamond Dog",
    "Hot Wurst",
    "Baby Karat T",
    "Baby Karat CT"
]

HIGHLIGHT_KEYWORDS = [
    "Hightlight"
]

class SkinPurchaser:
    """Класс для покупки скинов"""
    def __init__(self, api_key: str, partner: str, token: str):
        self.api_key = api_key
        self.partner = partner
        self.token = token
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
        
    async def buy_skin(self, skin_id: int, max_price: Optional[float] = None) -> Dict[str, Any]:
        """Покупка одного скина"""
        url = "https://api.lis-skins.com/v1/market/buy"
        custom_id = f"tg_purchase_{skin_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        data = {
            "ids": [skin_id],
            "partner": self.partner,
            "token": self.token,
            "custom_id": custom_id,
            "skip_unavailable": True
        }
        
        if max_price:
            data["max_price"] = max_price
            
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, json=data) as response:
                if response.status in [200, 201]:
                    result = await response.json()
                    return result.get('data', result)
                else:
                    error_text = await response.text()
                    raise Exception(f"Ошибка покупки: {error_text}")

class ConnectionMonitor(ClientEventHandler):
    """Мониторинг состояния соединения"""
    
    async def on_connected(self, ctx: ConnectedContext) -> None:
        logger.info(f"✅ WebSocket подключен: client_id={ctx.client}, version={ctx.version}")
        
    async def on_disconnected(self, ctx: DisconnectedContext) -> None:
        logger.warning(f"❌ WebSocket отключен: code={ctx.code}, reason={ctx.reason}")

class CSGOSkinTracker:
    def __init__(self, telegram_app: Application):
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.telegram_app = telegram_app
        self.client = None
        self.running = True
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5
        self.last_event_time = datetime.now()
        self.heartbeat_task = None
        self.events_count = 0
        self.purchaser = SkinPurchaser(API_KEY, STEAM_PARTNER, STEAM_TOKEN)
        
        # Добавляем глобальные кеши для дедупликации
        self.sent_new_items = {}  # {item_id: timestamp}
        self.sent_sold_items = {}  # {item_id: timestamp}
        self.cache_cleanup_interval = 3600  # Очистка кеша каждый час

    async def send_alert(self, message: str, item_id: Optional[int] = None, price: Optional[float] = None):
        """Отправка сообщения с кнопкой покупки"""
        try:
            keyboard = []
            
            # Добавляем кнопку покупки если есть ID предмета
            if item_id:
                # Используем короткий формат для callback_data
                callback_data = f"buy_{item_id}"
                keyboard.append([InlineKeyboardButton("🛒 Купить", callback_data=callback_data)])
                
                # Сохраняем полные данные в контексте бота
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
        url = "https://api.lis-skins.com/v1/user/get-ws-token"
        headers = {"Authorization": f"Bearer {API_KEY}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
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
                await asyncio.sleep(60)  # Проверяем каждую минуту
                
                time_since_last_event = datetime.now() - self.last_event_time
                logger.info(f"📊 Статус: События обработано: {self.events_count}, "
                        f"Последнее событие: {time_since_last_event.seconds} сек назад")
                
                # Если нет событий более 5 минут - что-то не так
                if time_since_last_event > timedelta(minutes=5):
                    logger.warning("⚠️ Нет событий более 5 минут, инициируем переподключение...")
                    self.running = False
                    break  # Важно! Выходим из цикла heartbeat
                        
            except Exception as e:
                logger.error(f"Ошибка в heartbeat: {e}")

    async def cleanup_cache(self):
        """Очистка старых записей из кеша"""
        while self.running:
            try:
                await asyncio.sleep(self.cache_cleanup_interval)
                current_time = datetime.now()
                
                # Очищаем записи старше 2 часов
                cutoff_time = current_time - timedelta(hours=2)
                
                # Очистка кеша новых предметов
                self.sent_new_items = {
                    item_id: timestamp 
                    for item_id, timestamp in self.sent_new_items.items() 
                    if timestamp > cutoff_time
                }
                
                # Очистка кеша проданных предметов
                self.sent_sold_items = {
                    item_id: timestamp 
                    for item_id, timestamp in self.sent_sold_items.items() 
                    if timestamp > cutoff_time
                }
                
                logger.info(f"🧹 Очистка кеша: новых {len(self.sent_new_items)}, проданных {len(self.sent_sold_items)}")
                
            except Exception as e:
                logger.error(f"Ошибка очистки кеша: {e}")

    class CSGOEventHandler(SubscriptionEventHandler):
        def __init__(self, tracker, float_ranges: List[Tuple[float, float]]):
            self.tracker = tracker
            self.float_ranges = float_ranges
            self.active_items = {}
            self.processing_lock = asyncio.Lock()

        async def on_subscribing(self, ctx) -> None:
            logger.info("📡 Подписка на канал...")

        async def on_subscribed(self, ctx) -> None:
            logger.info("✅ Успешно подписались на канал")
            # Очищаем active_items при новой подписке
            self.active_items.clear()

        async def on_unsubscribed(self, ctx) -> None:
            logger.warning(f"❌ Отписались от канала: {ctx}")

        async def on_error(self, ctx) -> None:
            logger.error(f"❌ Ошибка подписки: {ctx}")

        async def on_publication(self, ctx: PublicationContext) -> None:
            # Обновляем время последнего события
            self.tracker.last_event_time = datetime.now()
            self.tracker.events_count += 1
            
            # Логируем каждое 100-е событие для диагностики
            if self.tracker.events_count % 100 == 0:
                logger.info(f"📈 Обработано {self.tracker.events_count} событий")
            
            async with self.processing_lock:
                try:
                    data = ctx.pub.data
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    if not self.tracker.is_csgo_item(data):
                        return
                        
                    event_type = data.get('event')
                    item_id = str(data['id'])

                    if event_type == 'obtained_skin_added':
                        # Проверяем, не отправляли ли мы уже уведомление об этом предмете
                        if item_id in self.tracker.sent_new_items:
                            time_diff = datetime.now() - self.tracker.sent_new_items[item_id]
                            if time_diff < timedelta(minutes=30):  # Игнорируем повторы в течение 30 минут
                                logger.debug(f"Пропускаем дубликат нового предмета {item_id}")
                                return
                        
                        self.active_items[item_id] = {
                            'appear_time': current_time,
                            'data': data
                        }
                        await self.process_new_item(data, current_time)
                        
                    elif event_type == 'obtained_skin_deleted':
                        # Проверяем, не отправляли ли мы уже уведомление о продаже
                        if item_id in self.tracker.sent_sold_items:
                            time_diff = datetime.now() - self.tracker.sent_sold_items[item_id]
                            if time_diff < timedelta(minutes=30):  # Игнорируем повторы в течение 30 минут
                                logger.debug(f"Пропускаем дубликат продажи {item_id}")
                                return
                        
                        if item_id in self.active_items:
                            item_data = self.active_items[item_id]
                            await self.process_sold_item(
                                item_data['data'], 
                                item_data['appear_time'], 
                                current_time
                            )
                            del self.active_items[item_id]
                        else:
                            # Если предмета нет в active_items, возможно он был добавлен до запуска бота
                            logger.debug(f"Предмет {item_id} продан, но не был в отслеживании")

                except Exception as e:
                    logger.error(f"Ошибка обработки события: {e}")

        async def process_new_item(self, data: Dict[str, Any], appear_time: str):
            try:
                item_name = data.get('name', '')
                item_id = data.get('id')
                price = data.get('price')
                item_float = data.get('item_float')
                stickers = data.get('stickers', [])
                
                # Пропускаем кейсы
                if 'Case' in item_name:
                    return
                
                # Флаги для определения, подходит ли предмет
                matches_float = False
                found_stickers = []
                found_charms = []
                found_highlights = []
                
                # 1. Проверяем float диапазоны (только для оружия с float)
                if item_float is not None:
                    try:
                        skin_float = float(item_float)
                        for range_min, range_max in self.float_ranges:
                            if range_min <= skin_float <= range_max:
                                matches_float = True
                                break
                    except (ValueError, TypeError):
                        pass
                
                # 2. Проверяем стикеры/чармы/highlights
                if stickers and len(stickers) > 0:
                    for sticker in stickers:
                        sticker_name = sticker.get('name', '')
                        
                        # Проверяем на стикеры
                        for keyword in STICKER_KEYWORDS:
                            if keyword.lower() in sticker_name.lower():
                                found_stickers.append({
                                    'name': sticker_name,
                                    'wear': sticker.get('wear', 0),
                                    'slot': sticker.get('slot', 0)
                                })
                                break
                        
                        # Проверяем на чармы
                        for keyword in CHARM_KEYWORDS:
                            if keyword.lower() in sticker_name.lower():
                                found_charms.append({
                                    'name': sticker_name,
                                    'wear': sticker.get('wear', 0),
                                    'slot': sticker.get('slot', 0)
                                })
                                break
                        
                        # Проверяем хайлайты
                        for keyword in HIGHLIGHT_KEYWORDS:
                            if keyword.lower() in sticker_name.lower():
                                found_highlights.append({
                                    'name': sticker_name,
                                    'slot': sticker.get('slot', 0)
                                })
                                break
                
                # Если предмет подходит по любому критерию
                if matches_float or found_stickers or found_charms:
                    # Формируем сообщение
                    reasons = []
                    
                    if matches_float:
                        reasons.append(f"✅ Float: {float(item_float):.6f}")
                    
                    if found_stickers:
                        stickers_text = "\n".join([
                            f"  • {s['name']} (слот {s['slot']}, износ: {s['wear']}%)"
                            for s in found_stickers
                        ])
                        reasons.append(f"🏷 Стикеры:\n{stickers_text}")
                    
                    if found_charms:
                        charms_text = "\n".join([
                            f"  • {c['name']} (слот {c['slot']}, износ: {c['wear']}%)"
                            for c in found_charms
                        ])
                        reasons.append(f"💎 Чармы:\n{charms_text}")

                    if found_highlights:
                        highlight_text = "\n".join([
                            f"  • {c['name']} (слот {c['slot']})"
                            for c in found_highlights
                        ])
                        reasons.append(f"💎 Хайлайты:\n{highlight_text}")

                    
                    message = (
                        f"<b>🆕 НОВЫЙ СКИН </b>\n"
                        f"⏱ Появился: {appear_time}\n"
                        f"Название: {item_name}\n"
                        f"Цена: ${price}\n"
                        f"Float: {float(item_float)}\n"
                        f"ID: {item_id}\n\n"
                        f"Причины уведомления:\n" + "\n".join(reasons)
                    )
                    
                    # Добавляем дополнительную информацию
                    if item_float:
                        message += f"\n\nПаттерн: {data.get('item_paint_index', 'N/A')}"
                        message += f"\nSeed: {data.get('item_paint_seed', 'N/A')}"
                    
                    logger.info(f"[NEW ITEM] {item_name} - Float: {item_float}, Stickers: {len(found_stickers)}, Charms: {len(found_charms)}")
                    await self.tracker.send_alert(message, item_id, price)
                    
                    # Сохраняем в кеш
                    self.tracker.sent_new_items[str(item_id)] = datetime.now()
                    
            except Exception as e:
                logger.error(f"Ошибка обработки нового предмета: {e}")

        async def process_sold_item(self, data: Dict[str, Any], appear_time: str, sold_time: str):
            if 'Case' in data.get('name', ''):
                return
            
            try:
                item_name = data.get('name', '')
                item_id = data.get('id')
                item_float = data.get('item_float')
                stickers = data.get('stickers', [])
                
                # Проверяем по тем же критериям
                matches_float = False
                found_stickers = []
                found_charms = []
                found_highlights = []
                
                # Проверка float
                if item_float is not None:
                    try:
                        skin_float = float(item_float)
                        for range_min, range_max in self.float_ranges:
                            if range_min <= skin_float <= range_max:
                                matches_float = True
                                break
                    except (ValueError, TypeError):
                        pass
                
                # Проверка стикеров/чармов
                if stickers and len(stickers) > 0:
                    for sticker in stickers:
                        sticker_name = sticker.get('name', '')
                        
                        for keyword in STICKER_KEYWORDS:
                            if keyword.lower() in sticker_name.lower():
                                found_stickers.append(sticker_name)
                                break
                        
                        for keyword in CHARM_KEYWORDS:
                            if keyword.lower() in sticker_name.lower():
                                found_charms.append(sticker_name)
                                break

                        # Проверяем хайлайты
                        for keyword in HIGHLIGHT_KEYWORDS:
                            if keyword.lower() in sticker_name.lower():
                                found_highlights.append(sticker_name)
                                break
                
                # Если предмет подходит по любому критерию
                if matches_float or found_stickers or found_charms:
                    duration = self.calculate_duration(appear_time, sold_time)
                    
                    # Формируем описание
                    details = []
                    if matches_float:
                        details.append(f"Float: {float(item_float):.6f}")
                    if found_stickers:
                        details.append(f"Стикеры: {', '.join(found_stickers)}")
                    if found_charms:
                        details.append(f"Чармы: {', '.join(found_charms)}")
                    if found_highlights:
                        details.append(f"Хайлайты: {', '.join(found_highlights)}")
                    
                    message = (
                        f"💰 <b>Скин продан</b>\n"
                        f"⏱ Появился: {appear_time}\n"
                        f"🛒 Продан: {sold_time}\n"
                        f"⏳ Время на продажу: {duration}\n"
                        f"Название: {data.get('name', 'N/A')}\n"
                        f"Цена: ${data.get('price', 'N/A')}\n"
                        f"{chr(10).join(details)}\n"
                        f"ID: {data.get('id', 'N/A')}"
                    )
                    
                    logger.info(f"[SOLD] {data['name']} - {', '.join(details)}")
                    await self.tracker.send_alert(message)
                    
                    # Сохраняем в кеш
                    self.tracker.sent_sold_items[str(item_id)] = datetime.now()
                    
            except Exception as e:
                logger.error(f"Ошибка обработки проданного предмета: {e}")

        def calculate_duration(self, start_time: str, end_time: str) -> str:
            try:
                fmt = "%Y-%m-%d %H:%M:%S"
                start = datetime.strptime(start_time, fmt)
                end = datetime.strptime(end_time, fmt)
                delta = end - start
                
                hours, remainder = divmod(delta.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                return f"{hours}ч {minutes}м {seconds}с"
            except Exception as e:
                logger.error(f"Ошибка расчета времени: {e}")
                return "N/A"

    async def connect_and_subscribe(self):
        """Подключение и подписка с обработкой ошибок"""
        try:
            logger.info("🔑 Получение токена...")
            token = await self.get_websocket_token()
            logger.info("✅ Токен получен")
            
            # Создаем новый клиент с обработчиком событий соединения
            self.client = Client(
                "wss://ws.lis-skins.com/connection/websocket",
                token=token,
                events=ConnectionMonitor()
            )
            
            logger.info("📡 Создание подписки...")
            sub = self.client.new_subscription(
                "public:obtained-skins",
                events=self.CSGOEventHandler(self, FLOAT_RANGES)
            )
            
            logger.info("🔌 Подключение к WebSocket...")
            await self.client.connect()
            
            logger.info("📥 Подписка на канал...")
            await sub.subscribe()
            
            logger.info("✅ Успешно подключено к WebSocket")
            self.reconnect_attempts = 0
            
            # Запускаем мониторинг соединения
            if self.heartbeat_task:
                self.heartbeat_task.cancel()
            self.heartbeat_task = asyncio.create_task(self.heartbeat_monitor())
            
            # Запускаем очистку кеша
            self.cache_cleanup_task = asyncio.create_task(self.cleanup_cache())
            
            logger.info("💓 Heartbeat мониторинг запущен")
            
            # Держим соединение
            while self.running:
                await asyncio.sleep(1)
                
            logger.info("🔚 Выход из цикла подключения")
                
        except Exception as e:
            logger.error(f"❌ Ошибка соединения: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
        finally:
            # Отменяем heartbeat при отключении
            if self.heartbeat_task:
                self.heartbeat_task.cancel()
                
            # Отменяем очистку кеша
            if hasattr(self, 'cache_cleanup_task'):
                self.cache_cleanup_task.cancel()
                
            if self.client:
                try:
                    await self.client.disconnect()
                except:
                    pass
    
    async def track_skins(self):
        """Основной цикл с автоматическим переподключением"""
        logger.info("🚀 Запуск трекера CS:GO предметов...")
        
        # Проверяем настройки
        logger.info(f"📋 Настройки:")
        logger.info(f"   API Key: {API_KEY[:10]}...")
        logger.info(f"   Steam Partner: {STEAM_PARTNER}")
        logger.info(f"   Float диапазоны: {FLOAT_RANGES}")
        logger.info(f"   Ключевые слова стикеров: {len(STICKER_KEYWORDS)} шт.")
        logger.info(f"   Ключевые слова чармов: {len(CHARM_KEYWORDS)} шт.")
        
        while self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                logger.info(f"🔄 Попытка подключения {self.reconnect_attempts + 1}/{self.max_reconnect_attempts}")
                self.running = True  # Сбрасываем флаг для нового подключения
                await self.connect_and_subscribe()
                
                # Если вышли из connect_and_subscribe из-за self.running = False
                # и reconnect_attempts не превышен, продолжаем цикл
                if not self.running and self.reconnect_attempts < self.max_reconnect_attempts:
                    logger.info("📡 Соединение прервано, будет выполнено переподключение...")
                    self.reconnect_attempts += 1
                    
                    if self.reconnect_attempts < self.max_reconnect_attempts:
                        delay = min(self.reconnect_delay * self.reconnect_attempts, 60)
                        logger.info(f"⏳ Переподключение через {delay} секунд...")
                        await asyncio.sleep(delay)
                        continue
                else:
                    # Если running все еще True, значит была другая ошибка
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

    def stop(self):
        """Остановка трекера"""
        logger.info("🛑 Остановка трекера...")
        self.running = False


# Обработчики Telegram
async def handle_purchase_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки покупки"""
    query = update.callback_query
    
    try:
        # Сначала отвечаем на callback, чтобы убрать "часики"
        await query.answer("Обрабатываю покупку...")
        
        # Парсим callback_data
        callback_data = query.data
        logger.info(f"Получен callback: '{callback_data}'")
        logger.info(f"Тип callback_data: {type(callback_data)}")
        logger.info(f"Длина callback_data: {len(callback_data)}")
        
        # Проверяем формат данных
        if not callback_data:
            logger.error("Пустой callback_data")
            await query.edit_message_text("❌ Ошибка: пустые данные")
            return
            
        # Пробуем разные способы получения ID
        item_id = None
        
        # Способ 1: Проверяем формат buy_ID
        if callback_data.startswith("buy_"):
            try:
                item_id = int(callback_data.replace("buy_", ""))
                logger.info(f"Извлечен ID способом 1: {item_id}")
            except ValueError as e:
                logger.error(f"Ошибка преобразования ID: {e}")
        
        # Способ 2: Если данные обрезаны, пробуем найти в сохраненных данных
        if item_id is None and 'purchase_data' in context.bot_data:
            logger.info("Пробуем найти ID в сохраненных данных...")
            logger.info(f"Сохраненные ID: {list(context.bot_data['purchase_data'].keys())}")
            
            # Ищем по частичному совпадению
            for saved_id in context.bot_data['purchase_data'].keys():
                if saved_id in callback_data or callback_data in f"buy_{saved_id}":
                    item_id = int(saved_id)
                    logger.info(f"Найден ID в сохраненных данных: {item_id}")
                    break
        
        # Способ 3: Пробуем извлечь числа из callback_data
        if item_id is None:
            import re
            numbers = re.findall(r'\d+', callback_data)
            if numbers:
                item_id = int(numbers[0])
                logger.info(f"Извлечен ID из чисел: {item_id}")
        
        if item_id is None:
            logger.error(f"Не удалось извлечь ID из callback_data: '{callback_data}'")
            await query.edit_message_text(
                f"❌ Ошибка: не удалось определить ID предмета\n"
                f"Данные: {callback_data}"
            )
            return
        
        # Получаем сохраненные данные о предмете
        purchase_data = context.bot_data.get('purchase_data', {}).get(str(item_id), {})
        price = purchase_data.get('price', 0)
        
        logger.info(f"Покупка предмета ID: {item_id}, цена: ${price}")
        
        # Обновляем сообщение
        await query.edit_message_text(
            f"⏳ <b>Покупаю предмет</b>\n\n"
            f"ID: {item_id}\n"
            f"Цена: ${price}\n\n"
            f"Ожидайте...",
            parse_mode="HTML"
        )
        
        # Выполняем покупку
        purchaser = SkinPurchaser(API_KEY, STEAM_PARTNER, STEAM_TOKEN)
        
        try:
            result = await purchaser.buy_skin(item_id, max_price=price * 1.1 if price else None)
            
            if result:
                purchase_id = result.get('purchase_id')
                skins = result.get('skins', [])
                
                if skins:
                    skin = skins[0]
                    status_text = (
                        f"✅ <b>Покупка создана!</b>\n\n"
                        f"Purchase ID: {purchase_id}\n"
                        f"Название: {skin.get('name')}\n"
                        f"Цена: ${skin.get('price')}\n"
                        f"Статус: {skin.get('status')}\n\n"
                        f"⏳ Ожидайте трейд в Steam!"
                    )
                else:
                    status_text = f"✅ Покупка создана! ID: {purchase_id}"
                    
                await query.edit_message_text(status_text, parse_mode="HTML")
                
                # Удаляем сохраненные данные
                if 'purchase_data' in context.bot_data and str(item_id) in context.bot_data['purchase_data']:
                    del context.bot_data['purchase_data'][str(item_id)]
                    
            else:
                await query.edit_message_text("❌ Ошибка: не получен ответ от сервера")
                
        except Exception as purchase_error:
            logger.error(f"Ошибка при покупке: {purchase_error}")
            await query.edit_message_text(
                f"❌ <b>Ошибка при покупке</b>\n\n"
                f"Детали: {str(purchase_error)[:200]}",
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        import traceback
        traceback.print_exc()
        try:
            await query.answer("❌ Произошла ошибка", show_alert=True)
        except:
            pass


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /start"""
    await update.message.reply_text(
        "🤖 <b>CS:GO Skin Tracker Bot</b>\n\n"
        "Бот отслеживает новые скины и отправляет уведомления.\n"
        "Нажмите кнопку '🛒 Купить' под сообщением для покупки скина.\n\n"
        "Steam Partner: " + STEAM_PARTNER + "\n"
        "Steam Token: " + STEAM_TOKEN[:3] + "***",
        parse_mode="HTML"
    )


async def main():
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
        # Запускаем с обработкой Ctrl+C
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Программа прервана пользователем")
    except Exception as e:
        logger.error(f"Фатальная ошибка: {e}")
        import traceback
        traceback.print_exc()