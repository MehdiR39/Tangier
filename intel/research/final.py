"""One command, one consistent build, one file: the complete study from the raw events.

Every number in the final report has to come from the SAME construction of the observations and
labels. Yesterday's retractions all traced back to figures computed on different data than the
ones they were compared to. So this rebuilds rp_snap / rp_label first, then runs the three
analyses on that build, and writes everything to a single timestamped file that is kept.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import sys
import time

from intel.context import IntelContext
from intel.research import RESEARCH_DB
from intel.research.build import build
from intel.research.layers import run as run_layers
from intel.research.report import native_price_usd, quote_maps, run as run_report
from intel.research.schema import connect


def snapshot(src: str, stamp: str) -> str:
    """Freeze the sample: a collector may still be writing to the live file, and the report has
    to be reproducible from exactly the rows it was computed on. Also avoids the write lock that
    killed the first run of this orchestrator."""
    import sqlite3
    dst = f"/app/data/research_snapshot_{stamp}.sqlite"
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    s.backup(d)
    d.close()
    s.close()
    return dst


def main(db_path: str = RESEARCH_DB, ticket: float = 20.0) -> str:
    ctx = IntelContext.build()
    out = io.StringIO()
    stamp = time.strftime("%Y%m%d-%H%M")
    path = f"/app/data/research_final_{stamp}.txt"
    db_path = snapshot(db_path, stamp)
    try:
        nat = asyncio.run(native_price_usd(ctx))
        usd, dec = quote_maps(ctx, nat)          # without these, no exit is ever refused for size
        with contextlib.redirect_stdout(out):
            con = connect(db_path)
            n_pool = con.execute("SELECT COUNT(*) FROM rp_pool").fetchone()[0]
            n_alive = con.execute("SELECT COUNT(*) FROM rp_pool WHERE n_swaps>0").fetchone()[0]
            n_tr = con.execute("SELECT COUNT(*) FROM rp_pool WHERE n_swaps>0 AND transfers_status='ok'").fetchone()[0]
            n_bad = con.execute("SELECT COUNT(*) FROM rp_pool WHERE swaps_status<>'ok' OR transfers_status LIKE 'failed%'").fetchone()[0]
            con.close()
            print(f"RAPPORT FINAL · {stamp} · {db_path}")
            print(f"{n_pool} lancements · {n_alive} vivants · {n_tr} avec transferts · "
                  f"{n_bad} pools avec un echec de collecte (comptes)\n")
            print("=== CONSTRUCTION ===")
            b = build(db_path=db_path, pool_manager=ctx.pool_manager, verbose=False)
            for k, v in b.items():
                print(f"  {k:<24} {v}")
            print()
            print("#" * 96)
            print("PARTIE 1 · LANCEMENTS, TAUX DE BASE, REGLE D'ACTIVITE, LIVRE")
            print("#" * 96)
            run_report(ctx, db_path, ticket=ticket, native_usd=nat)
            print()
            print("#" * 96)
            print("PARTIE 2 · TEST EN COUCHES  A tous -> B security -> C +momentum -> D +organic flow")
            print("#" * 96)
            run_layers(db_path, quote_usd=usd, quote_dec=dec)
        text = out.getvalue()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        sys.stdout.write(text)
        print(f"\n[ecrit dans {path}]")
        return path
    finally:
        asyncio.run(ctx.close())


if __name__ == "__main__":
    main(ticket=float(sys.argv[1]) if len(sys.argv) > 1 else 20.0)
