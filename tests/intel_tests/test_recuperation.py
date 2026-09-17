"""La recuperation des cautions : elle ne doit JAMAIS pouvoir faire disparaitre un jeton.

Ce module signe des transactions. Les tests portent donc d abord sur ce qu il refuse de faire, et
seulement ensuite sur ce qu il fait : un compte a solde non nul, un jeton d une position ouverte,
un compte vu vide il y a trente secondes -- trois cas ou fermer coute de l argent ou casse un achat.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from intel.engines.recuperation import CAUTION_SOL, FERMER_APRES_S, PROGRAMMES, Recuperation

SPL = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
PROPRIO = "8Lp7Q4bWrEHbqJ1H5t2pZ6xVqgP3n9YkS4mA1cRfTuvW"
MINT_A = "So11111111111111111111111111111111111111112"
MINT_B = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


class _Reponse:
    def __init__(self, charge):
        self._c = charge

    def json(self):
        return self._c


class _Client:
    """Rejoue des reponses RPC et retient ce qui a ete envoye."""

    def __init__(self, comptes, blockhash="11111111111111111111111111111111"):
        self.comptes, self.blockhash, self.envois = comptes, blockhash, []

    async def post(self, url, json=None, timeout=None):  # noqa: A002
        m = (json or {}).get("method")
        if m == "getTokenAccountsByOwner":
            prog = json["params"][1]["programId"]
            return _Reponse({"result": {"value": self.comptes.get(prog, [])}})
        if m == "getLatestBlockhash":
            return _Reponse({"result": {"value": {"blockhash": self.blockhash}}})
        self.envois.append(json)
        return _Reponse({"result": "SIGNATURE"})


class _Db:
    def __init__(self, ouverts):
        self._o = ouverts

    def query(self, sql, params=()):
        return [{"token_address": m} for m in self._o]


class _Ctx:
    def __init__(self, cfg, ouverts=()):
        self._cfg = cfg
        self.db = _Db(ouverts)

    @property
    def config(self):
        return self

    def get(self, cle, defaut=None):
        return self._cfg.get(cle, defaut)


def _compte(pubkey, mint, montant):
    return {"pubkey": pubkey,
            "account": {"data": {"parsed": {"info": {
                "mint": mint, "tokenAmount": {"amount": str(montant)}}}}}}


def _moteur(comptes, cfg=None, ouverts=(), client=None):
    base = {"recuperation.enabled": True, "solana.rpc_url": "http://rpc",
            "execution.mode": "paper"}
    base.update(cfg or {})
    cl = client or _Client(comptes)
    return Recuperation(_Ctx(base, ouverts), cl), cl


def test_desactive_par_defaut(monkeypatch):
    """Comme tout ce qui signe dans ce projet : il faut l allumer expressement."""
    m, cl = _moteur({SPL: [_compte("C1", MINT_A, 0)]}, cfg={"recuperation.enabled": False})
    monkeypatch.setattr("intel.execution.solana.signer_address", lambda *a, **k: PROPRIO)
    asyncio.run(m.cycle())
    assert cl.envois == []


def test_un_compte_non_vide_n_est_jamais_retenu(monkeypatch):
    """La seule garantie qui compte : aucun jeton ne peut disparaitre."""
    monkeypatch.setattr("intel.execution.solana.signer_address", lambda *a, **k: PROPRIO)
    m, cl = _moteur({SPL: [_compte("C1", MINT_A, 1), _compte("C2", MINT_B, 10 ** 9)]})
    vides = asyncio.run(m._comptes_vides(cl, "http://rpc", PROPRIO))
    assert vides == []


def test_un_jeton_en_position_ouverte_est_epargne(monkeypatch):
    """Un achat en vol cree un compte a solde nul pendant quelques secondes : le fermer ferait
    echouer l achat."""
    monkeypatch.setattr("intel.execution.solana.signer_address", lambda *a, **k: PROPRIO)
    m, cl = _moteur({SPL: [_compte("C1", MINT_A, 0)]}, ouverts=(MINT_A,))
    m._vus["C1"] = 0.0                                  # vu vide il y a tres longtemps
    asyncio.run(m.cycle())
    assert cl.envois == []


def test_un_compte_vu_vide_a_l_instant_attend(monkeypatch):
    monkeypatch.setattr("intel.execution.solana.signer_address", lambda *a, **k: PROPRIO)
    m, cl = _moteur({SPL: [_compte("C1", MINT_A, 0)]}, cfg={"execution.mode": "live"})
    asyncio.run(m.cycle())                              # premier passage : on ne fait que le noter
    assert cl.envois == []
    assert "C1" in m._vus


def test_en_papier_rien_n_est_signe(monkeypatch):
    monkeypatch.setattr("intel.execution.solana.signer_address", lambda *a, **k: PROPRIO)
    appels = []
    monkeypatch.setattr("intel.execution.solana.sign", lambda *a, **k: appels.append(a) or "SIGNE")
    m, cl = _moteur({SPL: [_compte("C1", MINT_A, 0)]})
    m._vus["C1"] = 0.0
    asyncio.run(m.cycle())
    assert appels == [] and cl.envois == []


def test_l_instruction_est_bien_un_close_account():
    """Discriminant 9, trois comptes, et le proprietaire est le SEUL signataire. Une erreur ici
    enverrait des jetons ailleurs au lieu de rendre une caution."""
    m, _ = _moteur({})
    i = m._instruction_fermer("11111111111111111111111111111112", SPL, PROPRIO)
    assert bytes(i.data) == bytes([9])
    assert str(i.program_id) == SPL
    assert len(i.accounts) == 3
    compte, vers, proprio = i.accounts
    assert compte.is_writable and not compte.is_signer          # le compte ferme
    assert vers.is_writable and not vers.is_signer              # ou va la caution
    assert proprio.is_signer and not proprio.is_writable        # celui qui autorise
    assert str(vers.pubkey) == str(proprio.pubkey) == PROPRIO   # la caution revient chez nous


def test_les_deux_programmes_de_jetons_sont_couverts():
    """Token-2022 existe et cree aussi des comptes a caution ; l oublier laisserait la moitie
    de l argent dehors le jour ou un jeton l utilise."""
    assert PROGRAMMES == {SPL, "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"}


def test_la_caution_est_celle_de_solana():
    assert CAUTION_SOL == pytest.approx(0.00203928)
    assert FERMER_APRES_S >= 600            # au moins dix minutes de recul avant de fermer
