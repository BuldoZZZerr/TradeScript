#!/usr/bin/env python3
"""Веб-интерфейс для торгового скрипта trade_loop.py (BingX)."""

import json
import os
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")
ROOT = Path(__file__).resolve().parent
STATUS_FILE = ROOT / "trade_status.json"
LOG_FILE = ROOT / "trade_log.txt"
ENV_FILE = ROOT / ".env"
SCRIPT = ROOT / "trade_loop.py"

# Глобальная ссылка на процесс скрипта
_process = None


def _read_status():
    if not STATUS_FILE.exists():
        return {"status": "Нет данных", "updated_at": None}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"status": "Ошибка чтения", "updated_at": None}


def _read_logs(tail_lines=200):
    if not LOG_FILE.exists():
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return lines[-tail_lines:] if len(lines) > tail_lines else lines
    except Exception:
        return []


def _read_env():
    """Читает .env в словарь (для отображения в форме)."""
    out = {}
    if not ENV_FILE.exists():
        return out
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    out[k.strip()] = v.strip()
    except Exception:
        pass
    return out


def _write_env(data: dict):
    """Пишет конфиг в .env (переменные для trade_loop + dotenv)."""
    def s(v, default=""):
        return str(v).strip() if v is not None else default
    lines = [
        "# Настройки торгового скрипта (можно менять через веб-интерфейс)",
        f"API_KEY={s(data.get('API_KEY'))}",
        f"API_SECRET={s(data.get('API_SECRET'))}",
        f"EXCHANGE_ID={s(data.get('EXCHANGE_ID'), 'bingx')}",
        f"SYMBOL={s(data.get('SYMBOL'), 'BTC/USDT')}",
        f"AMOUNT_USDT={s(data.get('AMOUNT_USDT'), '50')}",
        f"X={s(data.get('X'), '0.5')}",
        f"WAIT_AFTER_SELL_SEC={s(data.get('WAIT_AFTER_SELL_SEC'), '300')}",
        f"USE_SANDBOX={s(data.get('USE_SANDBOX'), 'true')}",
    ]
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    for k, v in data.items():
        if v is not None and str(v).strip():
            os.environ[k] = str(v).strip()


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/status")
def api_status():
    return jsonify(_read_status())


@app.route("/api/logs")
def api_logs():
    n = request.args.get("lines", 200, type=int)
    return jsonify({"lines": _read_logs(min(n, 500))})


@app.route("/api/config", methods=["GET"])
def api_config_get():
    env = _read_env()
    # Подставляем ключи из .env для формы; если нет — из текущего окружения
    config = {
        "API_KEY": env.get("API_KEY", os.getenv("API_KEY", "")),
        "API_SECRET": env.get("API_SECRET", os.getenv("API_SECRET", "")),
        "EXCHANGE_ID": env.get("EXCHANGE_ID", os.getenv("EXCHANGE_ID", "bingx")),
        "SYMBOL": env.get("SYMBOL", os.getenv("SYMBOL", "BTC/USDT")),
        "AMOUNT_USDT": env.get("AMOUNT_USDT", os.getenv("AMOUNT_USDT", "50")),
        "X": env.get("X", os.getenv("X", "0.5")),
        "WAIT_AFTER_SELL_SEC": env.get("WAIT_AFTER_SELL_SEC", os.getenv("WAIT_AFTER_SELL_SEC", "300")),
        "USE_SANDBOX": env.get("USE_SANDBOX", os.getenv("USE_SANDBOX", "true")),
    }
    return jsonify(config)


@app.route("/api/config", methods=["POST"])
def api_config_post():
    data = request.get_json() or {}
    _write_env(data)
    return jsonify({"ok": True})


@app.route("/api/running")
def api_running():
    global _process
    running = _process is not None and _process.poll() is None
    return jsonify({"running": running})


@app.route("/api/start", methods=["POST"])
def api_start():
    global _process
    if _process is not None and _process.poll() is None:
        return jsonify({"ok": False, "error": "Скрипт уже запущен"}), 400
    # Убедиться, что .env загружен в окружение для дочернего процесса
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE)
    except ImportError:
        pass
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        _process = subprocess.Popen(
            [sys.executable, str(SCRIPT)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    global _process
    if _process is None:
        return jsonify({"ok": True})
    try:
        _process.terminate()
        _process.wait(timeout=10)
    except Exception:
        try:
            _process.kill()
        except Exception:
            pass
    _process = None
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
