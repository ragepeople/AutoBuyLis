"""Конфигурация приложения"""

# API настройки
API_KEY = "4e4c7ae1-9e45-4ee2-aef8-b8029f3cb97f"
TELEGRAM_TOKEN = "7726727524:AAEf82GMHiwXRfJkeZdH-t1Qlk5KOrOYc_c"
TELEGRAM_CHAT_ID = "758884131"

# Steam настройки
STEAM_PARTNER = "1057958433"
STEAM_TOKEN = "0KqicsOy"

# Фильтры поиска
FLOAT_RANGES = [
    (0.00, 0.01),
    (0.07, 0.071),
    (0.99, 1.00)
]

STICKER_KEYWORDS = [
    "2013",
    "Katowice 2014",
    "Cologne 2016",
    "Atlanta 2017",
    "Boston 2018",
    "Katowice 2019"
]

CHARM_KEYWORDS = [
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

HIGHLIGHT_KEYWORDS = [
    "Hightlight"
]

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
NO_EVENTS_TIMEOUT = 300  # 5 минут

# Кеш
CACHE_CLEANUP_INTERVAL = 3600  # 1 час
CACHE_ITEM_TTL = 7200  # 2 часа
DUPLICATE_CHECK_WINDOW = 1800  # 30 минут