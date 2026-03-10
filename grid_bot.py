import asyncio
import os
import grid_config as config
from pybit.unified_trading import HTTP
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from grid_logic import calculate_grid
from flask import Flask
from threading import Thread
from datetime import datetime

# --- БЛОК АНТИ-СОН (ДЛЯ RENDER) ---
app = Flask('')
start_time_dt = datetime.now()
start_time_str = start_time_dt.strftime("%Y-%m-%d %H:%M:%S")

@app.route('/')
def home(): 
    return f"Grid Bot is running since {start_time_str}"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- ГЛОБАЛЬНЫЕ ДАННЫЕ ---
FEE_RATE = 0.001  # 0.1% комиссия Bybit
INITIAL_DEPOSIT = 1000.0
TRADE_AMOUNT_USD = INITIAL_DEPOSIT / config.GRID_LEVELS 

stats = {
    "balance_usd": INITIAL_DEPOSIT,
    "total_profit_net": 0.0,
    "last_buy_price": None,
    "last_buy_volume_btc": 0.0,
    "trades_count": 0,
    "wins_count": 0,
    "current_price": 0.0,
    "target_sell": 0.0,
    "target_buy": 0.0
}

# --- ОБРАБОТЧИКИ КОМАНД ---

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 **МЕНЮ УПРАВЛЕНИЯ**\n"
        "━━━━━━━━━━━━━━━\n"
        "📊 /trades — Текущая цена, сделка и PnL\n"
        "📈 /stats — Винрейт и общий профит\n"
        "❓ /help — Список всех команд\n"
        "━━━━━━━━━━━━━━━\n"
        f"⚙️ Монета: `{config.SYMBOL}` | Шаг: `{config.GRID_STEP * 100}%`"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    header = f"🪙 **{config.SYMBOL}:** `{round(stats['current_price'], 2)}` USDT\n"
    if stats["last_buy_price"] is None:
        msg = f"{header}💰 **ДЕПОЗИТ: {round(stats['balance_usd'], 2)}$**\n📭 Жду покупку на `{round(stats['target_buy'], 2)}`"
    else:
        current_value = stats["last_buy_volume_btc"] * stats["current_price"]
        pnl = current_value - TRADE_AMOUNT_USD
        roi = (pnl / TRADE_AMOUNT_USD) * 100
        msg = (
            f"{header}"
            f"📊 **В СДЕЛКЕ:**\n"
            f"💵 Вход: `{round(TRADE_AMOUNT_USD, 2)}$` по `{round(stats['last_buy_price'], 2)}` \n"
            f"💰 **PnL:** `{round(pnl, 2)}$` ({round(roi, 2)}%)\n"
            f"🎯 Цель продажи: `{round(stats['target_sell'], 2)}`"
        )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_roi = (stats["total_profit_net"] / INITIAL_DEPOSIT) * 100
    winrate = (stats["wins_count"] / stats["trades_count"] * 100) if stats["trades_count"] > 0 else 0
    msg = (
        f"📈 **СТАТИСТИКА:**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏆 Винрейт: `{round(winrate, 1)}%` ({stats['wins_count']}/{stats['trades_count']})\n"
        f"💵 Профит: `{round(stats['total_profit_net'], 2)}$` \n"
        f"💰 Баланс: `{round(stats['balance_usd'], 2)}$` \n"
        f"🔄 Всего сделок: `{stats['trades_count']}`\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⏱ Запуск: `{start_time_str}`"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- ЛОГИКА МОНИТОРИНГА РЫНКА ---

async def monitor_market(bot):
    session = HTTP(testnet=config.IS_TESTNET)
    
    # Первичный расчет уровней
    res = session.get_tickers(category="spot", symbol=config.SYMBOL)
    start_price = float(res['result']['list'][0]['lastPrice'])
    buys, _ = calculate_grid(start_price, config.GRID_STEP, config.GRID_LEVELS)
    
    stats["target_buy"] = buys[0]
    # Временная цель продажи до первой покупки
    stats["target_sell"] = stats["target_buy"] * (1 + config.GRID_STEP + 0.0025)

    while True:
        try:
            res = session.get_tickers(category="spot", symbol=config.SYMBOL)
            stats["current_price"] = float(res['result']['list'][0]['lastPrice'])
            
            # 1. ЛОГИКА ПОКУПКИ (BUY)
            if stats["current_price"] <= stats["target_buy"] and stats["last_buy_price"] is None:
                stats["last_buy_price"] = stats["current_price"]
                # Считаем объем BTC за вычетом комиссии 0.1% за вход
                stats["last_buy_volume_btc"] = (TRADE_AMOUNT_USD * (1 - FEE_RATE)) / stats["last_buy_price"]
                
                # РАСЧЕТ БЕЗУБЫТКА: Вход + Твой Шаг + 0.25% (запас на обе комиссии)
                stats["target_sell"] = stats["last_buy_price"] * (1 + config.GRID_STEP + 0.0025)
                
                now = datetime.now().strftime("%H:%M:%S")
                await bot.send_message(
                    chat_id=config.CHAT_ID, 
                    text=f"📉 **BUY EXECUTION** [{now}]\n📍 Цена: `{stats['last_buy_price']}`\n🎯 Цель продажи: `{round(stats['target_sell'], 2)}`"
                )

            # 2. ЛОГИКА ПРОДАЖИ (SELL)
            if stats["current_price"] >= stats["target_sell"] and stats["last_buy_price"]:
                sell_price = stats["current_price"]
                now = datetime.now().strftime("%H:%M:%S")
                
                # Выручка после комиссии 0.1% за выход
                net_proceeds = (stats["last_buy_volume_btc"] * sell_price) * (1 - FEE_RATE)
                profit = net_proceeds - TRADE_AMOUNT_USD
                
                stats["total_profit_net"] += profit
                stats["balance_usd"] += profit
                stats["trades_count"] += 1
                if profit > 0: stats["wins_count"] += 1
                
                msg = (
                    f"✅ **SELL EXECUTION**\n"
                    f"⏰ Время: `{now}`\n"
                    f"📍 Цена: `{sell_price}`\n"
                    f"➕ Профит: `+{round(profit, 2)}$`"
                )
                
                # Сброс и установка новой цели покупки ниже цены продажи
                stats["last_buy_price"] = None
                stats["target_buy"] = sell_price * (1 - config.GRID_STEP)
                
                await bot.send_message(chat_id=config.CHAT_ID, text=msg, parse_mode='Markdown')

            await asyncio.sleep(10)
        except Exception as e:
            print(f"Ошибка мониторинга: {e}")
            await asyncio.sleep(30)

async def main():
    Thread(target=run_flask, daemon=True).start()
    token = os.getenv('TELEGRAM_TOKEN', config.TELEGRAM_TOKEN)
    application = Application.builder().token(token).build()
    
    application.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Бот в сети! Используй /help")))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("trades", trades_command))
    application.add_handler(CommandHandler("stats", stats_command))

    await application.initialize()
    await application.start()
    asyncio.create_task(monitor_market(application.bot))
    await application.updater.start_polling()
    
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
