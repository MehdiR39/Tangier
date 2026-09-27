"""One command for the continuous (Bitquery) dataset: snapshot → adapter → build → layered test → file.

Mirrors final.py so the two datasets are judged by the same code and the same guards. Two things
this run must get right that a bare `layers.run()` does not:
  - the quote prices, so sellability is enforced (without them every printed multiple counts as
    cashable, and the dry run said so in capitals);
  - a frozen copy of the Bitquery file, because the collector may still be writing to it.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import sqlite3
import sys
import time

from intel.context import IntelContext
from intel.research.bitquery import DB_PATH as BQ_DB
from intel.research.bq_adapter import convert
from intel.research.build import build
from intel.research.layers import run as run_layers
from intel.research.report import native_price_usd, quote_maps


def main(entries: tuple[float, ...] = (5.0, 10.0, 15.0)) -> str:
    stamp = time.strftime("%Y%m%d-%H%M")
    snap = f"/app/data/research_bq_snapshot_{stamp}.sqlite"
    rp = f"/app/data/research_bq_rp_{stamp}.sqlite"
    path = f"/app/data/research_final_bq_{stamp}.txt"
    src = sqlite3.connect(f"file:{BQ_DB}?mode=ro", uri=True)
    dst = sqlite3.connect(snap)
    src.backup(dst)
    dst.close()
    src.close()

    ctx = IntelContext.build()
    out = io.StringIO()
    try:
        nat = asyncio.run(native_price_usd(ctx))
        usd, dec = quote_maps(ctx, nat)
        with contextlib.redirect_stdout(out):
            print(f"RAPPORT BITQUERY (collecte continue) · {stamp}")
            c = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
            n_all = c.execute("SELECT COUNT(*) FROM bq_pool").fetchone()[0]
            n_ok = c.execute("SELECT COUNT(*) FROM bq_pool WHERE status='ok'").fetchone()[0]
            n_alive = c.execute("SELECT COUNT(*) FROM bq_pool WHERE status='ok' AND n_trades>0").fetchone()[0]
            span = c.execute("SELECT MIN(ts), MAX(ts) FROM bq_pool WHERE status='ok'").fetchone()
            c.close()
            hours = ((span[1] or 0) - (span[0] or 0)) / 3600
            print(f"{n_all} lancements dans la fenetre · {n_ok} recuperes · {n_alive} vivants · {hours:.1f} h continues")
            print(f"prix du natif : {nat} · quotes valorises : {len(usd)}\n")
            print("=== ADAPTATION ===")
            print(convert(bq_path=snap, out_path=rp, pool_manager=ctx.pool_manager, verbose=False))
            print("=== CONSTRUCTION ===")
            b = build(db_path=rp, pool_manager=ctx.pool_manager, verbose=False)
            print({k: b[k] for k in ("pools", "vivants", "observations", "positions_invendables")})
            print("\nNOTE : profondeur de pool inconnue sur ces donnees (Bitquery ne l'expose pas) — les features "
                  "liq_to_mc / vol5_to_liq sont vides et l'impact utilise sa valeur pessimiste par defaut.\n")
            print("#" * 96)
            print("TEST EN COUCHES  A tous -> B security -> C +momentum -> D +organic flow  (donnees continues)")
            print("#" * 96)
            run_layers(rp, entries=entries, quote_usd=usd, quote_dec=dec)
        text = out.getvalue()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        sys.stdout.write(text)
        print(f"\n[ecrit dans {path}]")
        return path
    finally:
        asyncio.run(ctx.close())


if __name__ == "__main__":
    main()
