#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Recuperer les cloture journalieres 2017-2021 pour ouvrir une TROISIEME periode de test.

Le signal on-chain n'a qu'une seule periode hors echantillon (2020-2021, douze rebalancements), ce
qui est trop court pour distinguer une dependance au regime d'un surajustement. Les metriques
CoinMetrics remontent a 2009 ; ce sont les prix qui manquent avant octobre 2020.

Binance publie ses chandelles journalieres sans cle. On prend 2017-2021, qui couvre le bear de 2018
et la reprise de 2019 -- des regimes absents des deux periodes actuelles. Environ 37 rebalancements,
trois fois l'echantillon hors calibration actuel.

Lecture seule d'une API publique de marche. Aucune cle, aucun ordre.
"""
import os
import sys
import time
import httpx
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data_raw")
COINS = ["BTC", "ETH", "BNB", "ADA", "XRP", "DOGE", "LTC", "LINK", "XLM", "XTZ",
         "TRX", "ETC", "ZEC", "ALGO", "MANA", "DOT", "UNI", "AAVE", "ICP"]
DEBUT, FIN = "2017-01-01", "2021-06-30"
BASES = ["https://api.binance.com", "https://data-api.binance.vision"]


def klines(client, base, sym, start_ms, end_ms):
    out = []
    while start_ms < end_ms:
        r = client.get(base + "/api/v3/klines",
                       params={"symbol": sym, "interval": "1d", "startTime": start_ms,
                               "endTime": end_ms, "limit": 1000})
        if r.status_code != 200:
            return None if not out else out
        d = r.json()
        if not d:
            break
        out += d
        start_ms = d[-1][0] + 86_400_000
        if len(d) < 1000:
            break
        time.sleep(0.15)
    return out


def main():
    s = int(pd.Timestamp(DEBUT).timestamp() * 1000)
    e = int(pd.Timestamp(FIN).timestamp() * 1000)
    cols = {}
    with httpx.Client(timeout=30) as c:
        base_ok = None
        for b in BASES:
            try:
                if c.get(b + "/api/v3/ping").status_code == 200:
                    base_ok = b
                    break
            except Exception:
                continue
        if not base_ok:
            print("  aucun point d acces Binance joignable"); sys.exit(1)
        print("  point d acces :", base_ok)
        for co in COINS:
            sym = co + "USDT"
            d = klines(c, base_ok, sym, s, e)
            if not d:
                print("  %-6s aucune donnee" % co); continue
            idx = pd.to_datetime([x[0] for x in d], unit="ms").normalize()
            cols[sym] = pd.Series([float(x[4]) for x in d], index=idx)
            print("  %-6s %4d jours  %s -> %s" % (co, len(d), idx.min().date(), idx.max().date()))
    if not cols:
        sys.exit(1)
    df = pd.DataFrame(cols).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    p = os.path.join(RAW, "broad_2017_2021.csv")
    df.to_csv(p)
    print("\n  ecrit %s : %d lignes x %d colonnes, %s -> %s" % (
        p, len(df), df.shape[1], df.index.min().date(), df.index.max().date()))


if __name__ == "__main__":
    main()
