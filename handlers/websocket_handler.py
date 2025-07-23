"""Обработчики WebSocket событий"""
import asyncio
from typing import Dict, Any, List, Tuple
from datetime import datetime, timedelta
from centrifuge import SubscriptionEventHandler, PublicationContext

from config import STICKER_KEYWORDS, CHARM_KEYWORDS, HIGHLIGHT_KEYWORDS, AUTO_BUY_SETTINGS, rates
from models.skin_purchaser import SkinPurchaser
from utils.logger import setup_logger

logger = setup_logger(__name__)


class CSGOEventHandler(SubscriptionEventHandler):
    """Обработчик событий CS:GO"""
    
    def __init__(self, tracker, float_ranges: List[Tuple[float, float]]):
        self.tracker = tracker
        self.float_ranges = float_ranges
        self.active_items = {}
        self.processing_lock = asyncio.Lock()
        self.purchaser = SkinPurchaser()

    async def on_subscribing(self, ctx) -> None:
        logger.info("📡 Подписка на канал...")

    async def on_subscribed(self, ctx) -> None:
        logger.info("✅ Успешно подписались на канал")
        self.active_items.clear()

    async def on_unsubscribed(self, ctx) -> None:
        logger.warning(f"❌ Отписались от канала: {ctx}")

    async def on_error(self, ctx) -> None:
        logger.error(f"❌ Ошибка подписки: {ctx}")

    async def on_publication(self, ctx: PublicationContext) -> None:
        """Обработка публикации"""
        self.tracker.last_event_time = datetime.now()
        self.tracker.events_count += 1
        
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
                    if self._is_duplicate_new_item(item_id):
                        return
                    
                    self.active_items[item_id] = {
                        'appear_time': current_time,
                        'data': data
                    }
                    await self.process_new_item(data, current_time)
                    
                elif event_type == 'obtained_skin_deleted':
                    if self._is_duplicate_sold_item(item_id):
                        return
                    
                    if item_id in self.active_items:
                        item_data = self.active_items[item_id]
                        await self.process_sold_item(
                            item_data['data'], 
                            item_data['appear_time'], 
                            current_time
                        )
                        del self.active_items[item_id]

            except Exception as e:
                logger.error(f"Ошибка обработки события: {e}")

    def _is_duplicate_new_item(self, item_id: str) -> bool:
        """Проверка на дубликат нового предмета"""
        if item_id in self.tracker.sent_new_items:
            time_diff = datetime.now() - self.tracker.sent_new_items[item_id]
            if time_diff < timedelta(minutes=30):
                logger.debug(f"Пропускаем дубликат нового предмета {item_id}")
                return True
        return False

    def _is_duplicate_sold_item(self, item_id: str) -> bool:
        """Проверка на дубликат проданного предмета"""
        if item_id in self.tracker.sent_sold_items:
            time_diff = datetime.now() - self.tracker.sent_sold_items[item_id]
            if time_diff < timedelta(minutes=30):
                logger.debug(f"Пропускаем дубликат продажи {item_id}")
                return True
        return False

    async def process_new_item(self, data: Dict[str, Any], appear_time: str):
        """Обработка нового предмета"""
        try:
            item_name = data.get('name', '')
            item_id = data.get('id')
            price = data.get('price')
            item_float = data.get('item_float')
            stickers = data.get('stickers', [])
            
            if 'Case' in item_name:
                return
            
            # --- [AUTOBUY BLOCK] ---
            try:
                if(item_float is not None and not any(word.lower() in item_name.lower() for word in AUTO_BUY_SETTINGS['EXCLUDED_KEYWORDS'])):
                    try:
                        skin_float = float(item_float)
                        if skin_float < AUTO_BUY_SETTINGS['FLOAT_THRESHOLD'] and price <= AUTO_BUY_SETTINGS['MAX_PRICE']:
                            logger.info(f"Попыка автобая: {item_name} | Float: {skin_float} | Price: {price}")
                            try:
                                result = await self.purchaser.buy_skin(item_id, max_price=price)
                                if result:
                                    message = (
                                        f"✅ <b>Автопокупка успешна!</b>\n"
                                        f"Название: {item_name}\n"
                                        f"Float: {skin_float}\n"
                                        f"Цена: USD: {price}\n"
                                        f"      RUB: {rates.convert('USD', 'RUB', {price})} \n"
                                        f"      CNY: {rates.convert('USD', 'CNY', {price})} \n"
                                        f"ID: {item_id}"
                                    )
                                    await self.tracker.send_alert(message)
                            except Exception as e:
                                logger.error(f"Автопокупка не удалась: {e}")
                    except Exception as e:
                        logger.error(f"Ошибка при попытке автобая: {e}")
            except Exception as e:
                logger.error(f"Ошибка в блоке автопокупки: {e}")
            # --- END [AUTOBUY BLOCK]
            
            # Проверяем критерии
            check_result = self._check_item_criteria(item_float, stickers)
            
            if check_result['matches']:
                message = self._format_new_item_message(
                    data, appear_time, check_result
                )
                
                logger.info(f"[NEW ITEM] {item_name} - Float: {item_float}, "
                          f"Stickers: {len(check_result['stickers'])}, "
                          f"Charms: {len(check_result['charms'])}")
                
                await self.tracker.send_alert(message, item_id, price)
                self.tracker.sent_new_items[str(item_id)] = datetime.now()
                
        except Exception as e:
            logger.error(f"Ошибка обработки нового предмета: {e}")

    async def process_sold_item(self, data: Dict[str, Any], appear_time: str, sold_time: str):
        """Обработка проданного предмета"""
        if 'Case' in data.get('name', ''):
            return
        
        try:
            item_name = data.get('name', '')
            item_id = data.get('id')
            item_float = data.get('item_float')
            stickers = data.get('stickers', [])
            
            check_result = self._check_item_criteria(item_float, stickers)
            
            if check_result['matches']:
                duration = self.calculate_duration(appear_time, sold_time)
                message = self._format_sold_item_message(
                    data, appear_time, sold_time, duration, check_result
                )
                
                logger.info(f"[SOLD] {data['name']}")
                await self.tracker.send_alert(message)
                self.tracker.sent_sold_items[str(item_id)] = datetime.now()
                
        except Exception as e:
            logger.error(f"Ошибка обработки проданного предмета: {e}")

    def _check_item_criteria(self, item_float: Any, stickers: List[Dict]) -> Dict:
        """Проверка критериев предмета"""
        result = {
            'matches': False,
            'matches_float': False,
            'stickers': [],
            'charms': [],
            'highlights': []
        }
        
        # Проверка float
        if item_float is not None:
            try:
                skin_float = float(item_float)
                for range_min, range_max in self.float_ranges:
                    if range_min <= skin_float <= range_max:
                        result['matches_float'] = True
                        result['float_value'] = skin_float
                        break
            except (ValueError, TypeError):
                pass
        
        # Проверка стикеров/чармов/хайлайтов
        if stickers:
            for sticker in stickers:
                sticker_name = sticker.get('name', '')
                
                for keyword in STICKER_KEYWORDS:
                    if keyword.lower() in sticker_name.lower():
                        result['stickers'].append({
                            'name': sticker_name,
                            'wear': sticker.get('wear', 0),
                            'slot': sticker.get('slot', 0)
                        })
                        break
                
                for keyword in CHARM_KEYWORDS:
                    if keyword.lower() in sticker_name.lower():
                        result['charms'].append({
                            'name': sticker_name,
                            'wear': sticker.get('wear', 0),
                            'slot': sticker.get('slot', 0)
                        })
                        break
                
                for keyword in HIGHLIGHT_KEYWORDS:
                    if keyword.lower() in sticker_name.lower():
                        result['highlights'].append({
                            'name': sticker_name,
                            'slot': sticker.get('slot', 0)
                        })
                        break
        
        result['matches'] = (result['matches_float'] or 
                           result['stickers'] or 
                           result['charms'] or 
                           result['highlights'])
        
        return result

    def _format_new_item_message(self, data: Dict, appear_time: str, 
                                check_result: Dict) -> str:
        """Форматирование сообщения о новом предмете"""
        reasons = []
        
        if check_result['matches_float']:
            reasons.append(f"✅ Float: {check_result['float_value']:.6f}")
        
        if check_result['stickers']:
            stickers_text = "\n".join([
                f"  • {s['name']} (слот {s['slot']}, износ: {s['wear']}%)"
                for s in check_result['stickers']
            ])
            reasons.append(f"🏷 Стикеры:\n{stickers_text}")
        
        if check_result['charms']:
            charms_text = "\n".join([
                f"  • {c['name']} (слот {c['slot']}, износ: {c['wear']}%)"
                for c in check_result['charms']
            ])
            reasons.append(f"💎 Чармы:\n{charms_text}")

        if check_result['highlights']:
            highlight_text = "\n".join([
                f"  • {h['name']} (слот {h['slot']})"
                for h in check_result['highlights']
                        ])
            reasons.append(f"💎 Хайлайты:\n{highlight_text}")
        
        message = (
            f"<b>🆕 НОВЫЙ СКИН </b>\n"
            f"⏱ Появился: {appear_time}\n"
            f"Название: {data.get('name')}\n"
            f"Цена: ${data.get('price')}\n"
            f"Цена: USD: {data.get('price')}\n"  
            f"      RUB: {rates.convert('USD', 'RUB', data.get('price'))} \n"
            f"      CNY: {rates.convert('USD', 'CNY', data.get('price'))} \n"
            f"Float: {data.get('item_float')}\n"
            f"ID: {data.get('id')}\n\n"
            f"Причины уведомления:\n" + "\n".join(reasons)
        )
        
        if data.get('item_float'):
            message += f"\n\nПаттерн: {data.get('item_paint_index', 'N/A')}"
            message += f"\nSeed: {data.get('item_paint_seed', 'N/A')}"
        
        return message

    def _format_sold_item_message(self, data: Dict, appear_time: str, 
                                 sold_time: str, duration: str, 
                                 check_result: Dict) -> str:
        """Форматирование сообщения о проданном предмете"""
        details = []
        
        if check_result['matches_float']:
            details.append(f"Float: {check_result['float_value']:.6f}")
        if check_result['stickers']:
            details.append(f"Стикеры: {', '.join([s['name'] for s in check_result['stickers']])}")
        if check_result['charms']:
            details.append(f"Чармы: {', '.join([c['name'] for c in check_result['charms']])}")
        if check_result['highlights']:
            details.append(f"Хайлайты: {', '.join([h['name'] for h in check_result['highlights']])}")
        
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
        
        return message

    def calculate_duration(self, start_time: str, end_time: str) -> str:
        """Расчет продолжительности"""
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
