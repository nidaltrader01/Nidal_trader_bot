from flask import Flask, request
import requests
import os
import time
import threading
from datetime import datetime, timedelta

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

WATCHLIST = ["NVDA", "MU", "DXYZ", "NASA", "MSFT", "VST"]
MARKET_PROXY = "QQQ"

PRICE_ALERT_PCT = 2.5
VOLUME_ALERT_MULTIPLE = 2.0
CHECK_SECONDS = 60
NEWS_CHECK_SECONDS = 300

last_alerts = {}
seen_news = set()


def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("Missing Telegram variables")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text[:3900]}, timeout=15)


def finnhub_get(endpoint, params):
    params["token"] = FINNHUB_API_KEY
    url = f"https://finnhub.io/api/v1/{endpoint}"
    r = requests.get(url, params=params, timeout=15)
    return r.json()


def get_quote(symbol):
    data = finnhub_get("quote", {"symbol": symbol})
    current = data.get("c", 0)
    prev = data.get("pc", 0)

    if not current or not prev:
        return None

    pct = ((current - prev) / prev) * 100

    return {
        "symbol": symbol,
        "current": current,
        "high": data.get("h"),
        "low": data.get("l"),
        "open": data.get("o"),
        "previous": prev,
        "pct": pct
    }


def get_daily_levels(symbol):
    today = int(time.time())
    past = today - 60 * 60 * 24 * 30

    data = finnhub_get("stock/candle", {
        "symbol": symbol,
        "resolution": "D",
        "from": past,
        "to": today
    })

    if data.get("s") != "ok":
        return None

    highs = data.get("h", [])[-20:]
    lows = data.get("l", [])[-20:]

    if len(highs) < 5 or len(lows) < 5:
        return None

    return {
        "resistance": max(highs[:-1]),
        "support": min(lows[:-1])
    }


def get_volume_signal(symbol):
    now = int(time.time())
    past = now - 60 * 60 * 8

    data = finnhub_get("stock/candle", {
        "symbol": symbol,
        "resolution": "5",
        "from": past,
        "to": now
    })

    if data.get("s") != "ok":
        return None

    volumes = data.get("v", [])
    if len(volumes) < 10:
        return None

    current_vol = volumes[-1]
    avg_vol = sum(volumes[-20:-1]) / max(len(volumes[-20:-1]), 1)

    if avg_vol == 0:
        return None

    multiple = current_vol / avg_vol

    return {
        "current_vol": current_vol,
        "avg_vol": avg_vol,
        "multiple": multiple
    }


def get_news(symbol):
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)

    news = finnhub_get("company-news", {
        "symbol": symbol,
        "from": yesterday,
        "to": today
    })

    if not isinstance(news, list):
        return []

    return news[:5]


def ai_analyze(title, symbol, quote=None, market=None):
    if not OPENAI_API_KEY:
        return "OpenAI analysis unavailable."

    prompt = f"""
Analyze this market event as a hedge-fund style trading assistant.

Stock: {symbol}
Headline/Event: {title}

Stock quote:
{quote}

Nasdaq/QQQ context:
{market}

Give concise Arabic analysis:
1. هل الخبر إيجابي أم سلبي؟
2. التأثير المتوقع على السهم خلال الجلسة القادمة
3. التأثير على السوق/ناسداك إن وجد
4. السيناريو الصاعد والهابط
5. هل يستحق تنبيه تداول أم مجرد ضجيج؟
No guaranteed buy/sell advice.
"""

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.25
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"AI analysis failed: {e}"


def cooldown(key, minutes=30):
    now = time.time()
    last = last_alerts.get(key, 0)
    if now - last < minutes * 60:
        return True
    last_alerts[key] = now
    return False


