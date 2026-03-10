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
INITIAL_DEPOSIT = 1000.0
# Выделяем часть депозита на одну сделку (у нас 3 уровня, значит 1/3)
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
        msg = (
            f"💰 **ДЕПОЗИТ: {round(stats['balance_usd'], 2)}$**\n"
            f"📭 Открытых сделок нет. Жду цену `{round(stats['target_buy'], 2)}`"
        )
    else:
        # Текущая стоимость купленных BTC
        current_value = stats["last_buy_volume_btc"] * stats["current_price"]
        # Стоимость при покупке (включая комиссию)
        entry_cost = TRADE_AMOUNT_USD 
        pnl = current_value - entry_cost
        roi = (pnl / entry_cost) * 100
        
        msg = (
            f"📊 **ТЕКУЩАЯ СДЕЛКА:**\n"
            f"💵 Вложено: `{round(entry_cost, 2)}$`\n"
            f"₿ Куплено: `{round(stats['last_buy_volume_btc'], 6)}` BTC\n"
            f"📍 Цена входа: `{round(stats['last_buy_price'], 2)}` USDT\n\n"
            f"💰 **Текущий PnL:** `{round(pnl, 2)}$` ({round(roi, 2)}%)\n"
            f"🎯 Продажа на: `{round(stats['target_sell'], 2)}` USDT"
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
            
            # --- ЛОГИКА BUY ---
            if stats["current_price"] <= buys[0] and stats["last_buy_price"] is None:
                buy_price = stats["current_price"]
                # Вычитаем комиссию из объема покупки
                net_amount = TRADE_AMOUNT_USD * (1 - FEE_RATE)
                stats["last_buy_volume_btc"] = net_amount / buy_price
                stats["last_buy_price"] = buy_price
                
                msg = (
                    f"📉 **ИСПОЛНЕНО: BUY**\n"
                    f"💰 Потрачено: {round(TRADE_AMOUNT_USD, 2)}$\n"
                    f"₿ Получено: {round(stats['last_buy_volume_btc'], 6)} BTC\n"
                    f"📍 Цена: {buy_price}"
                )
                await tg_bot.send_message(chat_id=config.CHAT_ID, text=msg)
                await asyncio.sleep(60)

            # --- ЛОГИКА SELL ---
            if stats["current_price"] >= sells[0] and stats["last_buy_price"]:
                sell_price = stats["current_price"]
                # Выручка после комиссии за продажу
                gross_proceeds = stats["last_buy_volume_btc"] * sell_price
                net_proceeds = gross_proceeds * (1 - FEE_RATE)
                
                profit = net_proceeds - TRADE_AMOUNT_USD
                stats["total_profit_net"] += profit
                stats["balance_usd"] += profit
                stats["trades_count"] += 1
                
                msg = (
                    f"✅ **ИСПОЛНЕНО: SELL**\n"
                    f"💵 Выручка: {round(net_proceeds, 2)}$\n"
                    f"➕ Чистый плюс: +{round(profit, 2)}$\n"
                    f"📊 Новый баланс: {round(stats['balance_usd'], 2)}$"
                )
                stats["last_buy_price"] = None
                await tg_bot.send_message(chat_id=config.CHAT_ID, text=msg)
                await asyncio.sleep(60)

            await asyncio.sleep(10)
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(30)

async def main():
    Thread(target=run).start()
    token = os.getenv('TELEGRAM_TOKEN', config.TELEGRAM_TOKEN)
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("trades", trades_command))
    
    async with application:
        await application.initialize()
        await application.start_polling()
        await monitor_market(application)

if __name__ == "__main__":
    asyncio.run(main())
