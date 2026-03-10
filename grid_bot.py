import asyncio
import grid_config as config
from pybit.unified_trading import HTTP
from telegram import Bot
from grid_logic import calculate_grid

# Хранилище для статистики
stats = {
    "total_profit": 0.0,
    "last_buy_price": None,
    "trades_count": 0
}

async def monitor_market():
    session = HTTP(testnet=config.IS_TESTNET)
    
    async with Bot(token=config.TELEGRAM_TOKEN) as tg_bot:
        print(f"--- БОТ ЗАПУЩЕН И СЧИТАЕТ ПРИБЫЛЬ ---")
        await tg_bot.send_message(chat_id=config.CHAT_ID, text="🤖 Бот перешел в режим бесконечного слежения с расчетом прибыли!")

        # Получаем стартовую цену
        res = session.get_tickers(category="spot", symbol=config.SYMBOL)
        start_price = float(res['result']['list'][0]['lastPrice'])
        
        # Строим сетку
        buys, sells = calculate_grid(start_price, config.GRID_STEP, config.GRID_LEVELS)
        print(f"Старт: {start_price} USDT. Жду сигналов...")

        while True:
            try:
                res = session.get_tickers(category="spot", symbol=config.SYMBOL)
                current_price = float(res['result']['list'][0]['lastPrice'])
                
                # ЛОГИКА ПОКУПКИ (Цена упала до уровня)
                for b_price in buys:
                    if current_price <= b_price:
                        stats["last_buy_price"] = current_price
                        msg = f"📉 **СИГНАЛ BUY**\nЦена: {current_price}\n_Запомнил цену для расчета прибыли._"
                        await tg_bot.send_message(chat_id=config.CHAT_ID, text=msg, parse_mode='Markdown')
                        print(f"Зафиксирована покупка по {current_price}")
                        # Ждем немного, чтобы не спамить на одном уровне
                        await asyncio.sleep(60) 

                # ЛОГИКА ПРОДАЖИ (Цена выросла до уровня)
                for s_price in sells:
                    if current_price >= s_price:
                        trade_text = f"📈 **СИГНАЛ SELL**\nЦена: {current_price}"
                        
                        # Если до этого была покупка, считаем профит
                        if stats["last_buy_price"] is not None:
                            profit = current_price - stats["last_buy_price"]
                            stats["total_profit"] += profit
                            stats["trades_count"] += 1
                            stats["last_buy_price"] = None # Сбрасываем после продажи
                            
                            trade_text += f"\n\n💰 **Сделка закрыта!**\nПрофит этой сделки: +{round(profit, 2)} USDT\nОбщая прибыль: **{round(stats['total_profit'], 2)}** USDT\nВсего сделок: {stats['trades_count']}"
                        
                        await tg_bot.send_message(chat_id=config.CHAT_ID, text=trade_text, parse_mode='Markdown')
                        print(f"Зафиксирована продажа по {current_price}. Общий профит: {stats['total_profit']}")
                        await asyncio.sleep(60)

                await asyncio.sleep(5) # Проверка каждые 5 секунд
                
            except Exception as e:
                print(f"Ошибка: {e}")
                await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(monitor_market())
