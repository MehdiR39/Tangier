@echo off
REM ---------------------------------------------------------------------------
REM Lance le tableau de bord Streamlit (data/carnet_app.py) sur le port 8502.
REM
REM POURQUOI CE FICHIER EXISTE. Le 21/09 a 20h10 le PC a redemarre. Les conteneurs
REM Docker sont revenus seuls (politique `unless-stopped`) ; l app Streamlit, non --
REM rien ne la relancait, et Mido s est retrouve sans tableau de bord sans le savoir.
REM « il faut qu elle se relance toute seule apres redemarrage ».
REM
REM Appele par la tache planifiee « Tangier - carnet Streamlit » (a l ouverture de
REM session). Peut aussi se lancer a la main : scripts\lancer_carnet.cmd
REM
REM NE PAS transformer en `start /b` : la tache planifiee doit garder le processus
REM comme enfant, sinon Windows considere la tache terminee et le redemarrage
REM automatique en cas d echec ne se declenche jamais.
REM ---------------------------------------------------------------------------
cd /d "%~dp0.."

REM Si quelqu un ecoute deja sur 8502, ne rien faire : une seconde instance ne
REM pourrait pas se lier au port et mourrait en boucle.
netstat -ano | findstr /C:":8502" | findstr /C:"LISTENING" >nul
if %errorlevel%==0 (
  echo [%date% %time%] deja en ecoute sur 8502, on ne relance pas >> logs\streamlit_carnet.log
  exit /b 0
)

if not exist logs mkdir logs
echo [%date% %time%] demarrage du carnet Streamlit >> logs\streamlit_carnet.log

"C:\Users\Osiris\miniconda3\envs\qrt\python.exe" -m streamlit run data/carnet_app.py ^
  --server.port 8502 ^
  --server.address 0.0.0.0 ^
  --server.headless true ^
  --browser.gatherUsageStats false ^
  >> logs\streamlit_carnet.log 2>> logs\streamlit_carnet.log.err
