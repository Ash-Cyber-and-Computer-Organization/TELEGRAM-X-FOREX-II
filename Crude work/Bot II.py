import telebot
import smtplib
import random
import string
import MetaTrader5 as mt5
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from threading import Thread
import time
import os
import json
import re

# MetaTrader 5 Connection Settings
MT5_LOGIN = os.getenv('89647215')
MT5_PASSWORD = os.getenv('R@lq8kAP')
MT5_SERVER = os.getenv('MetaQuotes-Demo')

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
bot = telebot.TeleBot("7597638064:AAEm828isgdGJB2atT3O5h774B_s8iN0y64")
EMAIL_ADDRESS = 'forexbot247@gmail.com'
EMAIL_PASSWORD = 'naqcnmmpmjabkwzy'
RECIPIENT_EMAIL = 'jackboiz4lyf@gmail.com'
PASSWORD_EXPIRY = 24 * 60 * 60

DAILY_TRACK_FILE = "tracker.json"
daily_password = None
authorized_users = set()
STARTING_BALANCE = 10.0  # Initial account balance for tracking
TARGET_MULTIPLIER = 1.27


def generate_password(length=8):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def send_password_email(password):
    subject = "Daily Bot Password"
    body = f"Your password for accessing the bot is: {password}"
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
    except Exception as e:
        print(f"Failed to send email: {e}")

def update_password():
    global daily_password
    while True:
        daily_password = generate_password()
        send_password_email(daily_password)
        time.sleep(PASSWORD_EXPIRY)

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Welcome! Please enter the password to access the bot.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    global authorized_users
    if message.chat.id in authorized_users:
        process_signal(message.text, message.chat.id)
    else:
        if message.text == daily_password:
            authorized_users.add(message.chat.id)
            bot.send_message(message.chat.id, "Access granted!")
        else:
            bot.send_message(message.chat.id, "Incorrect password. Access denied.")

def parse_signal(signal):
    try:
        action_match = re.search(r'\\b(BUY|SELL)\\b', signal, re.IGNORECASE)
        symbol_match = re.search(r'[A-Z]{6}', signal)
        sl_match = re.search(r'(SL[:= ]?)(\\d+\\.\\d+)', signal, re.IGNORECASE)
        tp_match = re.search(r'(TP[:= ]?)(\\d+\\.\\d+)', signal, re.IGNORECASE)
        action = action_match.group(0).upper() if action_match else None
        symbol = symbol_match.group(0).upper() if symbol_match else None
        sl = float(sl_match.group(2)) if sl_match else None
        tp = float(tp_match.group(2)) if tp_match else None
        if None in [action, symbol, sl, tp]:
            raise ValueError("Could not parse all signal components.")
        return action, symbol, sl, tp
    except Exception as e:
        print(f"Parsing error: {e}")
        return None, None, None, None

def calculate_lot_size(account_equity, sl_pips, pip_value=10):
    risk_amount = account_equity * 0.10
    lot_size = risk_amount / (sl_pips * pip_value)
    return round(min(lot_size, 1.0), 2)

def process_signal(signal, chat_id):
    action, symbol, sl, tp = parse_signal(signal)
    if all([action, symbol, sl, tp]):
        place_trade(action, symbol, sl, tp, chat_id)

def place_trade(action, symbol, sl, tp, chat_id):
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return
    account_info = mt5.account_info()
    equity = account_info.equity if account_info else STARTING_BALANCE
    sl_pips = abs(tp - sl) / 0.0001
    volume = calculate_lot_size(equity, sl_pips)

    order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
    price = mt5.symbol_info_tick(symbol).ask if order_type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": 234000,
        "comment": "Telegram Bot Trade",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)

    update_equity_log(chat_id)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        bot.send_message(chat_id, f"❌ Trade failed. Retcode: {result.retcode}")
    else:
        bot.send_message(chat_id, f"✅ Trade placed successfully. Volume: {volume:.2f}")
    mt5.shutdown()

def update_equity_log(chat_id):
    if not mt5.initialize():
        return
    account_info = mt5.account_info()
    equity = account_info.equity if account_info else 0
    day = time.strftime("%Y-%m-%d")

    if os.path.exists(DAILY_TRACK_FILE):
        with open(DAILY_TRACK_FILE, "r") as f:
            data = json.load(f)
    else:
        data = {}

    data[day] = equity
    with open(DAILY_TRACK_FILE, "w") as f:
        json.dump(data, f, indent=4)

    days_passed = len(data)
    target = STARTING_BALANCE * (TARGET_MULTIPLIER ** days_passed)
    bot.send_message(chat_id, f"📊 Day {days_passed}: Balance = ${equity:.2f} / Target = ${target:.2f}")
    mt5.shutdown()

def monitor_drawdown():
    if not mt5.initialize():
        return
    account_info = mt5.account_info()
    equity = account_info.equity
    if equity and equity < STARTING_BALANCE * 0.10:
        positions = mt5.positions_get()
        for pos in positions:
            if pos.profit < 0:
                close_trade(pos)
    mt5.shutdown()

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
        "comment": "Auto-close due to drawdown",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    print(f"Closed trade {position.ticket} with result: {result}")

if __name__ == "__main__":
    Thread(target=update_password, daemon=True).start()
    Thread(target=monitor_drawdown, daemon=True).start()
    bot.polling()
