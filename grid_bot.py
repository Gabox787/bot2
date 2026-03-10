import asyncio
import grid_config as config
from pybit.unified_trading import HTTP
from telegram import Bot
from grid_logic import calculate_grid

# Константы
FEE_RATE = 0.001  # 0.1% комиссия Bybit

# Хранилище для статистики
stats = {
    "total_profit_net": 0.0,  # Чистая прибыль (с учетом комиссий)
    "last_buy_price": None,
    "trades_count": 0
}

async def monitor_market():
    session = HTTP(testnet=config.IS_TESTNET)
    
    async with Bot(token=config.TELEGRAM_TOKEN) as tg_bot:
        print(f"--- БОТ-СОВЕТНИК С УЧЕТОМ КОМИССИЙ ЗАПУЩЕН ---")
        await tg_bot.send_message(chat_id=config.CHAT_ID, text="🤖 Бот запущен! Считаю чистую прибыль за вычетом 0.1% комиссии.")

        res = session.get_tickers(category="spot", symbol=config.SYMBOL)
        start_price = float(res['result']['list'][0]['lastPrice'])
        
        buys, sells = calculate_grid(start_price, config.GRID_STEP, config.GRID_LEVELS)
        print(f"Старт: {start_price} USDT. Сетка активна.")

        while True:
            try:
                res = session.get_tickers(category="spot", symbol=config.SYMBOL)
                current_price = float(res['result']['list'][0]['lastPrice'])
                
                # --- ЛОГИКА BUY ---
                for b_price in buys:
                    if current_price <= b_price:
                        # Считаем комиссию за покупку
                        buy_fee = current_price * FEE_RATE
                        stats["last_buy_price"] = current_price + buy_fee # Цена входа стала чуть выше из-за комиссии
                        
                        msg = f"📉 **СИГНАЛ BUY**\nЦена: {current_price} USDT\nКомиссия (0.1%): -{round(buy_fee, 4)} USDT"
                        await tg_bot.send_message(chat_id=config.CHAT_ID, text=msg, parse_mode='Markdown')
                        print(f"Покупка по {current_price}. Учтена комиссия {buy_fee}")
                        await asyncio.sleep(60) 

                # --- ЛОГИКА SELL ---
                for s_price in sells:
                    if current_price >= s_price:
                        # Если была покупка, считаем чистый профит
                        if stats["last_buy_price"] is not None:
                            sell_fee = current_price * FEE_RATE
                            # Чистая прибыль = (Цена продажи - Комиссия продажи) - (Цена покупки + Комиссия покупки)
                            net_sell_price = current_price - sell_fee
                            profit = net_sell_price - stats["last_buy_price"]
                            
                            stats["total_profit_net"] += profit
                            stats["trades_count"] += 1
                            stats["last_buy_price"] = None 
                            
                            trade_text = (
                                f"📈 **СИГНАЛ SELL**\nЦена: {current_price} USDT\n"
                                f"Комиссия (0.1%): -{round(sell_fee, 4)} USDT\n\n"
                                f"💰 **Сделка закрыта (Net)!**\n"
                                f"Чистый профит: +{round(profit, 4)} USDT\n"
                                f"Общая прибыль за сессию: **{round(stats['total_profit_net'], 4)}** USDT\n"
                                f"Всего сделок: {stats['trades_count']}"
                            )
                            await tg_bot.send_message(chat_id=config.CHAT_ID, text=trade_text, parse_mode='Markdown')
                            print(f"Продажа по {current_price}. Чистый профит: {profit}")
                        else:
                            # Если покупки не было, просто уведомляем о цене
                            await tg_bot.send_message(chat_id=config.CHAT_ID, text=f"📈 Цена достигла уровня продажи: {current_price}")
                        
                        await asyncio.sleep(60)

                await asyncio.sleep(5) 
                
            except Exception as e:
                print(f"Ошибка: {e}")
                await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(monitor_market())
