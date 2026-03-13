import asyncio
import logging
import os
from datetime import datetime
from dotenv import load_dotenv

import ccxt.async_support as ccxt
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode

load_dotenv()

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTC/USDT"
TIMEFRAME = "5m"
POSITION_SIZE = 2000
LEVERAGE = 20
STOP_LOSS_PCT = 0.7
TAKE_PROFIT_PCT = 3.0
BREAKEVEN_PCT = 0.75
TRAILING_OFFSET_PCT = 0.7
COMMISSION_PCT = 0.055

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ====================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
exchange = None

position = None
trade_history = []
signal_count = 0


# ==================== СТРУКТУРА ПОЗИЦИИ ====================
def create_position(side, entry_price):
    amount = POSITION_SIZE / entry_price
    return {
        "side": side,
        "entry_price": entry_price,
        "amount": amount,
        "stop_loss": entry_price * (1 - STOP_LOSS_PCT / 100) if side == "long" else entry_price * (1 + STOP_LOSS_PCT / 100),
        "take_profit": entry_price * (1 + TAKE_PROFIT_PCT / 100) if side == "long" else entry_price * (1 - TAKE_PROFIT_PCT / 100),
        "trailing_active": False,
        "breakeven_hit": False,
        "highest_price": entry_price if side == "long" else None,
        "lowest_price": entry_price if side == "short" else None,
        "open_time": datetime.now(),
        "position_size_usdt": POSITION_SIZE,
    }


# ==================== КОМИССИЯ И PnL ====================
def calc_commission(usdt_size):
    return usdt_size * COMMISSION_PCT / 100 * 2


def calc_pnl(pos, current_price):
    if pos["side"] == "long":
        pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100
    else:
        pnl_pct = (pos["entry_price"] - current_price) / pos["entry_price"] * 100

    pnl_usdt = pos["position_size_usdt"] * pnl_pct / 100
    commission = calc_commission(pos["position_size_usdt"])
    net_pnl = pnl_usdt - commission

    return pnl_pct, net_pnl, commission


# ==================== ИНДИКАТОРЫ ====================
def ema_series(data, period):
    if len(data) < period:
        return []
    ema = sum(data[:period]) / period
    result = [ema]
    m = 2 / (period + 1)
    for price in data[period:]:
        ema = (price - ema) * m + ema
        result.append(ema)
    return result


def calc_ema(closes, period):
    series = ema_series(closes, period)
    return series[-1] if series else None


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(0, delta))
        losses.append(max(0, -delta))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None, None, None

    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)

    offset = slow - fast
    macd_values = []
    for i in range(len(ema_slow)):
        macd_values.append(ema_fast[i + offset] - ema_slow[i])

    if len(macd_values) < signal:
        return None, None, None

    signal_line = sum(macd_values[:signal]) / signal
    m_sig = 2 / (signal + 1)
    for val in macd_values[signal:]:
        signal_line = (val - signal_line) * m_sig + signal_line

    macd_line = macd_values[-1]
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


# ==================== СИГНАЛЫ ====================
def get_signal(closes, volumes):
    if len(closes) < 50:
        return None

    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    ema50 = calc_ema(closes, 50)
    rsi = calc_rsi(closes)
    macd_line, signal_line, histogram = calc_macd(closes)

    if None in (ema9, ema21, ema50, rsi, macd_line, signal_line):
        return None

    current_price = closes[-1]
    avg_volume = sum(volumes[-20:]) / 20
    current_volume = volumes[-1]

    if (ema9 > ema21 > ema50 and
            current_price > ema9 and
            45 < rsi < 70 and
            macd_line > signal_line and
            current_volume > avg_volume * 0.8):
        return "long"

    if (ema9 < ema21 < ema50 and
            current_price < ema9 and
            30 < rsi < 55 and
            macd_line < signal_line and
            current_volume > avg_volume * 0.8):
        return "short"

    return None


