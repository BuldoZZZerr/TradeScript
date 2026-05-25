#!/usr/bin/env python3
"""
Скрипт: покупает криптовалюту, ждёт роста курса и продаёт в плюс.
Использует API биржи (по умолчанию Binance) через ccxt.
"""

import os
import time
import ccxt
from dotenv import load_dotenv

load_dotenv()

# --- Настройки (можно задать в .env) ---
EXCHANGE_ID = os.getenv("EXCHANGE", "binance")
API_KEY = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
AMOUNT_QUOTE = float(os.getenv("AMOUNT_QUOTE", "50"))  # Сколько потратить в USDT
PROFIT_PERCENT = float(os.getenv("PROFIT_PERCENT", "0.5"))  # Цель по прибыли в %
STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "0"))  # 0 = отключен
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "30"))
SANDBOX = os.getenv("SANDBOX", "false").lower() in ("1", "true", "yes")


def get_exchange():
    if not API_KEY or not API_SECRET:
        raise SystemExit(
            "Задайте API_KEY и API_SECRET в .env или переменных окружения."
        )
    opts = {
        "apiKey": API_KEY,
        "secret": API_SECRET,
        "enableRateLimit": True,
        "options": {},
    }
    if EXCHANGE_ID == "binance":
        opts["options"]["defaultType"] = "spot"
    if SANDBOX:
        opts["sandbox"] = True
    return getattr(ccxt, EXCHANGE_ID)(opts)


def round_amount(exchange, symbol: str, amount: float, is_cost: bool = False):
    """Округляет объём/сумму по правилам биржи."""
    market = exchange.market(symbol)
    if is_cost:
        precision = market.get("precision", {}).get("cost") or market.get("precision", {}).get("price")
        if precision is not None:
            return round(amount, precision)
        return amount
    precision = market.get("precision", {}).get("amount")
    if precision is not None:
        return exchange.amount_to_precision(symbol, amount)
    return amount


def buy(exchange, symbol: str, amount_quote: float) -> tuple[float, float]:
    """Покупка на указанную сумму в котировочной валюте. Возвращает (средняя цена, объём в базовой валюте)."""
    amount_quote = round_amount(exchange, symbol, amount_quote, is_cost=True)
    market = exchange.market(symbol)
    if market.get("quoteOrderQtyMarketAllowed"):
        order = exchange.create_order(
            symbol, "market", "buy", None, None, {"quoteOrderQty": amount_quote}
        )
    else:
        price = fetch_last_price(exchange, symbol)
        amount_base = amount_quote / price
        amount_base = round_amount(exchange, symbol, amount_base, is_cost=False)
        if isinstance(amount_base, str):
            amount_base = float(amount_base)
        order = exchange.create_order(symbol, "market", "buy", amount_base, None, {})
    filled = float(order.get("filled") or 0)
    cost = float(order.get("cost") or (float(order.get("average") or 0) * filled))
    avg_price = cost / filled if filled else 0
    print(f"  Куплено: {filled} по ~{avg_price:.6g}, сумма {cost:.4f}")
    return avg_price, filled


def sell(exchange, symbol: str, amount: float) -> float:
    """Продажа указанного объёма по рыночной цене. Возвращает полученную сумму в котировочной валюте."""
    amount = round_amount(exchange, symbol, amount, is_cost=False)
    if isinstance(amount, str):
        amount = float(amount)
    order = exchange.create_market_sell_order(symbol, amount)
    cost = order.get("cost") or 0
    print(f"  Продано: {amount} на сумму {cost:.4f}")
    return float(cost)


def fetch_last_price(exchange, symbol: str) -> float:
    ticker = exchange.fetch_ticker(symbol)
    return float(ticker.get("last") or ticker.get("close") or 0)


def run():
    print("Подключение к бирже...")
    exchange = get_exchange()
    exchange.load_markets()


    print(f"Пара: {SYMBOL}, сумма: {AMOUNT_QUOTE}, цель прибыли: +{PROFIT_PERCENT}%")
    if STOP_LOSS_PERCENT > 0:
        print(f"Стоп-лосс: -{STOP_LOSS_PERCENT}%")

    # 1. Покупка
    print("\n--- Покупка ---")
    buy_price, amount_bought = buy(exchange, SYMBOL, AMOUNT_QUOTE)
    if amount_bought <= 0:
        raise SystemExit("Не удалось купить (объём 0).")

    target_price = buy_price * (1 + PROFIT_PERCENT / 100)
    stop_price = buy_price * (1 - STOP_LOSS_PERCENT / 100) if STOP_LOSS_PERCENT else None

    # 2. Ожидание роста и продажа
    print("\n--- Ожидание целевой цены (или стоп-лосса) ---")
    while True:
        last = fetch_last_price(exchange, SYMBOL)
        pnl_pct = (last - buy_price) / buy_price * 100
        print(f"  Цена: {last:.4f}  (покупка: {buy_price:.4f}, PnL: {pnl_pct:+.2f}%)")

        if last >= target_price:
            print("\n--- Цель прибыли достигнута, продаём ---")
            sell(exchange, SYMBOL, amount_bought)
            print("Готово. Выход в плюс.")
            break
        if stop_price is not None and last <= stop_price:
            print("\n--- Сработал стоп-лосс, продаём ---")
            sell(exchange, SYMBOL, amount_bought)
            print("Продано по стоп-лоссу.")
            break

        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    run()