"""Обработчики Telegram команд и callback'ов"""
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from forex_python.converter import CurrencyRates

from config import API_KEY, STEAM_PARTNER, STEAM_TOKEN
from models.skin_purchaser import SkinPurchaser
from utils.logger import setup_logger

logger = setup_logger(__name__)


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


async def handle_purchase_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки покупки"""
    query = update.callback_query
    
    try:
        await query.answer("Обрабатываю покупку...")
        
        callback_data = query.data
        logger.info(f"Получен callback: '{callback_data}'")
        
        # Извлекаем ID предмета
        item_id = extract_item_id(callback_data, context)
        
        if item_id is None:
            await query.edit_message_text(
                f"❌ Ошибка: не удалось определить ID предмета\n"
                f"Данные: {callback_data}"
            )
            return
        
        # Получаем данные о предмете
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
        await process_purchase(query, item_id, price, context)
        
    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        import traceback
        traceback.print_exc()
        try:
            await query.answer("❌ Произошла ошибка", show_alert=True)
        except:
            pass


def extract_item_id(callback_data: str, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Извлечение ID предмета из callback_data"""
    if not callback_data:
        return None
    
    # Способ 1: формат buy_ID
    if callback_data.startswith("buy_"):
        try:
            return int(callback_data.replace("buy_", ""))
        except ValueError:
            pass
    
    # Способ 2: поиск в сохраненных данных
    if 'purchase_data' in context.bot_data:
        for saved_id in context.bot_data['purchase_data'].keys():
            if saved_id in callback_data or callback_data in f"buy_{saved_id}":
                return int(saved_id)
    
    # Способ 3: извлечение чисел
    numbers = re.findall(r'\d+', callback_data)
    if numbers:
        return int(numbers[0])
    
    return None


async def process_purchase(query, item_id: int, price: float, context: ContextTypes.DEFAULT_TYPE):
    """Обработка покупки"""
    purchaser = SkinPurchaser()
    
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
                    f"Цена: USD: {skin.get('price')}\n"
		    f"      RUB: CurrencyRates().convert('USD', 'RUB', skin.get('price')) \n"
                    f"      CNY: CurrencyRates().convert('USD', 'CNY', skin.get('price')) \n"
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
            
    except Exception as e:
        logger.error(f"Ошибка при покупке: {e}")
        await query.edit_message_text(
            f"❌ <b>Ошибка при покупке</b>\n\n"
            f"Детали: {str(e)[:200]}",
            parse_mode="HTML"
        )
