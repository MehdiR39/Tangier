#!/bin/bash
# Surveillance des processus de recherche : une ligne par probleme, un point de controle par heure.
#
# POURQUOI DANS LE DEPOT. Les deux tests papier de la regle G+D doivent tourner ~13 jours sans
# interruption ; un `docker restart` les tue tous. Ce script vivait dans un dossier temporaire de
# session, donc il disparaissait avec la session. Les commandes de relance sont dans
# data/recherche/INVENTAIRE.md § 5.
#
# Usage : bash intel/research/surveillance.sh
# Chaque ligne emise est un evenement : ALERTE (a traiter), INFO, ou CONTROLE (toutes les heures).

R=${R:-/c/Users/Osiris/Documents/Tangier/data/recherche}
CONTENEUR=${CONTENEUR:-tangier-intel}
dernier_ok=0
prev_v1=-1
prev_dec=-1

compter() {   # compte les tickets pris dans une base de test papier G+D
  MSYS_NO_PATHCONV=1 docker exec "$CONTENEUR" python -c "
import sqlite3, sys
try:
    c = sqlite3.connect('file:$1?mode=ro', uri=True)
    print(c.execute(\"SELECT COUNT(*) FROM decision WHERE pris=1\").fetchone()[0])
except Exception:
    print('?')" 2>/dev/null
}

while true; do
  procs=$(MSYS_NO_PATHCONV=1 docker exec "$CONTENEUR" sh -c 'for p in /proc/[0-9]*; do tr "\0" " " < $p/cmdline 2>/dev/null; echo; done' 2>/dev/null)
  if [ -z "$procs" ]; then
    echo "ALERTE $(date +%H:%M) conteneur $CONTENEUR injoignable"
  else
    for nom in "intel run" "intel.research.papier_combo" "intel.research.detenteurs" "intel.research.coffre --boucle" "intel.research.v1_enregistreur"; do
      echo "$procs" | grep -q "python -m $nom" || echo "ALERTE $(date +%H:%M) processus arrete : $nom"
    done
    # Les deux tests G+D : il en faut EXACTEMENT deux, un par age de decision. Zero = le test est mort
    # et les jours accumules sont perdus ; trois = une instance fantome ecrit dans la base d une autre
    # (c est arrive le 16/09). On ancre sur « ^python » : sinon on compterait aussi les enveloppes
    # `sh -c ...`, il y en a une par test, et ca ferait une fausse alerte toutes les dix minutes.
    n_gd=$(echo "$procs" | grep -c "^python -m intel.research.papier_gd_direct")
    [ "$n_gd" -ne 2 ] && echo "ALERTE $(date +%H:%M) tests G+D : $n_gd instance(s) au lieu de 2"
  fi
  v1=$(cat $R/v1_avant/*.jsonl 2>/dev/null | wc -l)
  err=$(cat $R/v1_avant/*.jsonl 2>/dev/null | grep -c '"erreur"')
  heure=$(date +%H%M)
  if [ "$v1" -gt 0 ] && [ "$err" -gt $((v1 / 5)) ]; then
    echo "ALERTE $(date +%H:%M) enregistreur v1 : $err erreurs sur $v1 pools"
  fi
  if [ "$prev_v1" -ge 0 ] && [ "$v1" -eq "$prev_v1" ]; then fige_v1=$((fige_v1 + 1)); else fige_v1=0; fi
  if [ "$heure" -ge 0030 ] && [ "$heure" -lt 2300 ] && [ "${fige_v1:-0}" -ge 3 ]; then
    echo "ALERTE $(date +%H:%M) enregistreur v1 : aucun nouveau pool en 30 min ($v1 au total)"
    fige_v1=0
  fi
  grep -q "plafond" $R/v1_enregistreur.log 2>/dev/null && echo "INFO $(date +%H:%M) enregistreur v1 : plafond de credits atteint (en pause)" && sed -i 's/plafond/PLAFOND-VU/' $R/v1_enregistreur.log
  dec=$(MSYS_NO_PATHCONV=1 docker exec "$CONTENEUR" python -c "
import sqlite3
c = sqlite3.connect('file:/app/db/papier_combo.sqlite?mode=ro', uri=True)
print(c.execute('SELECT COUNT(*) FROM decision').fetchone()[0])" 2>/dev/null)
  if [ -n "$dec" ] && [ "$prev_dec" -ge 0 ] && [ "$dec" -eq "$prev_dec" ]; then fige_dec=$((fige_dec + 1)); else fige_dec=0; fi
  if [ "${fige_dec:-0}" -ge 3 ]; then
    echo "ALERTE $(date +%H:%M) test papier : aucune nouvelle decision en 30 min ($dec)"
    fige_dec=0
  fi
  age_coffre=$(( $(date +%s) - $(stat -c %Y $R/coffre.log 2>/dev/null || echo 0) ))
  [ "$age_coffre" -gt 7800 ] && echo "ALERTE $(date +%H:%M) coffre : pas de passage depuis $((age_coffre / 60)) min"

  # CHIEN DE GARDE. Le 16/09 au soir, deux coupures d internet ont tue l ecoute des creations de
  # pool ; au retour du reseau elle ne s est PAS reconnectee toute seule -- les boucles tournaient,
  # le conteneur resolvait les noms, mais plus un seul lancement n arrivait, et les deux tests ont
  # cesse de juger pendant une heure. Il a fallu un redemarrage a la main. Si ca se produit la nuit,
  # on perd la nuit. Ici on le detecte et on repare : uniquement si le reseau est REVENU (sinon
  # redemarrer ne sert a rien), et au plus une fois par demi-heure.
  dernier_lancement=$(MSYS_NO_PATHCONV=1 docker exec "$CONTENEUR" python -c "
import sqlite3, time
c = sqlite3.connect('file:/app/db/intel.sqlite?mode=ro', uri=True)
print(int(time.time() - (c.execute('SELECT MAX(ts) FROM solana_stream_launches').fetchone()[0] or 0)))" 2>/dev/null)
  if [ -n "$dernier_lancement" ] && [ "$dernier_lancement" -gt 900 ] \
     && [ $(( $(date +%s) - ${dernier_soin:-0} )) -gt 1800 ]; then
    if MSYS_NO_PATHCONV=1 docker exec "$CONTENEUR" python -c "
import socket; socket.create_connection(('mainnet.helius-rpc.com', 443), timeout=8).close()" 2>/dev/null; then
      echo "ALERTE $(date +%H:%M) aucun lancement depuis $((dernier_lancement / 60)) min alors que le reseau repond : redemarrage du moteur"
      MSYS_NO_PATHCONV=1 docker restart "$CONTENEUR" >/dev/null 2>&1
      sleep 20
      for c in "intel.research.detenteurs >> /app/db/detenteurs.log" \
               "intel.research.coffre --boucle >> /app/data/recherche/coffre.log" \
               "intel.research.papier_combo >> /app/db/papier_combo.log" \
               "intel.research.v1_enregistreur >> /app/data/recherche/v1_enregistreur.log"; do
        MSYS_NO_PATHCONV=1 docker exec -d "$CONTENEUR" sh -c "cd /app && python -m $c 2>&1"
      done
      MSYS_NO_PATHCONV=1 docker exec -d "$CONTENEUR" sh -c "cd /app && PAPIER_GD_AGE=45 python -m intel.research.papier_gd_direct >> /app/db/papier_gd.log 2>&1"
      MSYS_NO_PATHCONV=1 docker exec -d "$CONTENEUR" sh -c "cd /app && PAPIER_GD_AGE=30 PAPIER_GD_DB=/app/db/papier_gd30.sqlite python -m intel.research.papier_gd_direct >> /app/db/papier_gd30.log 2>&1"
      dernier_soin=$(date +%s)
      echo "INFO $(date +%H:%M) moteur redemarre et six processus de recherche relances"
    else
      echo "INFO $(date +%H:%M) aucun lancement depuis $((dernier_lancement / 60)) min, mais le reseau ne repond pas : on attend son retour"
    fi
  fi
  maintenant=$(date +%s)
  if [ $((maintenant - dernier_ok)) -ge 3600 ]; then
    a=$(compter /app/db/papier_gd.sqlite)
    b=$(compter /app/db/papier_gd30.sqlite)
    echo "CONTROLE $(date +%H:%M) processus ok · pools v1 $v1 (erreurs $err) · decisions combo $dec · tickets G+D : 45 s = $a / 300, 30 s = $b / 300"
    dernier_ok=$maintenant
  fi
  prev_v1=$v1
  prev_dec=${dec:--1}
  sleep 600
done