# ==================== ВИРТУАЛЬНОЕ УПРАВЛЕНИЕ ПОЗИЦИЕЙ ====================
async def check_virtual_position(current_price):
    global position

    if position is None:
        return

    pos = position
    pnl_pct, net_pnl, commission = calc_pnl(pos, current_price)

    # Обновляем экстремумы
    if pos["side"] == "long":
        if current_price > (pos.get("highest_price") or 0):
            pos["highest_price"] = current_price
    else:
        if pos.get("lowest_price") is None or current_price < pos["lowest_price"]:
            pos["lowest_price"] = current_price

    # Безубыток и трейлинг
    if not pos["breakeven_hit"] and pnl_pct >= BREAKEVEN_PCT:
        pos["breakeven_hit"] = True
        pos["trailing_active"] = True
        pos["stop_loss"] = pos["entry_price"]
        await send_message(
            f"🔄 <b>[ТЕСТ] Безубыток активирован</b>\n"
            f"Стоп: {pos['stop_loss']:.2f}\n"
            f"Трейлинг включён ({TRAILING_OFFSET_PCT}%)"
        )

    if pos["trailing_active"]:
        if pos["side"] == "long":
            new_stop = pos["highest_price"] * (1 - TRAILING_OFFSET_PCT / 100)
            if new_stop > pos["stop_loss"]:
                pos["stop_loss"] = new_stop
        else:
            new_stop = pos["lowest_price"] * (1 + TRAILING_OFFSET_PCT / 100)
            if new_stop < pos["stop_loss"]:
                pos["stop_loss"] = new_stop

    # Проверяем стоп
    if pos["side"] == "long" and current_price <= pos["stop_loss"]:
        reason = "ТРЕЙЛИНГ-СТОП" if pos["trailing_active"] else "СТОП-ЛОСС"
        await close_virtual_position(current_price, reason)
        return
    if pos["side"] == "short" and current_price >= pos["stop_loss"]:
        reason = "ТРЕЙЛИНГ-СТОП" if pos["trailing_active"] else "СТОП-ЛОСС"
        await close_virtual_position(current_price, reason)
        return

    # Проверяем тейк
    if pos["side"] == "long" and current_price >= pos["take_profit"]:
        await close_virtual_position(current_price, "ТЕЙК-ПРОФИТ")
        return
    if pos["side"] == "short" and current_price <= pos["take_profit"]:
        await close_virtual_position(current_price, "ТЕЙК-ПРОФИТ")
        return


async def open_virtual_position(side, price):
    global position, signal_count

    if position is not None:
        return

    position = create_position(side, price)
    signal_count += 1

    emoji = "🟢" if side == "long" else "🔴"
    commission = calc_commission(POSITION_SIZE)

    await send_message(
        f"{emoji} <b>[ТЕСТ] Виртуальный вход #{signal_count}: {side.upper()}</b>\n"
        f"Цена: {price:.2f}\n"
        f"Размер: {POSITION_SIZE} USDT ({position['amount']:.6f} BTC)\n"
        f"Стоп: {position['stop_loss']:.2f} (-{STOP_LOSS_PCT}%)\n"
        f"Тейк: {position['take_profit']:.2f} (+{TAKE_PROFIT_PCT}%)\n"
        f"Безубыток при: +{BREAKEVEN_PCT}%\n"
        f"Комиссия: ~{commission:.2f}$\n"
        f"⚠️ Сделка НЕ открыта на бирже"
    )


