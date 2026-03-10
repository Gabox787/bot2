import asyncio
import os
import grid_config as config
from pybit.unified_trading import HTTP
from telegram import Bot
from grid_logic import calculate_grid
from flask import Flask
from threading import Thread

# --- БЛОК ДЛЯ RENDER (АНТИ-СОН) ---
app = Flask('')

@app.route('/')
def home():
    return "Grid Bot is running!"

def run():
    # Render использует порт 8080 или динамический PORT
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()
# ---------------------------------

FEE_RATE = 0.001 
stats = {"total_profit_net": 0.0, "last_buy_price": None, "trades_count": 0}

async def monitor_market():
    session = HTTP(testnet=config.IS_TESTNET)
    async with Bot(token=config.TELEGRAM_TOKEN) as tg_bot:
        print(f"--- ГРИД-БОТ ЗАПУЩЕН ---")
        try:
            await tg_bot.send_message(chat_id=config.CHAT_ID, text="🚀 Бот успешно запущен на Render!")
        except: pass

        res = session.get_tickers(category="spot", symbol=config.SYMBOL)
        start_price = float(res['result']['list'][0]['lastPrice'])
        buys, sells = calculate_grid(start_price, config.GRID_STEP, config.GRID_LEVELS)

        while True:
            try:
                res = session.get_tickers(category="spot", symbol=config.SYMBOL)
                current_price = float(res['result']['list'][0]['lastPrice'])
                
                for b_price in buys:
                    if current_price <= b_price:
                        buy_fee = current_price * FEE_RATE
                        stats["last_buy_price"] = current_price + buy_fee
                        await tg_bot.send_message(chat_id=config.CHAT_ID, text=f"📉 **BUY** на {current_price}")
                        await asyncio.sleep(60) 

                for s_price in sells:
                    if current_price >= s_price:
                        if stats["last_buy_price"] is not None:
                            sell_fee = current_price * FEE_RATE
                            profit = (current_price - sell_fee) - stats["last_buy_price"]
                            stats["total_profit_net"] += profit
                            stats["trades_count"] += 1
                            stats["last_buy_price"] = None 
                            
                            msg = f"💰 **PROFIT: +{round(profit, 4)} USDT**\nВсего: {round(stats['total_profit_net'], 4)}"
                            await tg_bot.send_message(chat_id=config.CHAT_ID, text=msg)
                        await asyncio.sleep(60)

                await asyncio.sleep(10) 
            except Exception as e:
                print(f"Ошибка: {e}")
                await asyncio.sleep(30)

if __name__ == "__main__":
    keep_alive() # Запуск веб-сервера для Render
    asyncio.run(monitor_market())
