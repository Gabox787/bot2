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
start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@app.route('/')
def home(): 
    return f"Grid Bot is running since {start_time}"

def run_flask():
    # Render дает порт в переменную окружения PORT
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- ГЛОБАЛЬНЫЕ ДАННЫЕ И СТАТИСТИКА ---
FEE_RATE = 0.001
INITIAL_DEPOSIT = 1000.0
# Делим депозит на количество уровней сетки
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

# --- ОБРАБОТЧИКИ КОМАНД TELEGRAM ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Я твой торговый бот. Напиши /help, чтобы увидеть список команд.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 **МЕНЮ УПРАВЛЕНИЯ**\n"
        "━━━━━━━━━━━━━━━\n"
        "📊 /trades — Текущая сделка, PnL и цели\n"
        "📈 /stats — Общая прибыль, баланс и сделки\n"
        "❓ /help — Список всех команд\n"
        "━━━━━━━━━━━━━━━\n"
        f"⚙️ Монета: `{config.SYMBOL}`\n"
        f"📏 Шаг сетки: `{config.GRID_STEP * 100}%`"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if stats["last_buy_price"] is None:
        msg = (
            f"💰 **ДЕПОЗИТ: {round(stats['balance_usd'], 2)}$**\n"
            f"📭 Сделок нет. Жду падения цены до `{round(stats['target_buy'], 2)}`"
        )
    else:
        current_value = stats["last_buy_volume_btc"] * stats["current_price"]
        pnl = current_value - TRADE_AMOUNT_USD
        roi = (pnl / TRADE_AMOUNT_USD) * 100
        msg = (
            f"📊 **ТЕКУЩАЯ СДЕЛКА:**\n"
            f"💵 Вложено: `{round(TRADE_AMOUNT_USD, 2)}$`\n"
            f"₿ Куплено: `{round(stats['last_buy_volume_btc'], 6)}` BTC\n"
            f"📍 Вход: `{round(stats['last_buy_price'], 2)}` USDT\n\n"
            f"💰 **PnL:** `{round(pnl, 2)}$` ({round(roi, 2)}%)\n"
            f"🎯 Цель закрытия: `{round(stats['target_sell'], 2)}` USDT"
        )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_roi = (stats["total_profit_net"] / INITIAL_DEPOSIT) * 100
    msg = (
        f"📈 **ОБЩАЯ СТАТИСТИКА:**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💵 Чистая прибыль: `{round(stats['total_profit_net'], 2)}$` \n"
        f"📊 Рост депозита: `{round(total_roi, 2)}%` \n"
        f"🔄 Закрытых сделок: `{stats['trades_count']}` \n"
        f"💰 Тек. баланс: `{round(stats['balance_usd'], 2)}$` \n"
        f"━━━━━━━━━━━━━━━\n"
        f"⏱ Запуск бота: `{start_time}`"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- ОСНОВНОЙ ЦИКЛ МОНИТОРИНГА ---

async def monitor_market(bot):
    session = HTTP(testnet=config.IS_TESTNET)
    # Получаем начальную цену для сетки
    res = session.get_tickers(category="spot", symbol=config.SYMBOL)
    start_price = float(res['result']['list'][0]['lastPrice'])
    buys, sells = calculate_grid(start_price, config.GRID_STEP, config.GRID_LEVELS)
    
    stats["target_buy"] = buys[0]
    stats["target_sell"] = sells[0]

    while True:
        try:
            res = session.get_tickers(category="spot", symbol=config.SYMBOL)
            stats["current_price"] = float(res['result']['list'][0]['lastPrice'])
            
            # Логика покупки (BUY)
            if stats["current_price"] <= buys[0] and stats["last_buy_price"] is None:
                buy_price = stats["current_price"]
                # Считаем объем за вычетом комиссии
                net_usd = TRADE_AMOUNT_USD * (1 - FEE_RATE)
                stats["last_buy_volume_btc"] = net_usd / buy_price
                stats["last_buy_price"] = buy_price
                
                await bot.send_message(
                    chat_id=config.CHAT_ID, 
                    text=f"📉 **BUY EXECUTION**\nЦена: {buy_price}\nОбъем: {round(stats['last_buy_volume_btc'], 6)} BTC"
                )

            # Логика продажи (SELL)
            if stats["current_price"] >= sells[0] and stats["last_buy_price"]:
                # Выручка после комиссии
                net_proceeds = (stats["last_buy_volume_btc"] * stats["current_price"]) * (1 - FEE_RATE)
                profit = net_proceeds - TRADE_AMOUNT_USD
                
                stats["total_profit_net"] += profit
                stats["balance_usd"] += profit
                stats["trades_count"] += 1
                stats["last_buy_price"] = None
                
                await bot.send_message(
                    chat_id=config.CHAT_ID, 
                    text=f"✅ **SELL EXECUTION**\nПрофит: +{round(profit, 2)}$\nБаланс: {round(stats['balance_usd'], 2)}$"
                )

            await asyncio.sleep(10)
        except Exception as e:
            print(f"Error in monitor: {e}")
            await asyncio.sleep(30)

# --- ЗАПУСК ---

async def main():
    # Запускаем Flask в отдельном потоке, чтобы Render не закрыл сервис
    Thread(target=run_flask, daemon=True).start()

    # Инициализация Telegram приложения
    token = os.getenv('TELEGRAM_TOKEN', config.TELEGRAM_TOKEN)
    application = Application.builder().token(token).build()
    
    # Регистрация команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("trades", trades_command))
    application.add_handler(CommandHandler("stats", stats_command))

    await application.initialize()
    await application.start()
    
    # Запуск фонового мониторинга
    asyncio.create_task(monitor_market(application.bot))
    
    # Запуск получения сообщений
    await application.updater.start_polling()
    
    # Поддерживаем работу скрипта
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
