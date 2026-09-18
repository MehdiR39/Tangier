"""Qui a finance le portefeuille qui detient le sac ? (recidive au niveau du FINANCEUR)

POURQUOI (15/09). La recidive par portefeuille est reelle (un detenteur qui a deja vide revide dans
29-47 % des cas) mais ne couvre que 4 % des jetons : 811 detenteurs pour 908 jetons, les orchestrateurs
prennent un portefeuille neuf a chaque lancement. Un portefeuille neuf doit recevoir du SOL de quelque
part : si c est la meme source d un lancement a l autre, la recidive se voit a ce niveau.

COMMENT. Pour chaque detenteur (plus gros portefeuille a T+30 s, >= 5 % de l offre) : sa transaction
la plus ancienne, et le compte dont le solde SOL y baisse le plus (hors le detenteur) = le financeur.
Sortie : data/recherche/financeurs.jsonl, relancable.
"""
import json, os, time, urllib.request

SACS = "/app/data/recherche/sacs_migration.jsonl"
SORTIE = "/app/data/recherche/financeurs.jsonl"


def rpc(m, p):
    for k in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(os.environ["SOLANA_RPC_URL"], data=json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": m, "params": p}).encode(),
                    headers={"Content-Type": "application/json"}), timeout=40) as f:
                j = json.load(f)
            if "error" in j:
                raise RuntimeError(str(j["error"])[:120])
            return j.get("result")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (k + 1))
    raise RuntimeError(str(last)[:120])


def financeur(w):
    before, oldest, pages = None, None, 0
    while pages < 15:
        opt = {"limit": 1000}
        if before:
            opt["before"] = before
        r = rpc("getSignaturesForAddress", [w, opt]) or []
        pages += 1
        if not r:
            break
        oldest = r[-1]
        before = r[-1]["signature"]
        if len(r) < 1000:
            break
    if not oldest:
        return None, pages, None
    tx = rpc("getTransaction", [oldest["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]
    m = tx["meta"]
    deltas = [(m["postBalances"][i] - m["preBalances"][i], keys[i]) for i in range(len(keys)) if keys[i] != w]
    d, f = min(deltas) if deltas else (0, None)
    return (f if d < 0 else None), pages, oldest.get("blockTime")


def main():
    offre = {}
    faits = set()
    if os.path.exists(SORTIE):
        faits = {json.loads(l)["wallet"] for l in open(SORTIE)}
    wallets = {}
    for l in open(SACS):
        d = json.loads(l)
        if d.get("erreur") or not d.get("instants"):
            continue
        top = d["instants"].get("30", [])
        if top and top[0][1] / 1e9 >= 0.05:
            wallets.setdefault(top[0][0], d["naissance"])
    todo = [w for w in wallets if w not in faits]
    print("financeurs: %d detenteurs a lire" % len(todo), flush=True)
    for i, w in enumerate(todo):
        try:
            f, pages, bt = financeur(w)
            ligne = {"wallet": w, "financeur": f, "pages": pages, "premiere_tx": bt}
        except Exception as e:  # noqa: BLE001
            ligne = {"wallet": w, "erreur": str(e)[:120]}
        with open(SORTIE, "a") as fh:
            fh.write(json.dumps(ligne) + "\n")
        if i % 50 == 49:
            print("financeurs: %d/%d" % (i + 1, len(todo)), flush=True)
        time.sleep(0.15)
    print("financeurs: FINI", flush=True)


if __name__ == "__main__":
    main()
