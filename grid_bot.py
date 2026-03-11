import asyncio
import os
import logging
import time
from datetime import datetime
from threading import Thread

import grid_config as config
from pybit.unified_trading import HTTP
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from grid_logic import calculate_grid
from flask import Flask

# Настройка логов
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask('')
start_time_dt = datetime.now()
start_time_str = start_time_dt.strftime("%Y-%m-%d %H:%M:%S")

@app.route('/')
def home(): return f"Bot alive since {start_time_str}"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# Данные
FEE_RATE = 0.001
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
    "target_buy": 0.0,
    "last_grid_update": time.time()  # Время последнего обновления сетки
}

# --- КОМАНДЫ ---

async def trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    header = f"🪙 **{config.SYMBOL}:** `{round(stats['current_price'], 2)}` USDT\n"
    if stats["last_buy_price"] is None:
        # Считаем, сколько минут висит текущая лимитка
        wait_time = int((time.time() - stats["last_grid_update"]) // 60)
        msg = (f"{header}💰 **ДЕПОЗИТ: {round(stats['balance_usd'], 2)}$**\n"
               f"📭 Жду BUY на `{round(stats['target_buy'], 2)}` (висит {wait_time} мин.)")
    else:
        msg = f"{header}📊 **В СДЕЛКЕ**\n📍 Вход: `{stats['last_buy_price']}`\n🎯 Цель SELL: `{round(stats['target_sell'], 2)}`"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    winrate = (stats["wins_count"] / stats["trades_count"] * 100) if stats["trades_count"] > 0 else 0
    msg = (f"📈 **СТАТИСТИКА:**\n🏆 Винрейт: `{round(winrate, 1)}%`\n"
           f"💵 Профит: `{round(stats['total_profit_net'], 2)}$` \n"
           f"🔄 Сделок: `{stats['trades_count']}`")
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- МОНИТОРИНГ ---

async def monitor_market(bot):
    session = HTTP(testnet=config.IS_TESTNET)
    
    # Инициализация
    res = session.get_tickers(category="spot", symbol=config.SYMBOL)
    stats["current_price"] = float(res['result']['list'][0]['lastPrice'])
    stats["target_buy"] = stats["current_price"] * (1 - config.GRID_STEP)
    stats["last_grid_update"] = time.time()

    while True:
        try:
            res = session.get_tickers(category="spot", symbol=config.SYMBOL)
            stats["current_price"] = float(res['result']['list'][0]['lastPrice'])
            
            # ПРОВЕРКА ТАЙМЕРА (5 минут = 300 секунд)
            # Если мы НЕ в сделке и прошло больше 5 минут — обновляем уровень закупа
            if stats["last_buy_price"] is None:
                if time.time() - stats["last_grid_update"] > 300:
                    old_target = stats["target_buy"]
                    stats["target_buy"] = stats["current_price"] * (1 - config.GRID_STEP)
                    stats["last_grid_update"] = time.time()
                    logger.info(f"Сетка обновлена. Старая цель {old_target} удалена. Новая: {stats['target_buy']}")

            # ЛОГИКА BUY
            if stats["current_price"] <= stats["target_buy"] and stats["last_buy_price"] is None:
                stats["last_buy_price"] = stats["current_price"]
                stats["last_buy_volume_btc"] = (TRADE_AMOUNT_USD * (1 - FEE_RATE)) / stats["last_buy_price"]
                stats["target_sell"] = stats["last_buy_price"] * (1 + config.GRID_STEP + 0.0025)
                
                await bot.send_message(chat_id=config.CHAT_ID, text=f"📉 **BUY** по `{stats['last_buy_price']}`\n🎯 Цель: `{round(stats['target_sell'], 2)}`")

            # ЛОГИКА SELL (Здесь таймер не нужен, ждем профита до победного)
            elif stats["current_price"] >= stats["target_sell"] and stats["last_buy_price"] is not None:
                sell_price = stats["current_price"]
                net_proceeds = (stats["last_buy_volume_btc"] * sell_price) * (1 - FEE_RATE)
                profit = net_proceeds - TRADE_AMOUNT_USD
                
                stats["total_profit_net"] += profit
                stats["balance_usd"] += profit
                stats["trades_count"] += 1
                if profit > 0: stats["wins_count"] += 1
                
                await bot.send_message(chat_id=config.CHAT_ID, text=f"✅ **SELL** по `{sell_price}`\n➕ Профит: `+{round(profit, 2)}$`")
                
                stats["last_buy_price"] = None
                # Сразу после продажи обновляем точку входа и сбрасываем таймер
                stats["target_buy"] = sell_price * (1 - config.GRID_STEP)
                stats["last_grid_update"] = time.time()

            await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Error: {e}")
            await asyncio.sleep(20)

async def main():
    Thread(target=run_flask, daemon=True).start()
    token = os.getenv('TELEGRAM_TOKEN', config.TELEGRAM_TOKEN)
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("trades", trades_command))
    application.add_handler(CommandHandler("stats", stats_command))
    await application.initialize()
    await application.start()
    asyncio.create_task(monitor_market(application.bot))
    await application.updater.start_polling()
    while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
