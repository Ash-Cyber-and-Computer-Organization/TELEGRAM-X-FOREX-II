import telebot
import smtplib
import random
import string
import MetaTrader5 as mt5
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from threading import Thread
from datetime import datetime
import time
import os
import json

# Telegram + Email Config
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
bot = telebot.TeleBot("7597638064:AAEm828isgdGJB2atT3O5h774B_s8iN0y64")
OWNER_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"  # replace this with your real Telegram ID
EMAIL_ADDRESS = 'forexbot247@gmail.com'
EMAIL_PASSWORD = 'naqcnmmpmjabkwzy'
RECIPIENT_EMAIL = 'jackboiz4lyf@gmail.com'
PASSWORD_EXPIRY = 24 * 60 * 60

daily_password = None

# Growth plan configurations
GROWTH_PLANS = {
    "30-day": {"starting_balance": 10.0, "target_multiplier": 1.27},
    "6-month": {"starting_balance": 1.0, "target_multiplier": 1.06}
}

# Client Bot Registry
CLIENTS = [
    {
        "login": 89647215,
        "password": "R@lq8kAP",
        "server": "MetaQuotes-Demo",
        "name": "Main Account",
        "telegram_id": "YOUR_TELEGRAM_CHAT_ID",
        "plan": "30-day"
    },
    {
        "login": 89647216,
        "password": "examplePass",
        "server": "MetaQuotes-Demo",
        "name": "LongTerm Client",
        "telegram_id": "YOUR_TELEGRAM_CHAT_ID",
        "plan": "6-month"
    }
    # Add more clients and assign them a plan from GROWTH_PLANS
]

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

def generate_password(length=8):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def update_password():
    global daily_password
    while True:
        daily_password = generate_password()
        send_password_email(daily_password)
        time.sleep(PASSWORD_EXPIRY)

def log_daily_equity():
    for client in CLIENTS:
        plan_info = GROWTH_PLANS[client["plan"]]
        mt5.initialize(login=client["login"], password=client["password"], server=client["server"])
        account_info = mt5.account_info()
        equity = account_info.equity if account_info else 0
        date_key = datetime.now().strftime("%Y-%m-%d")
        log_file = f"tracker_{client['login']}.json"

        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                log = json.load(f)
        else:
            log = {}

        log[date_key] = equity

        with open(log_file, 'w') as f:
            json.dump(log, f, indent=4)

        days_passed = len(log)
        target_equity = round(plan_info["starting_balance"] * (plan_info["target_multiplier"] ** days_passed), 2)
        send_daily_update(client["telegram_id"], client["name"], client["login"], equity, target_equity, days_passed, client["plan"])
        mt5.shutdown()

def send_daily_update(telegram_id, name, login, balance, target, day, plan):
    status = '✅ On Track' if balance >= target else '⚠️ Below Target'
    message = (
        f"🌅 Good Morning {name}\n"
        f"👤 Account: {login}\n"
        f"📋 Plan: {plan}\n"
        f"📊 Day {day}\n"
        f"💰 Balance: ${balance:.2f}\n"
        f"🎯 Target: ${target:.2f}\n"
        f"📈 Status: {status}"
    )
    bot.send_message(telegram_id, message)

def schedule_daily_update():
    while True:
        now = datetime.now()
        if now.hour == 7 and now.minute == 0:
            log_daily_equity()
            time.sleep(60)
        time.sleep(30)

def check_drawdown_and_close():
    for client in CLIENTS:
        plan_info = GROWTH_PLANS[client["plan"]]
        mt5.initialize(login=client["login"], password=client["password"], server=client["server"])
        account_info = mt5.account_info()
        if account_info:
            current_equity = account_info.equity
            threshold = plan_info["starting_balance"] * 0.10
            if current_equity < threshold:
                positions = mt5.positions_get()
                if positions:
                    for pos in positions:
                        if pos.profit < 0:
                            close_trade(pos)
                    bot.send_message(client["telegram_id"], "🚨 Equity dropped below 10%. Losing trades were closed automatically.")
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
    Thread(target=schedule_daily_update, daemon=True).start()
    Thread(target=check_drawdown_and_close, daemon=True).start()
    bot.polling()
