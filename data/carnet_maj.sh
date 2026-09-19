#!/bin/sh
# Rafraichit les donnees de la page de suivi « Carnet Tangier ».
#
# UNE SEULE SOURCE : on relance `table_std2.py`, exactement la table que Mido lit dans le terminal,
# avec sa sortie JSON. La page ne recalcule rien -- sinon deux vues du meme chiffre finiraient par
# diverger et il faudrait deviner laquelle croire.
#
# Produit `data/carnet_doc.json`, le document a ecrire dans la base de l artefact
# (collection « suivi », document « table »), champ `charge` = la table serialisee.
set -e
RACINE="$(cd "$(dirname "$0")/.." && pwd)"
MISE="${MISE:-25}"

docker exec tangier-intel sh -c "cd /app && MISE=$MISE JSON=/tmp/table.json python data/table_std2.py > /tmp/table.txt 2>&1"
docker exec tangier-intel python -c "
import json
d = json.load(open('/tmp/table.json', encoding='utf-8'))
json.dump({'charge': json.dumps(d, ensure_ascii=False, separators=(',',':')), 'genere': d['genere']},
          open('/tmp/doc.json', 'w', encoding='utf-8'), ensure_ascii=False)
print(d['genere'], '·', len(d['lignes']), 'lignes ·', d['cout_pt'], 'pt · mise', d['mise'])
"
docker cp tangier-intel:/tmp/doc.json "$RACINE/data/carnet_doc.json" > /dev/null
echo "pret : $RACINE/data/carnet_doc.json"
