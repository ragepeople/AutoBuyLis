"""Конфигурация приложения"""
from dotenv import load_dotenv
import os

load_dotenv() 


# API настройки
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_KEY = os.getenv("API_KEY")

# Steam настройки
STEAM_PARTNER = os.getenv("STEAM_PARTNER")
STEAM_TOKEN = os.getenv("STEAM_TOKEN")

# Фильтры поиска
FLOAT_RANGES = [
    (0.00, 0.01),
    (0.07, 0.071),
    (0.99, 1.00)
]

STICKER_KEYWORDS = [
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

# Настройки автопокупки
AUTO_BUY_SETTINGS = {
    'FLOAT_THRESHOLD': 0.001,    # Максимальное значение float
    'MAX_PRICE': 15.0,          # Максимальная цена в долларах
    'EXCLUDED_KEYWORDS': [       # Ключевые слова для исключения
        'Knife',
        '★',                    # Символ редкости ножей
        'Karambit',
        'Bayonet',
        'Daggers',
        'Butterfly',
    ]
}

# WebSocket настройки
WS_URL = "wss://ws.lis-skins.com/connection/websocket"
WS_TOKEN_URL = "https://api.lis-skins.com/v1/user/get-ws-token"
WS_CHANNEL = "public:obtained-skins"

# API endpoints
API_BASE_URL = "https://api.lis-skins.com/v1"
API_BUY_URL = f"{API_BASE_URL}/market/buy"

# Настройки переподключения
MAX_RECONNECT_ATTEMPTS = 10
RECONNECT_DELAY = 5
HEARTBEAT_INTERVAL = 60
NO_EVENTS_TIMEOUT = 150  # 3 минут

# Кеш
CACHE_CLEANUP_INTERVAL = 3600  # 1 час
CACHE_ITEM_TTL = 7200  # 2 часа
DUPLICATE_CHECK_WINDOW = 1800  # 30 минут