async def close_virtual_position(current_price, reason):
    global position

    if position is None:
        return

    pos = position
    pnl_pct, net_pnl, commission = calc_pnl(pos, current_price)

    duration = datetime.now() - pos["open_time"]
    hours = int(duration.total_seconds() // 3600)
    minutes = int((duration.total_seconds() % 3600) // 60)

    trade_record = {
        "side": pos["side"],
        "entry_price": pos["entry_price"],
        "exit_price": current_price,
        "pnl_pct": pnl_pct,
        "net_pnl": net_pnl,
        "commission": commission,
        "reason": reason,
        "duration": f"{hours}ч {minutes}м",
        "close_time": datetime.now().isoformat(),
        "position_size": pos["position_size_usdt"],
    }
    trade_history.append(trade_record)

    emoji = "✅" if net_pnl >= 0 else "❌"
    await send_message(
        f"{emoji} <b>[ТЕСТ] Виртуальное закрытие — {reason}</b>\n"
        f"{pos['side'].upper()} | {pos['entry_price']:.2f} → {current_price:.2f}\n"
        f"PnL: {net_pnl:+.2f}$ ({pnl_pct:+.2f}%)\n"
        f"Комиссия: {commission:.2f}$\n"
        f"Длительность: {hours}ч {minutes}м\n"
        f"⚠️ Виртуальная сделка"
    )

    position = None


# ==================== ОСНОВНОЙ ЦИКЛ ====================
async def trading_loop():
    global exchange

    exchange = ccxt.bybit({
        "sandbox": False,
        "options": {"defaultType": "swap"},
    })

    await send_message(
        f"🤖 <b>Бот запущен (ТЕСТОВЫЙ РЕЖИМ)</b>\n\n"
        f"Пара: {SYMBOL}\n"
        f"Таймфрейм: {TIMEFRAME}\n"
        f"Виртуальная позиция: {POSITION_SIZE} USDT (x{LEVERAGE})\n"
        f"Стоп: {STOP_LOSS_PCT}% | Тейк: {TAKE_PROFIT_PCT}%\n"
        f"Безубыток: +{BREAKEVEN_PCT}% | Трейлинг: {TRAILING_OFFSET_PCT}%\n\n"
        f"⚠️ Реальные сделки ОТКЛЮЧЕНЫ\n"
        f"Бот только показывает сигналы и считает виртуальный PnL"
    )

    while True:
        try:
            ohlcv = await exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=100)
            closes = [c[4] for c in ohlcv]
            volumes = [c[5] for c in ohlcv]
            current_price = closes[-1]

            # Проверяем виртуальную позицию
            await check_virtual_position(current_price)

            # Ищем сигнал
            if position is None:
                signal = get_signal(closes, volumes)
                if signal:
                    await open_virtual_position(signal, current_price)
            else:
                signal = get_signal(closes, volumes)
                if signal and signal != position["side"]:
                    await close_virtual_position(current_price, "СИГНАЛ РАЗВОРОТА")
                    await open_virtual_position(signal, current_price)

            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f"Loop error: {e}")
            await asyncio.sleep(60)


