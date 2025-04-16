from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import json
import os
import re
import MetaTrader5 as mt5
import telebot
import threading

app = FastAPI()

# Telegram Bot Integration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or "7597638064:AAEm828isgdGJB2atT3O5h774B_s8iN0y64"
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

ADMIN_IDS = ["YOUR_ADMIN_TELEGRAM_ID"]  # Replace with actual Telegram chat IDs

# Dummy client registry
CLIENTS = [
    {"login": 89647215, "name": "Main Account", "plan": "30-day", "password": "R@lq8kAP", "server": "MetaQuotes-Demo", "telegram_id": "YOUR_TELEGRAM_CHAT_ID"},
    {"login": 89647216, "name": "LongTerm Client", "plan": "6-month", "password": "examplePass", "server": "MetaQuotes-Demo", "telegram_id": "YOUR_TELEGRAM_CHAT_ID"},
]

GROWTH_PLANS = {
    "30-day": {"starting_balance": 10.0, "target_multiplier": 1.27},
    "6-month": {"starting_balance": 1.0, "target_multiplier": 1.06}
}

DEFAULT_LOT_SIZE = 0.01

def close_trade(position):
    price = mt5.symbol_info_tick(position.symbol).bid if position.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(position.symbol).ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "position": position.ticket,
        "price": price,
        "deviation": 10,
        "magic": 234000,
        "comment": "Closed via API",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    return mt5.order_send(request)

class SignalRequest(BaseModel):
    raw_signal: str
    login: int

@app.post("/parse-signal")
def parse_signal(signal: SignalRequest):
    return handle_signal(signal.raw_signal, signal.login)

def handle_signal(raw: str, login: int):
    result = {
        "symbol": None,
        "action": None,
        "volume": DEFAULT_LOT_SIZE,
        "sl": None,
        "tp": None
    }
    try:
        symbol_match = re.search(r"[A-Z]{6,7}", raw)
        action_match = re.search(r"\b(BUY|SELL)\b", raw, re.IGNORECASE)
        sl_match = re.search(r"SL[:\-]?\s*(\d+(\.\d+)?)", raw, re.IGNORECASE)
        tp_match = re.search(r"TP[:\-]?\s*(\d+(\.\d+)?)", raw, re.IGNORECASE)
        lot_match = re.search(r"Lot[:\-]?\s*(\d+(\.\d+)?)", raw, re.IGNORECASE)

        if symbol_match:
            result["symbol"] = symbol_match.group(0).upper()
        if action_match:
            result["action"] = action_match.group(0).upper()
        if sl_match:
            result["sl"] = float(sl_match.group(1))
        if tp_match:
            result["tp"] = float(tp_match.group(1))
        if lot_match:
            result["volume"] = float(lot_match.group(1))

        if not result["sl"] or not result["tp"]:
            numbers = list(map(float, re.findall(r"\d+\.\d+", raw)))
            if len(numbers) >= 2:
                result["sl"] = result["sl"] or numbers[0]
                result["tp"] = result["tp"] or numbers[1]

        if None in (result["symbol"], result["action"], result["sl"], result["tp"]):
            return {"error": "Could not parse full signal. Provide symbol, action, SL, and TP."}

        client = next((c for c in CLIENTS if c["login"] == login), None)
        if not client:
            return {"error": "Client not found."}

        mt5.initialize(login=client["login"], password=client["password"], server=client["server"])
        tick = mt5.symbol_info_tick(result["symbol"])
        order_type = mt5.ORDER_TYPE_BUY if result["action"] == "BUY" else mt5.ORDER_TYPE_SELL
        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": result["symbol"],
            "volume": result["volume"],
            "type": order_type,
            "price": price,
            "sl": result["sl"],
            "tp": result["tp"],
            "deviation": 10,
            "magic": 234000,
            "comment": "Signal Auto-Trade",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result_exec = mt5.order_send(request)
        mt5.shutdown()

        return {"parsed": result, "order_result": {"retcode": result_exec.retcode, "comment": result_exec.comment}}
    except Exception as e:
        return {"error": f"Parsing failed: {str(e)}"}

@bot.message_handler(func=lambda message: True)
def receive_signal(message):
    telegram_id = str(message.chat.id)

    if telegram_id in ADMIN_IDS:
        if message.text.strip().lower() == "/forceclose":
            closed_positions = []
            for client in CLIENTS:
                mt5.initialize(login=client["login"], password=client["password"], server=client["server"])
                positions = mt5.positions_get()
                if positions:
                    for pos in positions:
                        result = close_trade(pos)
                        closed_positions.append({"ticket": pos.ticket, "retcode": result.retcode})
                mt5.shutdown()
            bot.reply_to(message, f"🔒 Admin override: closed {len(closed_positions)} open trades.")
            return

    client = next((c for c in CLIENTS if c.get("telegram_id") == telegram_id), None)
    if client:
        result = handle_signal(message.text, client["login"])
        feedback = result.get("order_result", {}).get("comment", "Signal received.")
        bot.reply_to(message, f"🚀 Signal executed: {feedback}")
    else:
        bot.reply_to(message, "❌ Unauthorized or unlinked Telegram account.")

threading.Thread(target=bot.polling, daemon=True).start()
