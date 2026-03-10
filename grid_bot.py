import asyncio
import grid_config as config
from pybit.unified_trading import HTTP
from telegram import Bot
from grid_logic import calculate_grid

# Подключаемся к бирже
session = HTTP(testnet=config.IS_TESTNET)

async def get_current_price():
    """Получает актуальную цену с биржи Bybit"""
    try:
        response = session.get_tickers(category="spot", symbol=config.SYMBOL)
        return float(response['result']['list'][0]['lastPrice'])
    except Exception as e:
        print(f"Ошибка при получении цены: {e}")
        return None

async def monitor_market():
    # Инициализируем бота внутри асинхронного контекста
    async with Bot(token=config.TELEGRAM_TOKEN) as tg_bot:
        print(f"--- Бот-советник запущен для {config.SYMBOL} ---")
        
        # --- ВОТ ЭТА КОМАНДА ДЛЯ ПРОВЕРКИ ---
        try:
            await tg_bot.send_message(
                chat_id=config.CHAT_ID, 
                text="🤖 **Связь установлена!**\nЯ начал следить за рынком.", 
                parse_mode='Markdown'
            )
            print("Тестовое сообщение отправлено в Telegram!")
        except Exception as e:
            print(f"Ошибка отправки в Telegram: {e}")
            print("Проверь CHAT_ID и нажал ли ты кнопку START в боте.")
        # ------------------------------------

        # 1. Берем стартовую цену и строим виртуальную сетку
        start_price = await get_current_price()
        if not start_price:
            print("Не удалось получить начальную цену. Проверь интернет или символ монеты.")
            return

        buys, sells = calculate_grid(start_price, config.GRID_STEP, config.GRID_LEVELS)
        
        print(f"Стартовая цена: {start_price} USDT")
        print(f"Сетка построена. Жду покупку на {buys[0]} или продажу на {sells[0]}")

        # 2. Бесконечный цикл слежения за рынком
        while True:
            try:
                current_price = await get_current_price()
                if not current_price:
                    await asyncio.sleep(10)
                    continue

                # Проверяем касание первого уровня покупки
                if current_price <= buys[0]:
                    message = f"📉 **GRID SIGNAL: BUY**\nЦена {config.SYMBOL} упала до: **{current_price}**\nТвой уровень покупки: {buys[0]}"
                    await tg_bot.send_message(chat_id=config.CHAT_ID, text=message, parse_mode='Markdown')
                    print("Сигнал на покупку отправлен!")
                    break 
                    
                # Проверяем касание первого уровня продажи
                elif current_price >= sells[0]:
                    message = f"📈 **GRID SIGNAL: SELL**\nЦена {config.SYMBOL} выросла до: **{current_price}**\nТвой уровень продажи: {sells[0]}"
                    await tg_bot.send_message(chat_id=config.CHAT_ID, text=message, parse_mode='Markdown')
                    print("Сигнал на продажу отправлен!")
                    break

                await asyncio.sleep(5) 
                
            except Exception as e:
                print(f"Ошибка в цикле: {e}")
                await asyncio.sleep(10)

if __name__ == "__main__":
    try:
        asyncio.run(monitor_market())
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем.")
