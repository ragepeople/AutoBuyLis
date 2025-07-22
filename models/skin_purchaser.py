"""Модуль для покупки скинов"""
import aiohttp
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from config import API_KEY, STEAM_PARTNER, STEAM_TOKEN, API_BUY_URL
from utils.logger import setup_logger

logger = setup_logger(__name__)


class SkinPurchaser:
    """Класс для покупки скинов"""
    
    def __init__(self, api_key: str = API_KEY, partner: str = STEAM_PARTNER, token: str = STEAM_TOKEN):
        self.api_key = api_key
        self.partner = partner
        self.token = token
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
        
    async def buy_skin(self, skin_id: int, max_price: Optional[float] = None) -> Dict[str, Any]:
        """Покупка одного скина"""
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
            async with session.post(API_BUY_URL, headers=self.headers, json=data) as response:
                if response.status in [200, 201]:
                    result = await response.json()
                    return result.get('data', result)
                else:
                    error_text = await response.text()
                    raise Exception(f"Ошибка покупки: {error_text}")