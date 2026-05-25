#!/usr/bin/env python3
"""
Авто-торговля через ccxt для BingX: покупка BTC на фикс. сумму USDT,
лимитный ордер на продажу на X% дороже, бесконечный цикл с паузой 5 мин.
Режим sandbox (testnet) по умолчанию.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import ccxt

# Файлы для веб-интерфейса (статус и лог)
_SCRIPT_DIR = Path(__file__).resolve().parent
STATUS_FILE = _SCRIPT_DIR / "trade_status.json"
LOG_FILE = _SCRIPT_DIR / "trade_log.txt"

# Загрузка из .env при наличии (опционально)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============== Переменные (легко менять; можно задать в .env) ==============
API_KEY = os.getenv("API_KEY", "your_api_key_here")
API_SECRET = os.getenv("API_SECRET", "your_api_secret_here")
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "bingx")
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
AMOUNT_USDT = float(os.getenv("AMOUNT_USDT", "50"))
X = float(os.getenv("X", "0.5"))
WAIT_AFTER_SELL_SEC = int(os.getenv("WAIT_AFTER_SELL_SEC", "300"))
USE_SANDBOX = os.getenv("USE_SANDBOX", "true").lower() in ("1", "true", "yes")
CHECK_ORDER_INTERVAL_SEC = int(os.getenv("CHECK_ORDER_INTERVAL_SEC", "15"))
# =======================================================


def _write_status(buy_price=None, target_price=None, status="", order_id=None):
    data = {"updated_at": datetime.now().isoformat(), "status": status}
    if buy_price is not None:
        data["buy_price"] = buy_price
    if target_price is not None:
        data["target_price"] = target_price
    if order_id is not None:
        data["order_id"] = order_id
    try:
        prev = {}
        if STATUS_FILE.exists():
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                prev = json.load(f)
        prev.update(data)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(prev, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_exchange():
    opts = {
        "apiKey": API_KEY,
        "secret": API_SECRET,
        "enableRateLimit": True,
        "options": {},
    }
    # BingX: spot-торговля; testnet при USE_SANDBOX=True
    if EXCHANGE_ID == "bingx":
        opts["options"]["defaultType"] = "spot"
    elif EXCHANGE_ID == "binance":
        opts["options"]["defaultType"] = "spot"
    opts["sandbox"] = USE_SANDBOX
    return getattr(ccxt, EXCHANGE_ID)(opts)


def buy_market(exchange, symbol: str, amount_quote: float) -> tuple[float, float]:
    """Покупка на сумму в котировочной валюте. Возвращает (средняя цена, объём в базовой валюте)."""
    market = exchange.market(symbol)
    if market.get("quoteOrderQtyMarketAllowed"):
        order = exchange.create_order(
            symbol, "market", "buy", None, None, {"quoteOrderQty": amount_quote}
        )
    else:
        price = float(exchange.fetch_ticker(symbol).get("last") or 0)
        amount_base = amount_quote / price
        amount_base = exchange.amount_to_precision(symbol, amount_base)
        if isinstance(amount_base, str):
            amount_base = float(amount_base)
        order = exchange.create_order(symbol, "market", "buy", amount_base, None, {})
    filled = float(order.get("filled") or 0)
    cost = float(order.get("cost") or (float(order.get("average") or 0) * filled)
    avg_price = cost / filled if filled else 0
    return avg_price, filled


def place_limit_sell(exchange, symbol: str, amount: float, price: float):
    """Выставить лимитный ордер на продажу. Возвращает ордер."""
    amount = exchange.amount_to_precision(symbol, amount)
    if isinstance(amount, str):
        amount = float(amount)
    price = exchange.price_to_precision(symbol, price)
    if isinstance(price, str):
        price = float(price)
    return exchange.create_order(symbol, "limit", "sell", amount, price, {})


def run_cycle(exchange):
    symbol = SYMBOL
    amount_quote = AMOUNT_USDT
    target_percent = X
    log(f"Статус: начинаем цикл. Пара {symbol}, сумма {amount_quote} USDT, целевой +{target_percent}%")
    _write_status(status="Начало цикла")

    # 1. Рыночная покупка
    log("Статус: рыночная покупка...")
    _write_status(status="Рыночная покупка...")
    buy_price, amount_bought = buy_market(exchange, symbol, amount_quote)
    if amount_bought <= 0:
        log("Ошибка: объём покупки 0. Пропускаем цикл.")
        _write_status(status="Ошибка: объём покупки 0")
        return

    target_price = buy_price * (1 + target_percent / 100)
    _write_status(buy_price=buy_price, target_price=target_price, status="Куплено, выставляю лимитный ордер")
    log(f"Цена покупки: {buy_price:.4f}")
    log(f"Целевая цена продажи: {target_price:.4f} (+{target_percent}%)")

    # 2. Лимитный ордер на продажу
    order = place_limit_sell(exchange, symbol, amount_bought, target_price)
    order_id = order.get("id")
    _write_status(buy_price=buy_price, target_price=target_price, order_id=str(order_id), status="Ожидание исполнения лимитного ордера")
    log(f"Статус: выставлен лимитный ордер на продажу, id={order_id}, цена={target_price:.4f}")

    # 3. Ждём исполнения ордера
    while True:
        time.sleep(CHECK_ORDER_INTERVAL_SEC)
        o = exchange.fetch_order(order_id, symbol)
        status = o.get("status")
        _write_status(buy_price=buy_price, target_price=target_price, order_id=str(order_id), status=f"Ордер: {status}")
        log(f"Статус ордера: {status}")

        if status == "closed" or status == "filled":
            log("Продажа совершена. Выход из цикла.")
            _write_status(buy_price=buy_price, target_price=target_price, status="Продажа совершена")
            break
        if status == "canceled":
            log("Ордер отменён. Выход из цикла.")
            _write_status(buy_price=buy_price, target_price=target_price, status="Ордер отменён")
            break


def main():
    _write_status(status="Подключение к бирже...")
    log("Подключение к бирже (sandbox/testnet)...")
    exchange = get_exchange()
    exchange.load_markets()

    log(f"Биржа: {EXCHANGE_ID}, пара: {SYMBOL}, сумма: {AMOUNT_USDT} USDT, целевой %: {X}%")
    log(f"Пауза после продажи: {WAIT_AFTER_SELL_SEC} сек ({WAIT_AFTER_SELL_SEC // 60} мин)")

    while True:
        try:
            run_cycle(exchange)
        except Exception as e:
            log(f"Ошибка в цикле: {e}")
        log(f"Ожидание {WAIT_AFTER_SELL_SEC} сек перед следующей покупкой...")
        _write_status(status="Пауза перед следующей покупкой")
        time.sleep(WAIT_AFTER_SELL_SEC)


if __name__ == "__main__":
    main()
