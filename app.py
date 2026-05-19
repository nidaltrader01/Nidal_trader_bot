from flask import Flask, request
import requests
import os

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
@app.route("/")
def home():
    return "Nidal Trader Bot is running"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "TradingView alert received")
if message == "price":
    finnhub_url = f"https://finnhub.io/api/v1/quote?symbol=NVDA&token={FINNHUB_API_KEY}"

    response = requests.get(finnhub_url)
    stock_data = response.json()

    current_price = stock_data.get("c", "N/A")

    message = f"NVDA current price: {current_price}"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

    requests.post(url, json=payload)

    return {"status": "sent"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
