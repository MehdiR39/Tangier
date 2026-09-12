"""Suivre chaque lancement pendant 24 heures, pas 30 minutes.

RAISON D ETRE. Toute la recherche de ce projet s arrete a T+30 min : `solana_suivi` suit un
lancement une demi-heure, et le moteur vendait a 30 min maximum. Or deux faits, mesures le 09/09,
disent que l argent se fait APRES :

  - la chaine de l operateur : il a tenu 2dDDte quatre heures et encaisse x3,13. Le moteur, sur le
    meme jeton, serait sorti a T+30 min a x1,5 au mieux ;
  - l ecran de DexScreener : STONKSZN +433 % a 17 h d age, bob +712 % a 3 h, CARDCAT +508 % a 11 h.
    Ces jetons montent encore des heures apres leur naissance, et tous ont survecu a la premiere
    heure -- la ou un lancement sur cinq meurt.

L hypothese a tester n a jamais ete testee faute de donnees : NE PAS ACHETER LA NAISSANCE, ACHETER LA
SURVIE. Entrer a T+1 h sur ce qui tient, avec de la liquidite et du volume reels, et tenir des
heures. Sur 787 courbes existantes, 6 depassent six heures. Ce module collecte celles qui manquent.

COMMENT. Le flux depose les migrations dans `solana_stream_launches`. On suit chaque mint pendant
`heures` heures, a une cadence qui se relache avec l age -- l information par minute baisse a mesure
que le jeton vieillit, et DexScreener rend 25 jetons par appel :

    T+15 min a T+1 h     toutes les    60 s
    T+1 h   a T+6 h      toutes les   300 s
    T+6 h   a T+24 h     toutes les   900 s

La premiere quart d heure est deja couverte a 10 s par `prix_chaine`, en chaine ; ici la source est
DexScreener, dont le retard de 30 a 60 s ne compte plus a cette echelle. On enregistre ce que
l ecran montre et que la recherche n a jamais eu : volume horaire, achats et ventes de l heure, en
plus du prix, de la liquidite et de la capitalisation.

COUT. Environ 70 lancements par heure vivent 24 h, soit ~1 700 jetons suivis en regime etabli. Aux
cadences ci-dessus cela fait de l ordre de 15 appels DexScreener par minute, sous sa limite de 300.

CE MODULE N ACHETE RIEN, NE VEND RIEN, NE SIGNE RIEN. Il ecrit dans `solana_suivi_long`.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

TOKENS_URL = "https://api.dexscreener.com/latest/dex/tokens/"

# (age minimal en secondes, cadence en secondes) -- ordonne par age croissant
CADENCES = ((15 * 60, 60), (60 * 60, 300), (6 * 3600, 900))


def _cadence(age_s: int) -> int | None:
    """La cadence qui s applique a cet age ; None avant 15 min, couvert ailleurs."""
    if age_s < CADENCES[0][0]:
        return None
    pas = CADENCES[0][1]
    for seuil, p in CADENCES:
        if age_s >= seuil:
            pas = p
    return pas


class SuiviLong:
    def __init__(self, ctx, client) -> None:
        self.ctx, self.client = ctx, client
        self.dernier: dict[str, int] = {}          # mint -> ts du dernier releve
        self.pair_de: dict[str, str] = {}          # mint -> pair_id retenu (le plus profond)

    def _cfg(self, cle: str, defaut):
        return self.ctx.config.get("solana.suivi_long." + cle, defaut)

    async def cycle(self) -> dict[str, Any]:
        from intel.utils.timeutil import now_ts

        db = self.ctx.db
        db.execute("CREATE TABLE IF NOT EXISTS solana_suivi_long("
                   "  pair_id TEXT NOT NULL, mint TEXT, ts INTEGER NOT NULL, age_min REAL,"
                   "  price_usd REAL, liquidity_usd REAL, market_cap REAL,"
                   "  volume_h1 REAL, volume_h24 REAL, buys_h1 INTEGER, sells_h1 INTEGER,"
                   "  chg_h1 REAL, chg_h6 REAL,"
                   "  PRIMARY KEY (pair_id, ts))")
        heures = int(self._cfg("heures", 24) or 24)
        now = now_ts()
        lancements = db.query(
            "SELECT mint, ts FROM solana_stream_launches WHERE ts > ? AND ts < ?",
            (now - heures * 3600, now - CADENCES[0][0]))
        if not lancements:
            return {"status": "ok", "suivis": 0}

        # ceux dont la cadence dit qu il est temps
        a_lire: list[tuple[str, int]] = []
        for l in lancements:
            m, cree = l["mint"], int(l["ts"])
            if not m:
                continue
            pas = _cadence(now - cree)
            if pas is None:
                continue
            if now - self.dernier.get(m, 0) >= pas:
                a_lire.append((m, cree))
        if not a_lire:
            return {"status": "ok", "suivis": len(lancements), "lus": 0}

        ecrits = 0
        for i in range(0, len(a_lire), 25):
            lot = a_lire[i:i + 25]
            try:
                r = await self.client.get(TOKENS_URL + ",".join(m for m, _ in lot), timeout=25)
                paires = (r.json() or {}).get("pairs") or []
            except Exception:  # noqa: BLE001
                continue
            # une seule paire par jeton : la plus profonde, celle ou le negoce a lieu
            par_mint: dict[str, dict] = {}
            for p in paires:
                if p.get("chainId") != "solana":
                    continue
                m = ((p.get("baseToken") or {}).get("address") or "")
                liq = float((p.get("liquidity") or {}).get("usd") or 0)
                if m and (m not in par_mint or liq > float((par_mint[m].get("liquidity") or {}).get("usd") or 0)):
                    par_mint[m] = p
            for m, cree in lot:
                self.dernier[m] = now
                p = par_mint.get(m)
                if not p:
                    continue
                pid = p.get("pairAddress")
                if not pid:
                    continue
                self.pair_de[m] = pid
                v, t, c = p.get("volume") or {}, p.get("txns") or {}, p.get("priceChange") or {}
                h1 = t.get("h1") or {}
                try:
                    db.execute(
                        "INSERT OR IGNORE INTO solana_suivi_long(pair_id, mint, ts, age_min, price_usd,"
                        " liquidity_usd, market_cap, volume_h1, volume_h24, buys_h1, sells_h1, chg_h1, chg_h6)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, m, now, (now - cree) / 60.0,
                         float(p.get("priceUsd") or 0) or None,
                         float((p.get("liquidity") or {}).get("usd") or 0) or None,
                         float(p.get("marketCap") or p.get("fdv") or 0) or None,
                         float(v.get("h1") or 0) or None, float(v.get("h24") or 0) or None,
                         int(h1.get("buys") or 0), int(h1.get("sells") or 0),
                         float(c.get("h1")) if c.get("h1") is not None else None,
                         float(c.get("h6")) if c.get("h6") is not None else None))
                    ecrits += 1
                except Exception:  # noqa: BLE001
                    pass
        return {"status": "ok", "suivis": len(lancements), "lus": len(a_lire), "ecrits": ecrits}
