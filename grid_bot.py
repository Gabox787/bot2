import asyncio
import os
import logging
from datetime import datetime
from threading import Thread

# Библиотеки для работы с API и Telegram
import grid_config as config
from pybit.unified_trading import HTTP
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from grid_logic import calculate_grid
from flask import Flask

# Настраиваем логи, чтобы видеть всё, что происходит, в консоли Render
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- БЛОК FLASK (ДЕРЖИМ СЕРВЕР ЖИВЫМ) ---
app = Flask('')
start_time_dt = datetime.now()
start_time_str = start_time_dt.strftime("%Y-%m-%d %H:%M:%S")

@app.route('/')
def home():
    return f"Бот активен с {start_time_str}. Статус: OK"

def run_flask():
    # Render автоматически подставляет порт
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- ГЛОБАЛЬНЫЕ ДАННЫЕ И СТАТИСТИКА ---
FEE_RATE = 0.001          # Стандартная комиссия Bybit 0.1%
INITIAL_DEPOSIT = 1000.0   # Твой виртуальный банк
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

# --- КОМАНДЫ ДЛЯ ТЕЛЕГРАМ ---

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список всех команд"""
    msg = (
        "🤖 **МЕНЮ УПРАВЛЕНИЯ**\n"
        "━━━━━━━━━━━━━━━\n"
        "📊 /trades — Текущая цена и статус сделки\n"
        "📈 /stats — Прибыль и винрейт\n"
        "❓ /help — Список всех команд\n"
        "━━━━━━━━━━━━━━━\n"
        f"⚙️ Монета: `{config.SYMBOL}` | Шаг: `{config.GRID_STEP * 100}%`"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о текущем положении дел"""
    header = f"🪙 **{config.SYMBOL}:** `{round(stats['current_price'], 2)}` USDT\n"
    
    if stats["last_buy_price"] is None:
        msg = (
            f"{header}"
            f"💰 **ДЕПОЗИТ: {round(stats['balance_usd'], 2)}$**\n"
            f"📭 Жду закупа на: `{round(stats['target_buy'], 2)}`"
        )
    else:
        current_value = stats["last_buy_volume_btc"] * stats["current_price"]
        pnl = current_value - TRADE_AMOUNT_USD
        roi = (pnl / TRADE_AMOUNT_USD) * 100
        msg = (
            f"{header}"
            f"📊 **В СДЕЛКЕ**\n"
            f"📍 Вход: `{stats['last_buy_price']}`\n"
            f"💰 **PnL:** `{round(pnl, 2)}$` ({round(roi, 2)}%)\n"
            f"🎯 Цель продажи: `{round(stats['target_sell'], 2)}`"
        )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Общая статистика прибыли"""
    total_roi = (stats["total_profit_net"] / INITIAL_DEPOSIT) * 100
    winrate = (stats["wins_count"] / stats["trades_count"] * 100) if stats["trades_count"] > 0 else 0
    
    msg = (
        f"📈 **ОБЩАЯ СТАТИСТИКА**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏆 Винрейт: `{round(winrate, 1)}%` ({stats['wins_count']}/{stats['trades_count']})\n"
        f"💵 Чистая прибыль: `{round(stats['total_profit_net'], 2)}$` \n"
        f"💰 Тек. баланс: `{round(stats['balance_usd'], 2)}$` \n"
        f"🔄 Всего сделок: `{stats['trades_count']}`\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⏱ Запуск: `{start_time_str}`"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- ОСНОВНОЙ ЦИКЛ МОНИТОРИНГА ---

async def monitor_market(bot):
    session = HTTP(testnet=config.IS_TESTNET)
    
    # Определяем первую точку входа
    res = session.get_tickers(category="spot", symbol=config.SYMBOL)
    start_price = float(res['result']['list'][0]['lastPrice'])
    stats["target_buy"] = start_price * (1 - config.GRID_STEP)
    
    logger.info(f"Мониторинг запущен. Ожидаем покупку на уровне {stats['target_buy']}")

    while True:
        try:
            # Получаем актуальную цену
            res = session.get_tickers(category="spot", symbol=config.SYMBOL)
            stats["current_price"] = float(res['result']['list'][0]['lastPrice'])
            
            # --- 1. ЛОГИКА ПОКУПКИ (BUY) ---
            if stats["current_price"] <= stats["target_buy"] and stats["last_buy_price"] is None:
                stats["last_buy_price"] = stats["current_price"]
                # Считаем объем BTC минус комиссия 0.1%
                stats["last_buy_volume_btc"] = (TRADE_AMOUNT_USD * (1 - FEE_RATE)) / stats["last_buy_price"]
                
                # Ставим цель продажи: Вход + Твой Шаг + 0.25% (запас на комиссию)
                stats["target_sell"] = stats["last_buy_price"] * (1 + config.GRID_STEP + 0.0025)
                
                now = datetime.now().strftime("%H:%M:%S")
                await bot.send_message(
                    chat_id=config.CHAT_ID, 
                    text=f"📉 **BUY EXECUTION** [{now}]\n📍 Цена: `{stats['last_buy_price']}`\n🎯 Цель: `{round(stats['target_sell'], 2)}`"
                )
                logger.info(f"Куплено по {stats['last_buy_price']}")

            # --- 2. ЛОГИКА ПРОДАЖИ (SELL) ---
            elif stats["current_price"] >= stats["target_sell"] and stats["last_buy_price"] is not None:
                sell_price = stats["current_price"]
                now = datetime.now().strftime("%H:%M:%S")
                
                # Считаем деньги после продажи минус комиссия 0.1%
                net_proceeds = (stats["last_buy_volume_btc"] * sell_price) * (1 - FEE_RATE)
                profit = net_proceeds - TRADE_AMOUNT_USD
                
                # Обновляем статистику
                stats["total_profit_net"] += profit
                stats["balance_usd"] += profit
                stats["trades_count"] += 1
                if profit > 0: stats["wins_count"] += 1
                
                await bot.send_message(
                    chat_id=config.CHAT_ID, 
                    text=f"✅ **SELL EXECUTION** [{now}]\n📍 Цена: `{sell_price}`\n➕ Профит: `+{round(profit, 2)}$`"
                )
                logger.info(f"Продано по {sell_price}. Профит: {profit}")
                
                # Сбрасываем сделку и ставим новую покупку ниже цены продажи
                stats["last_buy_price"] = None
                stats["target_buy"] = sell_price * (1 - config.GRID_STEP)

            await asyncio.sleep(10) # Проверка каждые 10 секунд
            
        except Exception as e:
            logger.error(f"Ошибка в цикле мониторинга: {e}")
            await asyncio.sleep(20)

# --- ЗАПУСК ВСЕЙ СИСТЕМЫ ---

async def main():
    # Запуск Flask сервера в отдельном потоке
    Thread(target=run_flask, daemon=True).start()

    # Инициализация Telegram
    token = os.getenv('TELEGRAM_TOKEN', config.TELEGRAM_TOKEN)
    application = Application.builder().token(token).build()
    
    # Добавление команд
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("trades", trades_command))
    application.add_handler(CommandHandler("stats", stats_command))

    # Старт бота
    await application.initialize()
    await application.start()
    
    # Запуск задачи мониторинга рынка
    asyncio.create_task(monitor_market(application.bot))
    
    # Запуск получения сообщений
    await application.updater.start_polling()
    
    # Бесконечный цикл, чтобы скрипт не завершался
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
