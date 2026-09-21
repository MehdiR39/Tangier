#!/bin/sh
# VEILLE DE NUIT QUI REPARE, 20->21/09. Mido : « s il y a un probleme tu le resous, je vais pas me
# reveiller ».
#
# CE QU ELLE FAIT : elle repare, et elle ne sort -- donc ne me reveille -- que si une reparation
# ECHOUE, ou si la meme panne revient trois fois. Une panne qui revient sans cesse n est pas une
# panne a redemarrer, c est une panne a comprendre.
#
# CE QU ELLE NE TOUCHE JAMAIS : le mode du moteur, la mise, le modele. Remettre en reel ou en
# papier est une decision de Mido, pas une reparation.
#
# ATTENTION -- LA GARANTIE D ORIGINE EST TOMBEE. Cette veille a ete ecrite le 20/09 au soir alors
# que le moteur etait en PAPIER, et elle disait « aucune reparation ne peut couter un euro ». Le
# moteur est en REEL depuis le 21/09 09h56 : un redemarrage interrompt desormais de vrais ordres.
# Toute sonde ajoutee ici doit donc savoir dire « tout va bien » -- une sonde qui ne le sait pas
# redemarre en boucle. C est exactement ce qui est arrive le 21/09 (voir le bloc « le moteur »).
RACINE=/c/Users/Osiris/Documents/Tangier
MIN_COLLECTEURS=19
AGE_MAX_CARNET=1500
MAX_REPARATIONS=3          # au-dela, on arrete de rustiner et on reveille

r_conteneur=0; r_gardien=0; r_collecteurs=0; r_page=0; r_moteur=0; r_carnet=0
echo "veille demarree $(date '+%H:%M') -- elle repare, elle ne reveille qu en cas d echec"

abandon() { echo "ALERTE $(date '+%H:%M') · $1"; exit 1; }
note()    { echo "$(date '+%H:%M') repare : $1"; }

collecteurs() {
  docker exec tangier-intel python -c "
import os
n=g=0
for p in os.listdir('/proc'):
    if not p.isdigit(): continue
    try: c=open('/proc/%s/cmdline'%p).read().replace(chr(0),' ')
    except OSError: continue
    if '-m intel.research.' in c and 'sh -c' not in c:
        n+=1
        if 'gardien' in c: g+=1
print(n, g)
" 2>/dev/null
}

while true; do
  # --- le conteneur
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^tangier-intel$'; then
    r_conteneur=$((r_conteneur+1))
    [ $r_conteneur -gt $MAX_REPARATIONS ] && abandon "le conteneur retombe sans arret ($r_conteneur fois)"
    docker start tangier-intel >/dev/null 2>&1
    note "conteneur redemarre ($r_conteneur)"
    sleep 60
    docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^tangier-intel$' \
      || abandon "le conteneur refuse de redemarrer"
  fi

  N=$(collecteurs)
  if [ -z "$N" ]; then
    sleep 60; N=$(collecteurs)
    [ -n "$N" ] || abandon "le conteneur ne repond plus aux commandes"
  fi
  NB=$(echo "$N" | cut -d' ' -f1); GA=$(echo "$N" | cut -d' ' -f2)

  # --- le gardien : c est lui qui relance les collecteurs, donc il passe en premier
  if [ "$GA" -lt 1 ] 2>/dev/null; then
    r_gardien=$((r_gardien+1))
    [ $r_gardien -gt $MAX_REPARATIONS ] && abandon "le gardien meurt sans arret ($r_gardien fois)"
    docker exec -d tangier-intel sh -c "cd /app && python -u -m intel.research.gardien >> /app/logs/gardien.log 2>&1"
    note "gardien relance ($r_gardien)"
    sleep 90
  fi

  # --- les collecteurs : le gardien les reprend seul, on lui laisse deux tours avant d insister
  if [ "$NB" -lt "$MIN_COLLECTEURS" ] 2>/dev/null; then
    sleep 150
    NB=$(collecteurs | cut -d' ' -f1)
    if [ "$NB" -lt "$MIN_COLLECTEURS" ] 2>/dev/null; then
      r_collecteurs=$((r_collecteurs+1))
      [ $r_collecteurs -gt $MAX_REPARATIONS ] && abandon "$NB collecteurs seulement, le gardien n y arrive pas"
      docker exec tangier-intel python -c "
import os, signal
for p in os.listdir('/proc'):
    if not p.isdigit(): continue
    try: c=open('/proc/%s/cmdline'%p).read().replace(chr(0),' ')
    except OSError: continue
    if 'intel.research.gardien' in c and 'python -c' not in c: os.kill(int(p), signal.SIGTERM)
" >/dev/null 2>&1
      note "gardien reveille pour reprendre les collecteurs manquants ($r_collecteurs)"
      sleep 120
    fi
  fi

  # --- la page
  if [ -f "$RACINE/data/carnet.json" ]; then
    AGE=$(( $(date +%s) - $(stat -c %Y "$RACINE/data/carnet.json") ))
    if [ "$AGE" -ge "$AGE_MAX_CARNET" ]; then
      r_page=$((r_page+1))
      [ $r_page -gt $MAX_REPARATIONS ] && abandon "la page reste figee malgre $r_page relances"
      docker exec tangier-intel python -c "
