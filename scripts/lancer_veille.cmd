@echo off
REM ---------------------------------------------------------------------------
REM Lance la veille auto-reparatrice (intel/research/veille_repare.sh).
REM
REM POURQUOI CE FICHIER. Le 21/09 j ai annonce a Mido « la veille est armee »
REM alors qu elle ne tournait pas : corrigee et commitee, jamais relancee. Et
REM meme relancee a la main elle serait morte au redemarrage du PC de 06:48 le
REM 22/09 -- le defaut qu on venait de corriger pour Streamlit et que je n avais
REM pas applique ici.
REM
REM LE VERROU EST UN FICHIER, PAS UNE RECHERCHE DANS LES LIGNES DE COMMANDE.
REM Premiere version : `wmic process ... | find "veille_repare"`. Elle comptait
REM mes PROPRES commandes de diagnostic, qui contiennent ce mot -- donc elle
REM concluait « deja en cours » et ne lancait jamais rien. Un verrou de fichier
REM ne peut pas se tromper de cible.
REM
REM CE QU ELLE A LE DROIT DE FAIRE : redemarrer le conteneur, relancer les
REM collecteurs. Elle ne touche JAMAIS le mode, la mise ni le modele.
REM ---------------------------------------------------------------------------
cd /d "%~dp0.."
if not exist logs mkdir logs

REM Le verrou est un DOSSIER : sa creation est atomique sous Windows, contrairement
REM a « tester puis creer un fichier », qui laisse passer deux lancements simultanes.
mkdir logs\veille.lock 2>nul
if errorlevel 1 (
  echo [%date% %time%] verrou present, une veille tourne deja >> logs\veille.log
  exit /b 0
)

echo [%date% %time%] demarrage de la veille >> logs\veille.log
"C:\Program Files\Git\bin\bash.exe" intel/research/veille_repare.sh >> logs\veille.log 2>&1
echo [%date% %time%] veille terminee (code %errorlevel%) >> logs\veille.log

REM Le verrou tombe a la sortie, quelle qu en soit la raison : la tache planifiee
REM pourra donc la relancer au prochain passage de 30 minutes.
rmdir logs\veille.lock 2>nul
