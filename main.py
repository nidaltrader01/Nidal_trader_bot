from flask import Flask, request
import requests
import os
from datetime import datetime, timedelta

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text
    }
    requests.post(url, json=payload)


def get_quote(symbol="NVDA"):
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
    r = requests.get(url, timeout=10)
    data = r.json()

    current = data.get("c", "N/A")
    high = data.get("h", "N/A")
    low = data.get("l", "N/A")
    previous = data.get("pc", "N/A")

    return f"{symbol} price: {current}\nHigh: {high}\nLow: {low}\nPrevious close: {previous}"


def get_news(symbol="NVDA"):
    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=7)

    url = (
        f"https://finnhub.io/api/v1/company-news?"
        f"symbol={symbol}&from={week_ago}&to={today}&token={FINNHUB_API_KEY}"
    )

    r = requests.get(url, timeout=10)
    news = r.json()

    if not news:
        return f"No recent news found for {symbol}."

    top_news = news[:5]

    message = f"Latest {symbol} news:\n\n"
    for i, item in enumerate(top_news, 1):
        headline = item.get("headline", "No headline")
        source = item.get("source", "Unknown source")
        link = item.get("url", "")
        message += f"{i}. {headline}\nSource: {source}\n{link}\n\n"

    return message


def analyze_with_openai(symbol="NVDA"):
    quote = get_quote(symbol)
    news = get_news(symbol)

    if not OPENAI_API_KEY:
        return quote + "\n\n" + news + "\n\nOpenAI analysis unavailable: OPENAI_API_KEY not set."

    prompt = f"""
You are a careful trading assistant. Analyze this stock data and news.
Do not give guaranteed buy/sell advice. Give probabilities and risk.

Stock: {symbol}

Quote:
{quote}

News:
{news}

Give:
1. Bullish factors
2. Bearish factors
3. Most likely short-term scenario
4. Risk level
5. Important note for trader
"""

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    data = r.json()

    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return "OpenAI analysis failed.\n\n" + str(data)


@app.route("/")
def home():
    return "Nidal Trader Bot is running"


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()

    if message in ["price", "/price"]:
        reply = get_quote("NVDA")

    elif message in ["news", "/news"]:
        reply = get_news("NVDA")

    elif message in ["analyze", "/analyze"]:
        reply = analyze_with_openai("NVDA")

    else:
        reply = f"TradingView alert received:\n{message}"

    send_telegram(reply)

    return {"status": "sent"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
