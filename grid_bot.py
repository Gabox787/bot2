import asyncio
import grid_config as config
from pybit.unified_trading import HTTP  # Библиотека для связи с биржей
from telegram import Bot

# Подключаемся к бирже (даже без ключей можно смотреть цену)
session = HTTP(testnet=config.IS_TESTNET)
tg_bot = Bot(token=config.TELEGRAM_TOKEN)

async def get_current_price():
    """Получает актуальную цену с биржи"""
    response = session.get_tickers(category="spot", symbol=config.SYMBOL)
    return float(response['result']['list'][0]['lastPrice'])

async def monitor_market():
    print(f"--- Бот-советник запущен для {config.SYMBOL} ---")
    
    # 1. Берем стартовую цену и строим виртуальную сетку
    start_price = await get_current_price()
    from grid_logic import calculate_grid
    buys, sells = calculate_grid(start_price, config.GRID_STEP, config.GRID_LEVELS)
    
    print(f"Стартовая цена: {start_price}. Сетка построена.")
    print(f"Жду цену покупки: {buys[0]} или продажи: {sells[0]}")

    # 2. Бесконечный цикл слежения
    while True:
        try:
            current_price = await get_current_price()
            
            # Проверяем касание первого уровня покупки
            if current_price <= buys[0]:
                message = f"📉 Цена упала до уровня покупки: {current_price}\nПокупаем {config.SYMBOL}?"
                await tg_bot.send_message(chat_id=config.CHAT_ID, text=message)
                break # Остановим для теста, чтобы не спамил
                
            # Проверяем касание первого уровня продажи
            elif current_price >= sells[0]:
                message = f"📈 Цена выросла до уровня продажи: {current_price}\nПродаем {config.SYMBOL}?"
                await tg_bot.send_message(chat_id=config.CHAT_ID, text=message)
                break
                
            await asyncio.sleep(5) # Проверяем каждые 5 секунд
        except Exception as e:
            print(f"Ошибка: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(monitor_market())