def check_symbol(symbol):
    quote = get_quote(symbol)
    if not quote:
        return

    market = get_quote(MARKET_PROXY)

    # abnormal price move
    if abs(quote["pct"]) >= PRICE_ALERT_PCT:
        key = f"{symbol}_price_move"
        if not cooldown(key, 30):
            analysis = ai_analyze(
                f"{symbol} abnormal price move {quote['pct']:.2f}%",
                symbol,
                quote,
                market
            )
            send_telegram(
                f"⚠️ حركة سعر غير طبيعية\n"
                f"{symbol}: {quote['current']}\n"
                f"Change: {quote['pct']:.2f}%\n\n{analysis}"
            )

    # support / resistance
    levels = get_daily_levels(symbol)
    if levels:
        resistance = levels["resistance"]
        support = levels["support"]

        if quote["current"] > resistance * 1.002:
            key = f"{symbol}_breakout"
            if not cooldown(key, 60):
                analysis = ai_analyze(
                    f"{symbol} broke resistance {resistance}",
                    symbol,
                    quote,
                    market
                )
                send_telegram(
                    f"🚀 اختراق مقاومة\n"
                    f"{symbol}: {quote['current']}\n"
                    f"Resistance: {resistance}\n\n{analysis}"
                )

        if quote["current"] < support * 0.998:
            key = f"{symbol}_breakdown"
            if not cooldown(key, 60):
                analysis = ai_analyze(
                    f"{symbol} broke support {support}",
                    symbol,
                    quote,
                    market
                )
                send_telegram(
                    f"🔻 كسر دعم\n"
                    f"{symbol}: {quote['current']}\n"
                    f"Support: {support}\n\n{analysis}"
                )

    # unusual volume
    vol = get_volume_signal(symbol)
    if vol and vol["multiple"] >= VOLUME_ALERT_MULTIPLE:
        key = f"{symbol}_volume"
        if not cooldown(key, 30):
            analysis = ai_analyze(
                f"{symbol} unusual volume {vol['multiple']:.2f}x average",
                symbol,
                quote,
                market
            )
            send_telegram(
                f"📊 فوليوم غير طبيعي\n"
                f"{symbol}\n"
                f"Volume multiple: {vol['multiple']:.2f}x\n\n{analysis}"
            )


def check_news(symbol):
    quote = get_quote(symbol)
    market = get_quote(MARKET_PROXY)
    news = get_news(symbol)

    for item in news:
        headline = item.get("headline", "")
        url = item.get("url", "")
        source = item.get("source", "")

        news_id = url or headline
        if not headline or news_id in seen_news:
            continue

        seen_news.add(news_id)

        analysis = ai_analyze(headline, symbol, quote, market)

        send_telegram(
            f"📰 خبر جديد: {symbol}\n"
            f"{headline}\n"
            f"Source: {source}\n"
            f"{url}\n\n"
            f"{analysis}"
        )


def check_market():
    qqq = get_quote(MARKET_PROXY)
    if not qqq:
        return

    if abs(qqq["pct"]) >= 1.0:
        key = "market_move"
        if not cooldown(key, 30):
            analysis = ai_analyze(
                f"Nasdaq proxy QQQ moving {qqq['pct']:.2f}%",
                "QQQ",
                qqq,
                qqq
            )
            send_telegram(
                f"📈 حركة قوية في ناسداك / QQQ\n"
                f"QQQ: {qqq['current']}\n"
                f"Change: {qqq['pct']:.2f}%\n\n{analysis}"
            )


def monitor_loop():
    send_telegram("✅ Nidal Trader Bot started monitoring stocks and news.")

    last_news_time = 0

    while True:
        try:
            check_market()

            for symbol in WATCHLIST:
                check_symbol(symbol)

            if time.time() - last_news_time > NEWS_CHECK_SECONDS:
                for symbol in WATCHLIST:
                    check_news(symbol)
                last_news_time = time.time()

        except Exception as e:
            print("Monitor error:", e)

        time.sleep(CHECK_SECONDS)


@app.route("/")
def home():
    return "Nidal Trader Bot is running"


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip().upper()

    if message.startswith("PRICE"):
        parts = message.split()
        symbol = parts[1] if len(parts) > 1 else "NVDA"
        quote = get_quote(symbol)
        reply = str(quote) if quote else f"No data for {symbol}"

    elif message.startswith("NEWS"):
        parts = message.split()
        symbol = parts[1] if len(parts) > 1 else "NVDA"
        news = get_news(symbol)
        reply = "\n\n".join([n.get("headline", "") for n in news]) or "No news."

    elif message.startswith("ANALYZE"):
        parts = message.split()
        symbol = parts[1] if len(parts) > 1 else "NVDA"
        quote = get_quote(symbol)
        market = get_quote(MARKET_PROXY)
        reply = ai_analyze(f"Manual analysis request for {symbol}", symbol, quote, market)

    else:
        reply = f"TradingView/Webhook alert received:\n{message}"

    send_telegram(reply)
    return {"status": "sent"}


threading.Thread(target=monitor_loop, daemon=True).start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
