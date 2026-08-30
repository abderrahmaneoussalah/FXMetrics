# 🔔 Price Alerts — à ajouter dans le repo FXmetrics existant

Ce zip ne contient QUE les fichiers à ajouter — rien n'écrase ton FXmetrics actuel (noms de fichiers différents partout).

## Ce que tu obtiens une fois ajouté
- 5 nouveaux scripts dans `scripts/` (en plus de `fxmetrics.py`, qui reste intact)
- 4 nouveaux workflows dans `.github/workflows/` (en plus de `run.yml`, qui reste intact)
- Aucune modification de `requirements.txt` nécessaire (yfinance + requests sont déjà dedans)

## Étapes

1. **Dézippe** ce fichier, en révélant bien les fichiers cachés sur ton ordinateur (Windows : Affichage > Éléments masqués / Mac : ⌘+Shift+.) — sinon `.github` ne sera pas visible pour l'upload.

2. Sur GitHub, dans ton repo **FXMetrics** existant :
   - Va dans le dossier `scripts/`, clique **Add file → Upload files**, glisse les 5 fichiers `.py` (`alerts_common.py`, `add_alert.py`, `remove_alert.py`, `list_alerts.py`, `check_alerts.py`). Commit.
   - Retourne à la racine, va dans `.github/workflows/`, **Add file → Upload files**, glisse les 4 fichiers `.yml`. Commit.
   
   (Si l'upload direct dans un sous-dossier ne te propose pas le bon chemin, upload à la racine puis renomme chaque fichier — même technique que pour `.github/workflows/run.yml` la dernière fois.)

3. **Ajoute 2 nouveaux secrets** (Settings → Secrets and variables → Actions → New repository secret) :
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   
   (Rien à toucher aux secrets FRED/NEWS/Twelve Data déjà en place — ils continuent à servir uniquement à `fxmetrics.py`.)

4. C'est tout — pas de nouveau repo, pas de nouvelle activation Pages. Utilise les 4 nouveaux workflows dans l'onglet Actions exactement comme décrit précédemment :
   - **1 - Ajouter une zone d'alerte**
   - **2 - Supprimer une zone d'alerte**
   - **3 - Lister les zones**
   - **4 - Vérifier les zones (auto)** — tourne toutes les 15 min

⚠️ Rappel sur les minutes Actions : comme FXmetrics est déjà **public**, ce cron toutes les 15 min ne coûte rien (Actions gratuites et illimitées sur repo public). C'est justement pour ça que fusionner dans ce repo plutôt que d'en garder un privé séparé est une bonne idée ici.

Les fichiers `data/alerts.json` et `data/last_prices.json` seront créés automatiquement au premier `Run workflow`, à côté de `data/signals_log.csv` — ils ne se marchent pas dessus.