import os, signal
for p in os.listdir('/proc'):
    if not p.isdigit(): continue
    try: c=open('/proc/%s/cmdline'%p).read().replace(chr(0),' ')
    except OSError: continue
    if 'intel.research.carnet_json' in c and 'python -c' not in c: os.kill(int(p), signal.SIGTERM)
" >/dev/null 2>&1
      note "carnet_json relance, page figee depuis $((AGE/60)) min ($r_page)"
      sleep 180
    fi
  fi

  # --- le moteur : s il ne decide plus, seul le conteneur peut le relancer.
  #
  # ON NE LIT PLUS `docker logs --since`. Sur cette installation il rend ZERO ligne quelle que soit
  # la forme -- `10m`, `600s`, horodatage RFC3339 -- alors que `--tail 100` en rend cent. Le test
  # `! docker logs --since 10m | grep -q ...` etait donc TOUJOURS vrai, et cette veille a redemarre
  # QUATRE FOIS un moteur en REEL parfaitement sain, le 21/09 entre 10h27 et 10h58, avant
  # d abandonner. Une sonde qui ne sait pas dire « tout va bien » ne repare pas, elle casse.
  #
  # ON LIT MAINTENANT UN FAIT EN BASE, et on le lit CONTRE LE FLUX : un marche calme donne peu de
  # decisions sans que rien ne soit casse (le 21/09 au matin, 28 lancements/h contre 55 la nuit,
  # et les decisions suivaient). Le moteur n est declare en panne que s il n a RIEN decide alors
  # que des pools SONT nes -- sinon on accuse le moteur de la tranquillite du marche.
  ETAT=$(docker exec tangier-intel python -c "
import sqlite3, time
c = sqlite3.connect('file:/app/db/intel.sqlite?mode=ro', uri=True, timeout=30)
n = time.time()
print(c.execute('SELECT COUNT(*) FROM mr_lignes WHERE t_dec >= ?', (n-1800,)).fetchone()[0],
      c.execute('SELECT COUNT(*) FROM solana_stream_launches WHERE ts >= ?', (n-1800,)).fetchone()[0])
" 2>/dev/null)
  D=$(echo "$ETAT" | cut -d' ' -f1); L=$(echo "$ETAT" | cut -d' ' -f2)
  if [ -n "$D" ] && [ "$D" -eq 0 ] 2>/dev/null && [ "$L" -ge 5 ] 2>/dev/null \
     && [ $(( $(date +%s) - ${dernier_soin_moteur:-0} )) -gt 3600 ]; then
    # AU PLUS UN REDEMARRAGE PAR HEURE. Le moteur est en REEL depuis le 21/09 09h56 : un
    # redemarrage n est plus gratuit, il interrompt des ordres. L en-tete de cette veille promettait
    # « aucune reparation ne peut couter un euro » parce qu elle a ete ecrite quand le moteur etait
    # en papier ; cette promesse est tombee, la prudence doit monter d autant.
    r_moteur=$((r_moteur+1))
    [ $r_moteur -gt $MAX_REPARATIONS ] && abandon "le moteur ne decide plus malgre $r_moteur redemarrages ($L lancements, 0 decision)"
    docker restart tangier-intel >/dev/null 2>&1
    dernier_soin_moteur=$(date +%s)
    note "conteneur redemarre : 0 decision en 30 min alors que $L pools sont nes ($r_moteur)"
    sleep 180
  fi

  # --- un carnet qui plante sur une table a moitie ecrite : processus vivant, travail en echec.
  # L ecriture est atomique depuis ce soir, donc ca ne devrait plus arriver -- si ca revient,
  # c est que la correction ne suffit pas, et ca merite un reveil plutot qu une rustine.
  T=$(docker exec tangier-intel sh -c "grep -c 'truncated' /app/logs/*.log 2>/dev/null | awk -F: '{s+=\$2} END {print s+0}'" 2>/dev/null)
  if [ -n "$T" ] && [ "$T" -gt 2 ] 2>/dev/null; then
    r_carnet=$((r_carnet+1))
    [ $r_carnet -gt 1 ] && abandon "PICKLE TRONQUE a nouveau ($T) malgre l ecriture atomique -- a comprendre, pas a rustiner"
    note "pickle tronque detecte ($T), carnets relances une fois ($r_carnet)"
    docker exec tangier-intel python -c "
import os, signal
C=('foret_gel','foret_gel75','foret_marche','foret75_carnet','foret_gagnant','foret75_iso','prod_reentraine')
for p in os.listdir('/proc'):
    if not p.isdigit(): continue
    try: c=open('/proc/%s/cmdline'%p).read().replace(chr(0),' ')
    except OSError: continue
    if 'python -c' in c: continue
    for n in C:
        if 'intel.research.%s' % n in c: os.kill(int(p), signal.SIGTERM); break
" >/dev/null 2>&1
    sleep 180
  fi

  sleep 300
done
