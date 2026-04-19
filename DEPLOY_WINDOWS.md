# Déploiement mini PC Windows — Daily Stock Signals

Ce guide déploie le scanner quotidien sur un mini PC Windows, avec exécution
automatique chaque matin ouvré à 13h00 Paris (~8h ET, pré-marché US).

---

## 0) Prérequis à installer sur le mini PC

### Git for Windows
→ https://git-scm.com/download/win
Installer avec options par défaut. Vérifie :
```powershell
git --version
```

### Docker Desktop
→ https://www.docker.com/products/docker-desktop/
Pendant l'installation :
- ✅ Cocher "Use WSL 2 instead of Hyper-V" (recommandé)
- Après installation, lancer Docker Desktop une fois et l'autoriser à démarrer au boot

Vérifie :
```powershell
docker --version
docker compose version
```

---

## 1) Cloner le projet

Ouvrir **PowerShell** (admin pas obligatoire) :

```powershell
cd C:\
git clone https://github.com/MehdiR39/Tangier.git tangier_L
cd C:\tangier_L
```

Tu dois avoir le contenu du projet dans `C:\tangier_L`.

---

## 2) Créer le fichier `.env` (jamais versionné sur GitHub)

Depuis le Mac, copier le contenu de `.env` (transfert USB, AirDrop via
application tierce, ou copier-coller le texte).

Sur le mini PC, dans `C:\tangier_L\` créer un fichier `.env` avec :

```env
BINANCE_API_KEY=xxxxxxxxxxxxxxxx
BINANCE_API_SECRET=xxxxxxxxxxxxxxxx
TELEGRAM_BOT_TOKEN=xxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=xxxxxxxxxxxxxxxx
```

> ⚠️ **Jamais** push ce fichier sur GitHub.
> Le `.gitignore` le bloque mais fais attention aux copies.

---

## 3) Build de l'image Docker

Premier build (installe Python 3.11 + toutes les deps, ~5 min) :

```powershell
cd C:\tangier_L
docker compose build
```

Vérifier :
```powershell
docker images | findstr tangier-bot
```

---

## 4) Test manuel — dry-run

Envoyer un message test **sans** passer par Telegram (affichage console) :

```powershell
docker compose run --rm daily-signals `
    python daily_signals.py --universe config --top 5 --min-quality 30 --dry-run
```

Tu dois voir un message formaté dans la console. Si ça marche, passe au vrai test.

---

## 5) Test manuel — envoi live Telegram

```powershell
docker compose run --rm daily-signals
```

Cette commande lance `daily_signals.py` avec les args par défaut du
`docker-compose.yml` (S&P 500, top 20, quality ≥ 60%, liquid only).

Tu dois recevoir le message sur **ton Telegram**.

---

## 6) Test du script PowerShell

Le script PowerShell ajoute la gestion des logs. Vérifier qu'il tourne :

```powershell
cd C:\tangier_L
.\scripts\run_daily_signals.ps1
```

Si erreur "execution policy", exécuter **une fois** :
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Vérifier le log :
```powershell
Get-Content C:\tangier_L\logs\daily_$(Get-Date -Format "yyyy-MM-dd").log
```

---

## 7) Activer l'exécution automatique (Task Scheduler)

### Import du fichier XML

1. Ouvrir **Task Scheduler** (Planificateur de tâches) → clic droit sur
   "Task Scheduler Library" → **Import Task**
2. Sélectionner `C:\tangier_L\scripts\daily_signals_task.xml`
3. Dans la fenêtre qui s'ouvre :
   - Onglet **General** → cocher "Run whether user is logged on or not"
     (pour que ça tourne même si tu es déco)
   - Entrer ton mot de passe Windows quand demandé
4. Cliquer OK

### Vérification

Dans Task Scheduler → tu dois voir la tâche `Tangier\DailySignals`.

Pour tester sans attendre 13h :
- Clic droit sur la tâche → **Run**
- Vérifier `C:\tangier_L\logs\daily_XXXX.log`

---

## 8) Configuration du mini PC pour H24

Pour que la tâche tourne **même la nuit** :

- Paramètres Windows → Système → Alimentation et batterie
  → **Mode de gestion d'alimentation** : toujours "branché sur secteur"
  → **Veille** : Jamais
- Si l'écran peut s'éteindre, pas grave. Le PC reste actif.

Pour que Docker Desktop se lance automatiquement :
- Paramètres Docker Desktop → **Start Docker Desktop when you log in**

---

## 9) Monitoring quotidien

### Vérifier les logs

```powershell
cd C:\tangier_L\logs
Get-ChildItem daily_*.log | Sort-Object LastWriteTime -Descending | Select-Object -First 5
```

### Voir le dernier signal envoyé

```powershell
Get-Content results/signal_history.csv -Tail 10
```

### Historique Telegram

Les messages sont dans ton chat Telegram avec le bot. Remonte les jours
précédents pour comparer.

---

## 10) Mise à jour du code

Quand tu fais des améliorations sur le Mac :

**Sur le Mac :**
```bash
git add .
git commit -m "description des changements"
git push origin main
```

**Sur le mini PC :**
```powershell
cd C:\tangier_L
git pull origin main
docker compose build    # si requirements.txt a changé
```

La prochaine exécution de la tâche utilisera le nouveau code.

---

## 11) Debugging

### "Docker daemon not running"
→ Lancer Docker Desktop manuellement, attendre le icône "running" dans le tray.

### "Task Scheduler completed with exit code -1"
→ Vérifier le log dans `C:\tangier_L\logs\`. Le plus souvent :
- Docker Desktop pas démarré
- `.env` manquant ou mauvais token Telegram
- Perte réseau (check `Get-NetConnectionProfile`)

### "Telegram message not received"
→ Tester manuellement en dry-run. Puis tester sans dry-run.
→ Vérifier que `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` dans `.env` sont corrects.

### "Model retrain takes too long"
→ Normal, ~5-8 min pour S&P 500 complet. Si tu veux accélérer :
  - Passer `--universe config` (30 tickers, 15s)
  - Le modèle est sauvegardé entre les runs, pas besoin de retrain chaque jour
  - Prévoir un retrain hebdomadaire (ex: lundi matin uniquement) en modifiant la tâche

---

## 12) Setup retrain hebdomadaire (optionnel)

Pour retrainer le modèle seulement le **lundi** (et scan rapide sinon) :

1. Modifier `docker-compose.yml` pour retirer le retrain du service daily (déjà OK par défaut — le scanner charge le modèle sauvegardé sauf `--retrain`).
2. Créer une 2ème tâche Task Scheduler pour le retrain Lundi 12h30 :

```powershell
docker compose run --rm daily-signals `
    python daily_signals.py --retrain --universe sp500 --dry-run
```

(`--dry-run` pour ne pas envoyer le message, le vrai run à 13h utilisera le nouveau modèle.)

---

## Résumé des fichiers importants

| Fichier | Rôle |
|---|---|
| `C:\tangier_L\.env` | Clés API (Telegram, Binance) — **NE PAS PARTAGER** |
| `C:\tangier_L\docker-compose.yml` | Services Docker |
| `C:\tangier_L\scripts\run_daily_signals.ps1` | Runner PowerShell |
| `C:\tangier_L\scripts\daily_signals_task.xml` | Config Task Scheduler |
| `C:\tangier_L\logs\daily_*.log` | Logs quotidiens |
| `C:\tangier_L\results\signal_history.csv` | Historique des signaux envoyés |
| `C:\tangier_L\models\SCANNER_GLOBAL_lgbm_model.pkl` | Modèle entraîné (retrain si besoin) |
