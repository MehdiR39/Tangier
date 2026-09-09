"""Vider le portefeuille compromis vers le nouveau, puis basculer la configuration.

CONTEXTE. Le 09/09/2026, en inspectant la configuration du conteneur collecteur, j ai affiche ses
variables d environnement et la cle privee EVM (`INTEL_EXECUTION_PRIVATE_KEY`) est apparue en clair
dans la conversation. Elle doit etre consideree comme compromise : tout ce que ce portefeuille
detient est accessible a quiconque lit cette conversation.

CE QUE FAIT CE SCRIPT, dans l ordre :
  1. lit l ancienne cle dans .env et la nouvelle dans data/nouveau_portefeuille.txt ;
  2. affiche le solde, le cout du gaz et le montant a transferer, puis DEMANDE confirmation ;
  3. envoie tout le solde moins le gaz vers la nouvelle adresse et attend le recu ;
  4. seulement si le transfert a reussi, remplace la cle dans .env et sauvegarde l ancien fichier.

Aucune cle privee n est affichee, ni ecrite ailleurs que dans les fichiers deja prevus pour ca.

USAGE, depuis le dossier du projet :
    python scripts/rotation_cle.py
puis, une fois le script termine :
    docker compose up -d intel

Le moteur repartira sur le nouveau portefeuille. Le portefeuille Solana n est PAS concerne : sa cle
est dans une autre variable, qui n a pas ete exposee.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import urllib.request

RPC = os.environ.get("INTEL_RPC_URL") or "https://rpc.mainnet.chain.robinhood.com"
ENV = ".env"
NOUVEAU = os.path.join("data", "nouveau_portefeuille.txt")
UA = {"content-type": "application/json", "user-agent": "Mozilla/5.0", "accept": "*/*"}


def rpc(method: str, params: list) -> str:
    req = urllib.request.Request(
        RPC, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers=UA)
    rep = json.load(urllib.request.urlopen(req, timeout=45))
    if "error" in rep:
        raise SystemExit(f"le noeud refuse {method} : {rep['error']}")
    return rep["result"]


def lire_env() -> dict[str, str]:
    out: dict[str, str] = {}
    with open(ENV, encoding="utf-8") as f:
        for ligne in f:
            if "=" in ligne and not ligne.lstrip().startswith("#"):
                k, v = ligne.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def main() -> None:
    if not os.path.exists(ENV):
        raise SystemExit(f"{ENV} introuvable : lance ce script depuis le dossier du projet.")
    if not os.path.exists(NOUVEAU):
        raise SystemExit(f"{NOUVEAU} introuvable : le nouveau portefeuille n a pas ete cree.")
    try:
        from eth_account import Account
    except ImportError:
        raise SystemExit("il manque eth_account : pip install eth-account")

    env = lire_env()
    ancienne = env.get("INTEL_EXECUTION_PRIVATE_KEY")
    if not ancienne:
        raise SystemExit("INTEL_EXECUTION_PRIVATE_KEY absente de .env")
    neuf = dict(l.split("=", 1) for l in open(NOUVEAU, encoding="utf-8").read().split("\n") if "=" in l)
    adresse_neuve, cle_neuve = neuf["ADRESSE"].strip(), neuf["CLE_PRIVEE"].strip()

    compte = Account.from_key(ancienne if ancienne.startswith("0x") else "0x" + ancienne)
    ancienne_adresse = compte.address

    solde = int(rpc("eth_getBalance", [ancienne_adresse, "latest"]), 16)
    prix_gaz = int(rpc("eth_gasPrice", []), 16)
    nonce = int(rpc("eth_getTransactionCount", [ancienne_adresse, "pending"]), 16)
    chain_id = int(rpc("eth_chainId", []), 16)
    gaz = 21000
    cout = prix_gaz * gaz
    envoi = solde - cout

    print(f"  portefeuille compromis : {ancienne_adresse}")
    print(f"  nouveau portefeuille   : {adresse_neuve}")
    print(f"  solde                  : {solde / 1e18:.8f} ETH")
    print(f"  cout du transfert      : {cout / 1e18:.8f} ETH ({prix_gaz / 1e9:.4f} gwei)")
    print(f"  montant transfere      : {envoi / 1e18:.8f} ETH")
    if envoi <= 0:
        raise SystemExit("  le solde ne couvre meme pas le gaz : rien a transferer.")

    if input("\n  taper OUI pour envoyer : ").strip() != "OUI":
        raise SystemExit("  annule, rien n a ete envoye.")

    tx = {"to": adresse_neuve, "value": envoi, "gas": gaz, "gasPrice": prix_gaz,
          "nonce": nonce, "chainId": chain_id}
    signee = Account.from_key(ancienne if ancienne.startswith("0x") else "0x" + ancienne).sign_transaction(tx)
    h = rpc("eth_sendRawTransaction", ["0x" + signee.raw_transaction.hex().removeprefix("0x")])
    print(f"  transaction envoyee : {h}")

    # On n echange la cle QUE si la chaine a confirme le transfert. Sinon le moteur repartirait sur
    # un portefeuille vide en laissant les fonds sur la cle compromise -- le pire des deux mondes.
    for _ in range(60):
        time.sleep(3)
        recu = rpc("eth_getTransactionReceipt", [h])
        if recu:
            if int(recu.get("status", "0x0"), 16) != 1:
                raise SystemExit("  la transaction a echoue en chaine : la cle n est PAS remplacee.")
            print("  transfert confirme.")
            break
    else:
        raise SystemExit("  pas de recu apres trois minutes : verifie la transaction avant de continuer.")

    shutil.copyfile(ENV, ENV + ".compromis")
    lignes = open(ENV, encoding="utf-8").read().splitlines()
    sortie = [f"INTEL_EXECUTION_PRIVATE_KEY={cle_neuve}"
              if l.startswith("INTEL_EXECUTION_PRIVATE_KEY=") else l for l in lignes]
    open(ENV, "w", encoding="utf-8").write("\n".join(sortie) + "\n")
    print(f"  .env mis a jour · ancien fichier garde sous {ENV}.compromis")
    print("\n  Il reste deux choses a faire, dans cet ordre :")
    print("    1. docker compose up -d intel        (le moteur repart sur le nouveau portefeuille)")
    print(f"    2. supprimer {NOUVEAU} et {ENV}.compromis une fois que tout tourne")
    print(f"\n  Le solde du nouveau portefeuille se verifie sur")
    print(f"    https://robinhoodchain.blockscout.com/address/{adresse_neuve}")


if __name__ == "__main__":
    main()
