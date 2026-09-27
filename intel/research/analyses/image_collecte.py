"""L IMAGE DU JETON DIT-ELLE QUELQUE CHOSE ? Collecte et mesure, sur l HOTE.

D OU VIENT LA QUESTION. Mido, capture d ecran de son portefeuille a l appui : « j ai constate que
la majorite des crashs vient des memes avec comme photo un fond noir et l ecriture au milieu,
souvent le nom ». C est une observation d operateur, et c est exactement le genre qui a produit le
seul vrai signal de la journee (§3.121) -- le balayage automatique ne l aurait jamais trouvee, parce
qu il ne regardait que des nombres.

POURQUOI C EST UNE BONNE PISTE A PRIORI. Toutes les variables testees jusqu ici decrivent le PRIX
ou le MARCHE, et toutes disent la meme chose : ce qui predit la chute predit aussi la montee (« le
modele mesure la VIE, pas le danger »). Une image ne dit rien du marche : elle dit QUI a cree le
jeton et AVEC QUEL SOIN. Un fond noir avec le nom ecrit dessus est la signature d une creation
industrielle, generee en masse sans effort -- une information d une nature entierement differente,
donc potentiellement DECORRELEE, ce qui est la seule chose qui ait de la valeur ici.

POURQUOI IL TOURNE SUR L HOTE. Le conteneur n a pas PIL, et il trade en REEL : on n installe pas de
paquets sur un processus qui signe des transactions. Ce script lit la base en lecture seule via
`docker exec`, travaille sur l hote, et ecrit dans son propre fichier.

CE QU IL MESURE, choisi pour l hypothese de Mido et rien d autre :
    luminance          un fond noir a une luminance basse
    part_sombre        la proportion de pixels quasi noirs
    part_claire        du texte blanc sur fond noir en fait quelques pourcents
    n_couleurs         une image generee en a tres peu ; une vraie illustration, beaucoup
    bimodalite         la part des pixels dans les deux modes dominants -- une image a deux tons
                       (fond + texte) la fait monter pres de 1
    centre_moins_bord  le texte est AU MILIEU : le centre est plus clair que la peripherie
    empreinte          dHash 64 bits : deux jetons du MEME GABARIT ont des empreintes
                       voisines meme si leurs fichiers different. C est ce qui permet de
                       regrouper les jetons par CREATEUR sans connaitre le createur.

REPRENABLE : chaque jeton deja mesure est saute. On peut l arreter et le relancer sans perte.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "..",
                    "data", "recherche", "images.sqlite")
# PLUSIEURS PASSERELLES, ESSAYEES DANS L ORDRE. Une passerelle publique gratuite repond 429 des
# qu on insiste, et `ipfs.io` repond 403 tout court. En alterner plusieurs multiplie le debit
# utilisable sans marteler aucune d elles. Mesure : pinata repond en ~6 s, dweb en ~0,1 s quand il
# a le contenu en cache mais echoue souvent -- on met donc le rapide d abord et le fiable ensuite.
PASSERELLES = ["https://%s.ipfs.dweb.link",
               "https://gateway.pinata.cloud/ipfs/%s",
               "https://ipfs.filebase.io/ipfs/%s",
               "https://4everland.io/ipfs/%s"]
PASSERELLE = PASSERELLES[1]   # celle qui sert de reference dans les tests
FILS = 4                      # modere : on ne martele pas une passerelle publique gratuite
TAILLE = 64                   # on reduit avant de mesurer : le motif cherche est grossier


def _depuis_conteneur() -> list[tuple[str, str]]:
    """(mint, uri) des jetons qui ont un ticket ANALYSABLE, lus dans le conteneur."""
    code = (
        "import sqlite3;"
        "c=sqlite3.connect('file:/app/db/papier_combo.sqlite?mode=ro',uri=True,timeout=30);"
        "c.execute(\"ATTACH DATABASE 'file:/app/db/intel.sqlite?mode=ro' AS M\");"
        "rows=c.execute('''SELECT DISTINCT d.mint, o.uri FROM decision d"
        " JOIN issue i ON i.pair=d.pair JOIN M.solana_social o ON o.mint=d.mint"
        " WHERE d.eligible=1 AND i.brut_240 IS NOT NULL AND o.uri IS NOT NULL"
        " AND o.uri != \\'\\' ''').fetchall();"
        "print('\\n'.join('%s\\t%s'%r for r in rows))"
    )
    out = subprocess.run(["docker", "exec", "-i", "tangier-intel", "python", "-c", code],
                         capture_output=True, text=True, timeout=180)
    res = []
    for ligne in out.stdout.splitlines():
        if "\t" in ligne:
            m, u = ligne.split("\t", 1)
            if m and u:
                res.append((m.strip(), u.strip()))
    return res


def schema(c: sqlite3.Connection) -> None:
    c.execute("CREATE TABLE IF NOT EXISTS image("
              "  mint TEXT PRIMARY KEY, luminance REAL, part_sombre REAL, part_claire REAL,"
              "  n_couleurs INTEGER, bimodalite REAL, centre_moins_bord REAL,"
              "  largeur INTEGER, hauteur INTEGER, domaine TEXT, empreinte TEXT,"
              "  erreur TEXT, t REAL)")
    c.commit()


def _chercher(cid: str, timeout: int = 20):
    """Recupere un CID en essayant les passerelles dans l ordre. Leve si toutes echouent.

    Ne jamais s arreter a la premiere erreur : un 429 ou un 403 sur une passerelle ne dit rien du
    contenu, seulement de l humeur de cette passerelle-la.
    """
    import requests
    derniere = None
    for p in PASSERELLES:
        try:
            r = requests.get(p % cid, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001
            derniere = exc
    raise RuntimeError("toutes les passerelles ont echoue : %s" % str(derniere)[:80])


def mesurer(uri: str) -> dict:
    """Telecharge la metadonnee puis l image, et rend les mesures. Leve sur echec."""
    from PIL import Image

    # TOUTES LES URI NE SONT PAS DE L IPFS. Une bonne part pointe vers des USINES A JETONS --
    # usepaid.app, vortexdeployer.com, rapidlaunch.io, uxento.io -- qui servent la metadonnee
    # directement en HTTPS. Les traiter comme de l IPFS produisait un « 400 Bad Request » sur
    # toutes les passerelles : 143 echecs sur 400, soit plus du tiers de l echantillon, et pas au
    # hasard -- c est une famille entiere de jetons qui disparaissait de l analyse.
    if uri.startswith("ipfs://") or "/ipfs/" in uri:
        cid = uri.rstrip("/").split("/")[-1]
        meta = _chercher(cid).json()
    else:
        import requests
        rr = requests.get(uri, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        rr.raise_for_status()
        meta = rr.json()
    url = meta.get("image") or ""
    if not url:
        raise ValueError("pas d image dans la metadonnee")
    # L IMAGE POINTE PRESQUE TOUJOURS VERS `ipfs.io`, QUI REFUSE (403). La metadonnee passe par
    # notre passerelle mais son champ `image` garde l URL d origine : il faut la reecrire aussi,
    # sinon tout echoue a la deuxieme requete. Cas rencontres : `ipfs://<cid>` et
    # `https://<hote>/ipfs/<cid>`. Une URL qui n est pas de l IPFS est laissee telle quelle.
    if url.startswith("ipfs://"):
        ri = _chercher(url[7:].split("/")[-1])
    elif "/ipfs/" in url:
        ri = _chercher(url.split("/ipfs/", 1)[1].split("/")[0].split("?")[0])
    else:
        import requests
        ri = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        ri.raise_for_status()
    brut = Image.open(io.BytesIO(ri.content))
    largeur, hauteur = brut.size
    im = brut.convert("L").resize((TAILLE, TAILLE))
    px = list(im.getdata())
    n = len(px)
    # n_couleurs se compte sur l image RGB reduite : une image generee en a une poignee
    rgb = brut.convert("RGB").resize((32, 32))
    couleurs = len(set(rgb.getdata()))
    # EMPREINTE PERCEPTUELLE (dHash 64 bits). C est le coeur de l idee de Mido : « les memes cons
    # refont la meme sorte de crypto ». Deux jetons batis sur le MEME GABARIT -- meme fond, meme
    # mise en page, seul le nom change -- ont des empreintes voisines, alors que leurs FICHIERS
    # sont differents (un hash classique ne verrait rien). On regroupe donc les jetons par
    # CREATEUR sans jamais connaitre le createur.
    #
    # dHash compare chaque pixel a son voisin de droite sur une image 9x8 : il encode la STRUCTURE
    # (ou ça monte, ou ça descend) et non les couleurs, donc il resiste au changement de teinte,
    # de compression et de taille. La distance entre deux empreintes est le nombre de bits qui
    # different.
    g = brut.convert("L").resize((9, 8))
    gp = list(g.getdata())
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (1 if gp[y*9 + x] > gp[y*9 + x + 1] else 0)
    empreinte = "%016x" % bits

    # bimodalite : part des pixels dans les deux tranches de 16 niveaux les plus peuplees
    h = Counter(p // 16 for p in px)
    bimod = sum(v for _, v in h.most_common(2)) / n
    # le texte est AU MILIEU : on compare le carre central au pourtour
    k = TAILLE // 4
    centre = [px[y * TAILLE + x] for y in range(k, TAILLE - k) for x in range(k, TAILLE - k)]
    bord = [px[y * TAILLE + x] for y in range(TAILLE) for x in range(TAILLE)
            if not (k <= y < TAILLE - k and k <= x < TAILLE - k)]
    return {"luminance": sum(px) / n,
            "part_sombre": sum(1 for p in px if p < 40) / n,
            "part_claire": sum(1 for p in px if p > 215) / n,
            "n_couleurs": couleurs,
            "bimodalite": bimod,
            "centre_moins_bord": (sum(centre) / len(centre)) - (sum(bord) / len(bord)),
            "largeur": largeur, "hauteur": hauteur, "empreinte": empreinte}


def main() -> None:
    chemin = os.path.abspath(BASE)
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    c = sqlite3.connect(chemin, timeout=30)
    schema(c)
    # on ne saute que ce qui a REUSSI : une erreur peut venir d une passerelle de
    # mauvaise humeur, pas du contenu, et doit etre reessayee
    # On ne saute que ce qui est COMPLET. Une erreur peut venir d une passerelle de mauvaise
    # humeur plutot que du contenu, et une ligne mesuree avant l ajout de l empreinte est
    # incomplete : les deux doivent etre reprises.
    deja = {r[0] for r in c.execute(
        "SELECT mint FROM image WHERE erreur IS NULL AND empreinte IS NOT NULL")}
    todo = [(m, u) for m, u in _depuis_conteneur() if m not in deja]
    print("a mesurer : %d jetons (%d deja faits)" % (len(todo), len(deja)), flush=True)
    if not todo:
        return
    t0 = time.time()
    faits = [0]

    def un(arg):
        m, u = arg
        try:
            d = mesurer(u)
            return (m, d, None)
        except Exception as exc:  # noqa: BLE001
            return (m, None, str(exc)[:120])

    with ThreadPoolExecutor(max_workers=FILS) as ex:
        for m, d, err in ex.map(un, todo):
            if d:
                c.execute("INSERT OR REPLACE INTO image(mint, luminance, part_sombre, part_claire,"
                          " n_couleurs, bimodalite, centre_moins_bord, largeur, hauteur,"
                          " empreinte, erreur, t) VALUES(?,?,?,?,?,?,?,?,?,?,NULL,?)",
                          (m, d["luminance"], d["part_sombre"], d["part_claire"], d["n_couleurs"],
                           d["bimodalite"], d["centre_moins_bord"], d["largeur"], d["hauteur"],
                           d["empreinte"], time.time()))
            else:
                c.execute("INSERT OR REPLACE INTO image(mint, erreur, t) VALUES(?,?,?)",
                          (m, err, time.time()))
            faits[0] += 1
            if faits[0] % 25 == 0:
                c.commit()
                reste = (len(todo) - faits[0]) * (time.time() - t0) / faits[0]
                print("   %d/%d · %.0f min restantes" % (faits[0], len(todo), reste / 60), flush=True)
    c.commit()
    ok, ko = c.execute("SELECT SUM(erreur IS NULL), SUM(erreur IS NOT NULL) FROM image").fetchone()
    print("termine · %d mesurees, %d en erreur" % (ok or 0, ko or 0))


if __name__ == "__main__":
    sys.exit(main())
