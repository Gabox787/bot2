import asyncio
import os
import grid_config as config
from pybit.unified_trading import HTTP
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from grid_logic import calculate_grid
from flask import Flask
from threading import Thread

# --- БЛОК АНТИ-СОН ---
app = Flask('')
@app.route('/')
def home(): return "Grid Bot is running!"
def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- ГЛОБАЛЬНЫЕ ДАННЫЕ ---
FEE_RATE = 0.001
stats = {
    "total_profit_net": 0.0,
    "last_buy_price": None,
    "trades_count": 0,
    "current_price": 0.0,
    "target_sell": 0.0,
    "target_buy": 0.0
}

# --- КОМАНДА /trades ---
async def trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if stats["last_buy_price"] is None:
        msg = "📭 **Сейчас открытых сделок нет.**\nЖду падения цены до уровня покупки."
    else:
        # Считаем PnL и ROI
        pnl = stats["current_price"] - stats["last_buy_price"]
        roi = (pnl / stats["last_buy_price"]) * 100
        
        msg = (
            f"📊 **ТЕКУЩАЯ СДЕЛКА:**\n"
            f"🔹 Монета: {config.SYMBOL}\n"
            f"🔹 Вход: `{round(stats['last_buy_price'], 2)}` USDT\n"
            f"🔹 Текущая: `{round(stats['current_price'], 2)}` USDT\n\n"
            f"💰 **PnL:** `{round(pnl, 2)}` USDT\n"
            f"📈 **ROI:** `{round(roi, 2)}`%\n\n"
            f"🎯 **Цель закрытия:** `{round(stats['target_sell'], 2)}` USDT\n"
            f"📉 **Докупим на:** `{round(stats['target_buy'], 2)}` USDT"
        )
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- ОСНОВНАЯ ЛОГИКА ---
async def monitor_market(application: Application):
    session = HTTP(testnet=config.IS_TESTNET)
    tg_bot = application.bot
    
    res = session.get_tickers(category="spot", symbol=config.SYMBOL)
    start_price = float(res['result']['list'][0]['lastPrice'])
    buys, sells = calculate_grid(start_price, config.GRID_STEP, config.GRID_LEVELS)
    
    stats["target_buy"] = buys[0]
    stats["target_sell"] = sells[0]

    while True:
        try:
            res = session.get_tickers(category="spot", symbol=config.SYMBOL)
            stats["current_price"] = float(res['result']['list'][0]['lastPrice'])
            
            # Логика BUY
            if stats["current_price"] <= buys[0]:
                buy_fee = stats["current_price"] * FEE_RATE
                stats["last_buy_price"] = stats["current_price"] + buy_fee
                await tg_bot.send_message(chat_id=config.CHAT_ID, text=f"📉 **BUY** зафиксирован: {stats['current_price']}")
                await asyncio.sleep(60)

            # Логика SELL
            if stats["current_price"] >= sells[0] and stats["last_buy_price"]:
                sell_fee = stats["current_price"] * FEE_RATE
                profit = (stats["current_price"] - sell_fee) - stats["last_buy_price"]
                stats["total_profit_net"] += profit
                stats["trades_count"] += 1
                stats["last_buy_price"] = None
                await tg_bot.send_message(chat_id=config.CHAT_ID, text=f"💰 **PROFIT:** +{round(profit, 4)} USDT")
                await asyncio.sleep(60)

            await asyncio.sleep(10)
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(30)

async def main():
    # Запуск Flask
    Thread(target=run).start()
    
    # Настройка Telegram Application
    token = os.getenv('TELEGRAM_TOKEN', config.TELEGRAM_TOKEN)
    application = Application.builder().token(token).build()
    
    # Добавляем команду /trades
    application.add_handler(CommandHandler("trades", trades_command))
    
    # Запускаем мониторинг и бота параллельно
    async with application:
        await application.initialize()
        await application.start_polling()
        await monitor_market(application)

if __name__ == "__main__":
    asyncio.run(main())