# ==================== TELEGRAM ====================
async def send_message(text):
    try:
        await bot.send_message(CHAT_ID, text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Telegram send error: {e}")


def calc_total_stats(trades):
    if not trades:
        return ""
    total_pnl = sum(t["net_pnl"] for t in trades)
    total_pct = sum(t["pnl_pct"] for t in trades)
    wins = sum(1 for t in trades if t["net_pnl"] > 0)
    losses = sum(1 for t in trades if t["net_pnl"] <= 0)
    winrate = (wins / len(trades) * 100) if trades else 0
    emoji = "📈" if total_pnl >= 0 else "📉"

    return (
        f"\n{emoji} <b>Виртуальная статистика:</b>\n"
        f"Всего сделок: {len(trades)}\n"
        f"Побед: {wins} | Поражений: {losses}\n"
        f"Winrate: {winrate:.1f}%\n"
        f"Общий PnL: {total_pnl:+.2f}$ ({total_pct:+.2f}%)"
    )


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🤖 <b>Торговый бот BTC/USDT (ТЕСТ)</b>\n\n"
        "/status — текущая виртуальная позиция\n"
        "/history — история виртуальных сделок\n"
        "/stats — статистика\n"
        "/price — текущая цена BTC",
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    pos = position
    if pos is None:
        await message.answer("📭 Нет виртуальных позиций. Ищу сигнал...")
        return

    try:
        ohlcv = await exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=1)
        current_price = ohlcv[-1][4]
        pnl_pct, net_pnl, commission = calc_pnl(pos, current_price)

        emoji = "🟢" if pos["side"] == "long" else "🔴"
        pnl_emoji = "✅" if net_pnl >= 0 else "❌"

        duration = datetime.now() - pos["open_time"]
        hours = int(duration.total_seconds() // 3600)
        minutes = int((duration.total_seconds() % 3600) // 60)

        await message.answer(
            f"{emoji} <b>[ТЕСТ] {pos['side'].upper()}</b>\n"
            f"Вход: {pos['entry_price']:.2f}\n"
            f"Текущая: {current_price:.2f}\n"
            f"Стоп: {pos['stop_loss']:.2f}\n"
            f"Тейк: {pos['take_profit']:.2f}\n"
            f"Безубыток: {'✅' if pos['breakeven_hit'] else '❌'}\n"
            f"Трейлинг: {'✅' if pos['trailing_active'] else '❌'}\n"
            f"{pnl_emoji} PnL: {net_pnl:+.2f}$ ({pnl_pct:+.2f}%)\n"
            f"Длительность: {hours}ч {minutes}м",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    if not trade_history:
        await message.answer("📭 История виртуальных сделок пуста.")
        return

    last_trades = trade_history[-10:]
    text = "<b>📋 Виртуальные сделки:</b>\n\n"

    for i, t in enumerate(last_trades, 1):
        emoji = "✅" if t["net_pnl"] >= 0 else "❌"
        side_emoji = "🟢" if t["side"] == "long" else "🔴"
        text += (
            f"{i}. {side_emoji}{emoji} {t['side'].upper()} | "
            f"{t['entry_price']:.2f} → {t['exit_price']:.2f}\n"
            f"   PnL: {t['net_pnl']:+.2f}$ ({t['pnl_pct']:+.2f}%) | "
            f"{t['reason']} | {t['duration']}\n\n"
        )

    text += calc_total_stats(trade_history)
    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if not trade_history:
        await message.answer("📭 Нет данных для статистики.")
        return

    total_pnl = sum(t["net_pnl"] for t in trade_history)
    total_commission = sum(t["commission"] for t in trade_history)
    wins = [t for t in trade_history if t["net_pnl"] > 0]
    losses = [t for t in trade_history if t["net_pnl"] <= 0]
    winrate = len(wins) / len(trade_history) * 100

    avg_win = sum(t["net_pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["net_pnl"] for t in losses) / len(losses) if losses else 0
    best = max(trade_history, key=lambda t: t["net_pnl"])
    worst = min(trade_history, key=lambda t: t["net_pnl"])

    reasons = {}
    for t in trade_history:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    reasons_text = "\n".join(f"  {k}: {v}" for k, v in reasons.items())

    emoji = "📈" if total_pnl >= 0 else "📉"

    await message.answer(
        f"{emoji} <b>Виртуальная статистика</b>\n\n"
        f"Всего сделок: {len(trade_history)}\n"
        f"Побед: {len(wins)} | Поражений: {len(losses)}\n"
        f"Winrate: {winrate:.1f}%\n\n"
        f"Общий PnL: {total_pnl:+.2f}$\n"
        f"Комиссии: {total_commission:.2f}$\n"
        f"Средняя победа: {avg_win:+.2f}$\n"
        f"Средний убыток: {avg_loss:+.2f}$\n\n"
        f"Лучшая: {best['net_pnl']:+.2f}$ ({best['side'].upper()})\n"
        f"Худшая: {worst['net_pnl']:+.2f}$ ({worst['side'].upper()})\n\n"
        f"<b>Причины закрытия:</b>\n{reasons_text}",
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("price"))
async def cmd_price(message: types.Message):
    try:
        ohlcv = await exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=100)
        closes = [c[4] for c in ohlcv]
        volumes = [c[5] for c in ohlcv]
        current_price = closes[-1]

        ema9 = calc_ema(closes, 9)
        ema21 = calc_ema(closes, 21)
        ema50 = calc_ema(closes, 50)
        rsi = calc_rsi(closes)
        macd_line, signal_line, histogram = calc_macd(closes)

        signal = get_signal(closes, volumes)
        signal_text = "🟢 LONG" if signal == "long" else "🔴 SHORT" if signal == "short" else "⚪ Нет сигнала"

        await message.answer(
            f"📊 <b>BTC/USDT</b>\n\n"
            f"Цена: {current_price:.2f}\n"
            f"EMA9: {ema9:.2f}\n"
            f"EMA21: {ema21:.2f}\n"
            f"EMA50: {ema50:.2f}\n"
            f"RSI: {rsi:.1f}\n"
            f"MACD: {macd_line:.2f}\n"
            f"Signal: {signal_line:.2f}\n"
            f"Histogram: {histogram:.2f}\n\n"
            f"Сигнал: {signal_text}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


# ==================== ЗАПУСК ====================
async def main():
    try:
        asyncio.create_task(trading_loop())
        await dp.start_polling(bot)
    finally:
        if exchange:
            await exchange.close()


if __name__ == "__main__":
    asyncio.run(main())
