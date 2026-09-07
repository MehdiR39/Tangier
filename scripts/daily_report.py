#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Daily crypto report -> Telegram.

One morning message combining, for a watchlist of coins:
  * MARKET / timing : BTC regime, Fear&Greed, BTC funding -> deploy or cash
  * PER-COIN signals: adoption trend (active addresses, IN/OUT), MVRV,
                      price technicals (trend vs MA50/MA200, RSI14, 30d momentum)
  * WHAT MOVES      : CoinGecko trending + top gainers/losers 24h
  * NEWS            : CryptoPanic hot headlines

Standard library ONLY (urllib/json/statistics) -> no numpy/pandas, no DLL issues,
runs fine as a scheduled task.

Config (scripts/daily_report_config.json, git-ignored) or env vars:
  telegram_bot_token / TELEGRAM_BOT_TOKEN
  telegram_chat_id   / TELEGRAM_CHAT_ID
  cryptopanic_token  / CRYPTOPANIC_TOKEN   (optional)

Usage:
  python scripts/daily_report.py            # fetch + send to Telegram
  python scripts/daily_report.py --dry-run  # fetch + print to console (no send)
"""
import os
import sys
import ssl
import json
import time
import html
import statistics
import datetime as dt
import urllib.request
import urllib.parse
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (tangier-daily)"}

# base ticker -> (Binance perp/spot symbol, Coin Metrics asset id)
WATCH = ["BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "LINK", "DOT", "LTC",
         "UNI", "ETC", "XLM", "ALGO", "ICP", "AAVE", "MANA", "ZEC", "XTZ"]

# base ticker -> CoinGecko id (free community sentiment / attention)
GECKO_ID = {
    "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin", "XRP": "ripple",
    "ADA": "cardano", "DOGE": "dogecoin", "LINK": "chainlink", "DOT": "polkadot",
    "LTC": "litecoin", "UNI": "uniswap", "ETC": "ethereum-classic", "XLM": "stellar",
    "ALGO": "algorand", "ICP": "internet-computer", "AAVE": "aave",
    "MANA": "decentraland", "ZEC": "zcash", "XTZ": "tezos",
}


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def _read_env_file(path):
    """Minimal .env parser (stdlib only) -> dict."""
    d = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def load_config():
    """Precedence: daily_report_config.json (non-empty) -> repo .env -> OS env."""
    cfg = {}
    p = os.path.join(HERE, "daily_report_config.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    envf = _read_env_file(os.path.join(HERE, "..", ".env"))

    def pick(json_key, env_key):
        return cfg.get(json_key) or envf.get(env_key) or os.environ.get(env_key, "")

    return {
        "bot":  pick("telegram_bot_token", "TELEGRAM_BOT_TOKEN"),
        "chat": pick("telegram_chat_id", "TELEGRAM_CHAT_ID"),
        "cp":   pick("cryptopanic_token", "CRYPTOPANIC_TOKEN"),
        "cg":   pick("coingecko_key", "COINGECKO_KEY"),   # optional free Demo key
    }


# --------------------------------------------------------------------------- #
# http
# --------------------------------------------------------------------------- #
def get_json(url, tries=4, pause=1.2):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                        timeout=40, context=CTX) as r:
                return json.load(r)
        except Exception as e:  # noqa
            last = e
            time.sleep(pause * (2 ** i))
    print(f"  [warn] get failed: {url[:70]}... ({last})")
    return None


# --------------------------------------------------------------------------- #
# indicators (pure python)
# --------------------------------------------------------------------------- #
def sma(v, n):
    return sum(v[-n:]) / n if len(v) >= n else None


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    g = l = 0.0
    for i in range(-n, 0):
        ch = closes[i] - closes[i - 1]
        g += max(ch, 0.0); l += max(-ch, 0.0)
    if l == 0:
        return 100.0
    rs = (g / n) / (l / n)
    return 100 - 100 / (1 + rs)


def pct(v, n):
    return (v[-1] / v[-1 - n] - 1) if len(v) > n and v[-1 - n] else None


# --------------------------------------------------------------------------- #
# fetchers
# --------------------------------------------------------------------------- #
def binance_daily(sym, limit=260):
    d = get_json(f"https://data-api.binance.vision/api/v3/klines"
                 f"?symbol={sym}&interval=1d&limit={limit}")
    if not d:
        return None
    return [float(k[4]) for k in d]   # close prices, oldest->newest


def fear_greed():
    d = get_json("https://api.alternative.me/fng/?limit=1")
    if not d:
        return None
    x = d["data"][0]
    return int(x["value"]), x["value_classification"]


def btc_funding_7d():
    d = get_json("https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=21")
    if not d:
        return None
    rates = [float(x["fundingRate"]) for x in d]
    return sum(rates) / len(rates)


def cg_markets():
    d = get_json("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
                 "&order=market_cap_desc&per_page=250&page=1"
                 "&price_change_percentage=24h,7d,30d")
    if not isinstance(d, list):
        return {}, []
    by_sym = {}
    for x in d:
        by_sym[(x.get("symbol") or "").upper()] = x
    return by_sym, d


def cg_trending():
    d = get_json("https://api.coingecko.com/api/v3/search/trending")
    if not d:
        return []
    return [c["item"]["symbol"].upper() for c in d.get("coins", [])[:7]]


def coinmetrics(asset):
    """last ~400 daily AdrActCnt + CapMVRVCur for one asset."""
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=400)).strftime("%Y-%m-%d")
    url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
           f"?assets={asset}&metrics=AdrActCnt,CapMVRVCur&frequency=1d"
           f"&start_time={start}&page_size=1000")
    d = get_json(url)
    adr, mv = [], []
    if d and "data" in d:
        for x in d["data"]:
            if x.get("AdrActCnt") is not None:
                adr.append(float(x["AdrActCnt"]))
            if x.get("CapMVRVCur") is not None:
                mv.append(float(x["CapMVRVCur"]))
    return adr, mv


def rss_headlines(n=5):
    """Keyless multi-source RSS (CoinDesk + Cointelegraph). Never needs a key."""
    import re
    feeds = [("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk"),
             ("https://cointelegraph.com/rss", "Cointelegraph")]
    out = []
    for url, name in feeds:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                        timeout=25, context=CTX) as r:
                xml = r.read().decode("utf-8", "ignore")
        except Exception:  # noqa
            continue
        for it in re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)[:3]:
            m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.DOTALL)
            if m and m.group(1).strip():
                out.append((m.group(1).strip(), name))
        if len(out) >= n:
            break
    return out[:n]


def get_news(token, n=5):
    """CryptoPanic (classic v1) if the token works from this host, else RSS.

    Note: CryptoPanic sits behind Cloudflare which 403s some datacenter IPs; it
    typically works from a residential IP (the user's PC). RSS is the guaranteed
    fallback so the NEWS block is never empty.
    """
    if token:
        d = get_json(f"https://cryptopanic.com/api/v1/posts/"
                     f"?auth_token={token}&public=true", tries=2)
        if d and d.get("results"):
            out = [((r.get("title") or "").strip(), (r.get("source") or {}).get("title", ""))
                   for r in d["results"][:n]]
            out = [o for o in out if o[0]]
            if out:
                return out
    return rss_headlines(n)


# --------------------------------------------------------------------------- #
# regime from BTC closes
# --------------------------------------------------------------------------- #
def regime(closes):
    if len(closes) < 100:
        return "?"
    ma = sma(closes, 100)
    r90 = pct(closes, 90)
    c = closes[-1]
    if r90 is None:
        return "?"
    if r90 > 0.30 and c > ma:
        return "bull"
    if r90 < -0.15 or (c < ma and r90 < 0):
        return "bear"
    return "consolidation"


# --------------------------------------------------------------------------- #
# free social / attention (CoinGecko community sentiment; Reddit/GTrends gated)
# --------------------------------------------------------------------------- #
def coingecko_social(gid, key=""):
    if not gid:
        return None, None
    suffix = f"&x_cg_demo_api_key={key}" if key else ""
    # tries=2 -> fail fast on persistent 429 (spacing in the loop avoids most)
    d = get_json(f"https://api.coingecko.com/api/v3/coins/{gid}"
                 "?localization=false&tickers=false&market_data=false"
                 "&community_data=false&developer_data=false" + suffix, tries=2)
    if not isinstance(d, dict):
        return None, None
    return d.get("sentiment_votes_up_percentage"), d.get("watchlist_portfolio_users")


# --------------------------------------------------------------------------- #
# build report
# --------------------------------------------------------------------------- #
def esc(s):
    return html.escape(str(s), quote=False)


def build():
    today = dt.datetime.now().strftime("%Y-%m-%d")
    print("Fetching market ...", flush=True)
    btc = binance_daily("BTCUSDT")
    reg = regime(btc) if btc else "?"
    fg = fear_greed()
    fund = btc_funding_7d()
    by_sym, all_mkt = cg_markets()
    trending = cg_trending()

    # timing verdict
    deploy = reg in ("consolidation", "bull")
    reg_emoji = {"bull": "🟢 BULL", "consolidation": "🟡 CONSO",
                 "bear": "🔴 BEAR", "?": "?"}[reg]

    lines = [f"<b>📊 CRYPTO DAILY — {today}</b>", ""]
    lines.append("<b>🌡️ MARCHÉ</b>")
    lines.append(f"Régime BTC : {reg_emoji}")
    if fg:
        tag = "Peur" if fg[0] < 45 else "Avidité" if fg[0] > 55 else "Neutre"
        lines.append(f"Fear&amp;Greed : {fg[0]} ({tag})")
    if fund is not None:
        ft = "frothy ⚠️" if fund > 0.0003 else "calme"
        lines.append(f"Funding BTC 7j : {fund*100:+.3f}% ({ft})")
    lines.append(f"👉 <b>{'DÉPLOYER (conso/bull)' if deploy else 'CASH — ne pas déployer (bear)'}</b>")
    lines.append("")

    # per-coin
    print("Fetching per-coin signals ...", flush=True)
    cgkey = load_config()["cg"]
    social_sleep = 0.7 if cgkey else 2.5   # a free Demo key lifts the rate limit
    rows = []
    for c in WATCH:
        closes = binance_daily(c + "USDT")
        adr, mv = coinmetrics(c.lower())
        time.sleep(0.25)
        if not closes:
            continue
        price = closes[-1]
        ma50, ma200 = sma(closes, 50), sma(closes, 200)
        r = rsi(closes, 14)
        m30 = pct(closes, 30)
        # adoption 30d growth
        adg = (adr[-1] / adr[-31] - 1) if len(adr) > 31 and adr[-31] else None
        adopt = "IN " if (adg is not None and adg > 0) else ("OUT" if adg is not None else " - ")
        # mvrv + euphoria flag
        mvrv = mv[-1] if mv else None
        mvmed = statistics.median(mv[-365:]) if len(mv) >= 120 else None
        mvflag = ""
        if mvrv and mvmed:
            if mvrv > 1.3 * mvmed:
                mvflag = "🔴"      # richly valued
            elif mvrv < 0.8 * mvmed:
                mvflag = "🟢"      # cheap vs own history
        # trend (arrows only -> safe inside Telegram HTML <pre>)
        if ma50 and ma200:
            trend = "▲" if (price > ma200 and price > ma50) else ("▼" if price < ma200 else "→")
        else:
            trend = "-"
        # overall coin light
        up = (adopt == "IN ") and ma50 and price > ma50
        down = (adopt == "OUT") and ma200 and price < ma200
        light = "🟢" if up else ("🔴" if down else "🟡")
        # free social/attention (CoinGecko community sentiment) - space out to
        # respect the free rate limit (a Demo key lifts it; else 429s drop coins)
        sent, watch = coingecko_social(GECKO_ID.get(c, ""), cgkey)
        time.sleep(social_sleep)
        rows.append((light, c, adopt, mvrv, mvflag, trend, r, m30, sent, watch))

    lines.append("<b>🎯 SIGNAUX PAR COIN</b>")
    lines.append("<pre>")
    lines.append(f"{'  Coin':<8}{'Adopt':<6}{'MVRV':<7}{'Trend':<6}{'RSI':<5}{'30j'}")
    for light, c, adopt, mvrv, mvflag, trend, r, m30, sent, watch in rows:
        mvs = (f"{mvrv:.2f}{mvflag}" if mvrv else "  -  ")
        rss = f"{r:.0f}" if r is not None else "-"
        m30s = f"{m30*100:+.0f}%" if m30 is not None else "-"
        lines.append(f"{light}{c:<6}{adopt:<6}{mvs:<7}{trend:<6}{rss:<5}{m30s}")
    lines.append("</pre>")
    lines.append("<i>Adopt IN=réseau en croissance (reste) / OUT=décline (sors)."
                 " MVRV 🔴 cher 🟢 bas. 🟢 fort / 🔴 faible / 🟡 mitigé.</i>")
    lines.append("")

    # social / attention (free proxy: CoinGecko community sentiment + trending)
    lines.append("<b>📣 SOCIAL &amp; ATTENTION</b>")
    if trending:
        hot = [t for t in trending if t in WATCH]
        line = "🔥 Trending : " + ", ".join(esc(t) for t in trending[:6])
        if hot:
            line += "  (ta liste : " + ", ".join(hot) + ")"
        lines.append(line)
    sents = [(c, sent) for (_, c, _, _, _, _, _, _, sent, _) in rows if sent is not None]
    if sents:
        sents.sort(key=lambda x: -x[1])
        lines.append("Communauté haussière : " + " · ".join(f"{c} {s:.0f}%" for c, s in sents[:4]))
        lines.append("Moins aimés : " + " · ".join(f"{c} {s:.0f}%" for c, s in sents[-3:]))
    lines.append("<i>Sentiment = % avis haussiers communauté (CoinGecko, proxy social gratuit ; "
                 "Reddit/Google Trends bloqués sans clé).</i>")
    lines.append("")

    # what moves
    if trending or all_mkt:
        lines.append("<b>🔥 CE QUI BOUGE</b>")
        if trending:
            lines.append("Trending : " + ", ".join(esc(t) for t in trending))
        if all_mkt:
            top = sorted([x for x in all_mkt[:120]
                          if x.get("price_change_percentage_24h") is not None],
                         key=lambda x: x["price_change_percentage_24h"], reverse=True)
            g = top[:3]; lo = top[-3:]
            lines.append("↑ 24h : " + ", ".join(
                f"{esc(x['symbol'].upper())} {x['price_change_percentage_24h']:+.0f}%" for x in g))
            lines.append("↓ 24h : " + ", ".join(
                f"{esc(x['symbol'].upper())} {x['price_change_percentage_24h']:+.0f}%" for x in lo))
        lines.append("")

    # news
    cfg = load_config()
    news = get_news(cfg["cp"])
    if news:
        lines.append("<b>📰 NEWS</b>")
        for title, src in news:
            s = f" — {esc(src)}" if src else ""
            lines.append(f"• {esc(title)}{s}")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# telegram
# --------------------------------------------------------------------------- #
def _tg_post(text, bot, chat, html_mode=True):
    params = {"chat_id": chat, "text": text, "disable_web_page_preview": "true"}
    if html_mode:
        params["parse_mode"] = "HTML"
    data = urllib.parse.urlencode(params).encode()
    url = f"https://api.telegram.org/bot{bot}/sendMessage"
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=UA),
                                timeout=30, context=CTX) as r:
        return json.load(r).get("ok", False)


def send_telegram(text, bot, chat):
    if len(text) > 4096:
        text = text[:4080] + "\n…(tronqué)"
    try:
        return _tg_post(text, bot, chat, html_mode=True)
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print("  [telegram] HTML send failed:", e.code, body)
        # fallback: strip tags and resend as plain text so the report still arrives
        import re
        plain = re.sub(r"<[^>\n]+>", "", text).replace("&amp;", "&")
        try:
            print("  [telegram] retrying as plain text ...")
            return _tg_post(plain, bot, chat, html_mode=False)
        except Exception as e2:  # noqa
            print("  [telegram] plain retry failed:", e2)
            return False
    except Exception as e:  # noqa
        print("  [telegram]", e)
        return False


def get_chat_id():
    """Helper: print chat_id(s) that have messaged the bot (run after messaging it)."""
    cfg = load_config()
    if not cfg["bot"]:
        print("Mets d'abord telegram_bot_token dans scripts/daily_report_config.json")
        return
    d = get_json(f"https://api.telegram.org/bot{cfg['bot']}/getUpdates")
    seen = set()
    for u in (d or {}).get("result", []):
        m = u.get("message") or u.get("channel_post") or {}
        ch = m.get("chat", {})
        cid = ch.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            who = ch.get("first_name") or ch.get("title") or ""
            print(f"  chat_id = {cid}   ({ch.get('type')}, {who})")
    if not seen:
        print("  Aucun message reçu. Envoie 'hello' à ton bot sur Telegram, puis relance.")


def main():
    if "--chat-id" in sys.argv:
        get_chat_id()
        return
    dry = "--dry-run" in sys.argv
    msg = build()
    if dry:
        print("\n" + "=" * 60 + "\n(DRY RUN — message below)\n" + "=" * 60)
        # strip tags for console readability (do NOT let [^>] eat newlines)
        import re
        print(re.sub(r"<[^>\n]+>", "", msg))
        print("\n[message length: %d chars]" % len(msg))
        return
    cfg = load_config()
    if not cfg["bot"] or not cfg["chat"]:
        print("ERROR: telegram_bot_token / telegram_chat_id missing "
              "(scripts/daily_report_config.json or env vars).")
        sys.exit(1)
    ok = send_telegram(msg, cfg["bot"], cfg["chat"])
    print("Telegram sent." if ok else "Telegram send FAILED.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
