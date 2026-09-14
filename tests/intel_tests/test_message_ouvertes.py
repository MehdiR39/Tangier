"""Le message de vente doit dire combien de positions restent ouvertes, et ce qu elles valent.

Demande de l operateur le 14/09. Le point delicat est le RESULTAT LATENT : partout ailleurs le
moteur lit le resultat sur le portefeuille, mais pour une position non vendue c est impossible. On
ne peut que citer la cotation -- celle-la meme qui avait fait annoncer +5,05 EUR sur une ligne
payee +2,54 le 08/09. Le mot « estime » doit donc etre present, et ces cas le verrouillent.
"""
from __future__ import annotations

import time

from intel.engines.telegram_rapide import TelegramRapide


class _Row(dict):
    def keys(self):
        return super().keys()


class _Db:
    def __init__(self, fermees, ouvertes):
        self.fermees, self.ouvertes = fermees, ouvertes

    def query(self, sql, params=()):
        if "statut='OUVERTE'" in sql:
            return self.ouvertes
        if "GROUP BY meth" in sql:
            par = {}
            for l in self.fermees:
                m = l.get("methode", "telegram")
                d = par.setdefault(m, {"meth": m, "n": 0, "g": 0.0, "m": 0.0, "w": 0})
                d["n"] += 1
                d["g"] += l["gain_eur"]
                d["m"] += l["mise_eur"]
                d["w"] += 1 if l["gain_eur"] > 0 else 0
            return list(par.values())
        if "ts_sortie >=" in sql:
            return [{"n": len(self.fermees),
                     "g": sum(l["gain_eur"] for l in self.fermees),
                     "w": sum(1 for l in self.fermees if l["gain_eur"] > 0)}]
        return [{"n": len(self.fermees),
                 "g": sum(l["gain_eur"] for l in self.fermees),
                 "m": sum(l["mise_eur"] for l in self.fermees),
                 "w": sum(1 for l in self.fermees if l["gain_eur"] > 0)}]

    def execute(self, sql, params=()):
        return None

    def scalar(self, sql, params=(), defaut=None):
        return defaut


class _Config:
    def get(self, cle, defaut=None):
        return defaut


class _Ctx:
    def __init__(self, fermees, ouvertes):
        self.db = _Db(fermees, ouvertes)
        self.config = _Config()


def _moteur(fermees, ouvertes, prix=None):
    m = TelegramRapide(_Ctx(fermees, ouvertes), client=None)
    m._prix = lambda mint, now, fraicheur=30, pair=None: prix
    return m


FERMEES = [{"gain_eur": 10.0, "mise_eur": 120.0, "methode": "telegram"},
           {"gain_eur": -5.0, "mise_eur": 30.0, "methode": "propre"}]


def _ouverte(sym, mise, prix_entree, meth, pair="pool1"):
    return _Row(mint="Mint" + sym, symbole=sym, pair_id=pair, mise_eur=mise,
                prix_entree=prix_entree, ts_entree=int(time.time()) - 60, meth=meth)


def test_le_nombre_de_positions_ouvertes_apparait():
    m = _moteur(FERMEES, [_ouverte("AAA", 120.0, 1.0, "telegram"),
                          _ouverte("BBB", 30.0, 2.0, "propre")],
                prix=(1.1, 20, "pool1", 80.0))
    t = m._cumul()
    assert "2 position(s) ouverte(s)" in t
    assert "150 EUR engages" in t


def test_le_detail_par_carnet_apparait():
    m = _moteur(FERMEES, [_ouverte("AAA", 120.0, 1.0, "telegram"),
                          _ouverte("BBB", 30.0, 2.0, "propre"),
                          _ouverte("CCC", 30.0, 2.0, "propre")],
                prix=(1.0, 20, "pool1", 80.0))
    t = m._cumul()
    assert "Telegram 1" in t
    assert "Propre (sans TG) 2" in t


def test_le_resultat_latent_est_marque_comme_estime():
    """Sans ce mot, un chiffre de cotation se lit comme un fait du portefeuille."""
    m = _moteur(FERMEES, [_ouverte("AAA", 100.0, 1.0, "telegram")],
                prix=(1.2, 20, "pool1", 80.0))
    t = m._cumul()
    assert "estime sur la cotation" in t
    assert "+20.00 EUR" in t, "100 EUR a x1,2 doit donner +20 EUR de latent"


def test_sans_cotation_lisible_on_annonce_le_nombre_sans_inventer_de_chiffre():
    m = _moteur(FERMEES, [_ouverte("AAA", 120.0, 1.0, "telegram")], prix=None)
    t = m._cumul()
    assert "1 position(s) ouverte(s)" in t
    assert "latent" not in t, "aucun latent ne doit etre annonce si aucune cotation n est lue"


def test_aucune_position_ouverte_n_ajoute_rien():
    m = _moteur(FERMEES, [])
    t = m._cumul()
    assert "position(s) ouverte(s)" not in t


def test_une_base_qui_leve_ne_casse_pas_le_message():
    """Le cumul doit partir meme si le bloc des ouvertes echoue : c est un bonus, pas le message."""
    m = _moteur(FERMEES, [])

    def casse(sql, params=()):
        if "statut='OUVERTE'" in sql:
            raise RuntimeError("base indisponible")
        return _Db(FERMEES, []).query(sql, params)

    m.ctx.db.query = casse
    t = m._cumul()
    assert "Depuis le depart" in t
