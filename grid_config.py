# Telegram настройки
TELEGRAM_TOKEN = '8530434492:AAHE7S6GHnLImGUIkpyqeKrr4slOwR5gIDU'
# Убрали кавычки, чтобы ID был числом (это важно для библиотеки python-telegram-bot)
CHAT_ID = 715162339

# Настройки сетки
SYMBOL = "BTCUSDT"
# Уменьшил шаг до 0.001 (0.1%), чтобы бот прислал сигнал почти сразу после запуска
GRID_STEP = 1 
GRID_LEVELS = 3

# Добавили пропущенный параметр, на который ругался бот
IS_TESTNET = False
