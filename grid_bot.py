import asyncio
import os
import grid_config as config
from pybit.unified_trading import HTTP
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from grid_logic import calculate_grid
from flask import Flask
from threading import Thread

# --- БЛОК АНТИ-СОН (FLASK) ---
app = Flask('')
@app.route('/')
def home(): return "Grid Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- ГЛОБАЛЬНЫЕ ДАННЫЕ ---
FEE_RATE = 0.001
INITIAL_DEPOSIT = 1000.0
TRADE_AMOUNT_USD = INITIAL_DEPOSIT / config.GRID_LEVELS 

stats = {
    "balance_usd": INITIAL_DEPOSIT,
    "total_profit_net": 0.0,
    "last_buy_price": None,
    "last_buy_volume_btc": 0.0,
    "trades_count": 0,
    "current_price": 0.0,
    "target_sell": 0.0,
    "target_buy": 0.0
}

# --- КОМАНДА /trades ---
async def trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if stats["last_buy_price"] is None:
        msg = f"💰 **ДЕПОЗИТ: {round(stats['balance_usd'], 2)}$**\n📭 Сделок нет. Жду цену `{round(stats['target_buy'], 2)}`"
    else:
        current_value = stats["last_buy_volume_btc"] * stats["current_price"]
        pnl = current_value - TRADE_AMOUNT_USD
        roi = (pnl / TRADE_AMOUNT_USD) * 100
        msg = (
            f"📊 **ТЕКУЩАЯ СДЕЛКА:**\n💵 Вложено: `{round(TRADE_AMOUNT_USD, 2)}$`\n"
            f"₿ Куплено: `{round(stats['last_buy_volume_btc'], 6)}` BTC\n"
            f"📍 Вход: `{round(stats['last_buy_price'], 2)}` USDT\n\n"
            f"💰 **PnL:** `{round(pnl, 2)}$` ({round(roi, 2)}%)\n"
            f"🎯 Цель: `{round(stats['target_sell'], 2)}` USDT"
        )
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- МОНИТОРИНГ РЫНКА ---
async def monitor_market(bot):
    session = HTTP(testnet=config.IS_TESTNET)
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
            if stats["current_price"] <= buys[0] and stats["last_buy_price"] is None:
                stats["last_buy_price"] = stats["current_price"]
                stats["last_buy_volume_btc"] = (TRADE_AMOUNT_USD * (1 - FEE_RATE)) / stats["last_buy_price"]
                await bot.send_message(chat_id=config.CHAT_ID, text=f"📉 **BUY** на {stats['last_buy_price']}")

            # Логика SELL
            if stats["current_price"] >= sells[0] and stats["last_buy_price"]:
                profit = (stats["last_buy_volume_btc"] * stats["current_price"] * (1 - FEE_RATE)) - TRADE_AMOUNT_USD
                stats["balance_usd"] += profit
                stats["last_buy_price"] = None
                await bot.send_message(chat_id=config.CHAT_ID, text=f"✅ **SELL! Профит: +{round(profit, 2)}$**")

            await asyncio.sleep(10)
        except Exception as e:
            await asyncio.sleep(30)

async def main():
    # Запуск Flask в отдельном потоке
    Thread(target=run_flask, daemon=True).start()

    # Настройка бота
    token = os.getenv('TELEGRAM_TOKEN', config.TELEGRAM_TOKEN)
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("trades", trades_command))

    # Инициализация
    await application.initialize()
    await application.start()
    
    # Запуск мониторинга в фоне
    asyncio.create_task(monitor_market(application.bot))
    
    # Запуск бесконечного цикла обновлений (polling)
    await application.updater.start_polling()
    
    # Держим main() живым
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
