import asyncio
import grid_config as config
from pybit.unified_trading import HTTP
from telegram import Bot
from grid_logic import calculate_grid

async def monitor_market():
    # Создаем сессию внутри функции
    session = HTTP(testnet=config.IS_TESTNET)
    
    async with Bot(token=config.TELEGRAM_TOKEN) as tg_bot:
        print(f"--- ЗАПУСК БОТА ДЛЯ {config.SYMBOL} ---")
        
        # СРАЗУ ШЛЕМ ТЕСТ В ТЕЛЕГРАМ
        try:
            await tg_bot.send_message(chat_id=config.CHAT_ID, text="🤖 Бот запущен! Вижу реальный рынок.")
            print("Сообщение в Telegram отправлено успешно!")
        except Exception as e:
            print(f"ОШИБКА TELEGRAM: {e}")

        # ПОЛУЧАЕМ ЦЕНУ
        try:
            res = session.get_tickers(category="spot", symbol=config.SYMBOL)
            start_price = float(res['result']['list'][0]['lastPrice'])
            print(f"Текущая цена на бирже: {start_price} USDT")
        except Exception as e:
            print(f"ОШИБКА БИРЖИ: {e}")
            return

        buys, sells = calculate_grid(start_price, config.GRID_STEP, config.GRID_LEVELS)
        print(f"Сетка: BUY на {buys[0]}, SELL на {sells[0]}")

        while True:
            res = session.get_tickers(category="spot", symbol=config.SYMBOL)
            current_price = float(res['result']['list'][0]['lastPrice'])
            
            if current_price <= buys[0]:
                await tg_bot.send_message(chat_id=config.CHAT_ID, text=f"📉 СИГНАЛ BUY: {current_price}")
                break
            elif current_price >= sells[0]:
                await tg_bot.send_message(chat_id=config.CHAT_ID, text=f"📈 СИГНАЛ SELL: {current_price}")
                break
            
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(monitor_market())
