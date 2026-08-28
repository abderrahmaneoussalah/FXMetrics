# # 📊 FXmetrics — GitHub Actions + Pages

Conversion du notebook `FXmetrics_V7` en une GitHub Action qui génère un dashboard HTML (forex + indices + matières premières) et sauvegarde automatiquement l'historique des signaux.

## Ce qui a changé vs le notebook

- Plus de Google Colab : les clés API (optionnelles) se configurent en secrets GitHub, pas en secrets Colab.
- La page HTML est publiée dans `docs/index.html` → GitHub Pages sert cette page automatiquement à une URL stable.
- L'ancienne "Cellule 5" (saisie manuelle de la paire tradée) a été remplacée par une **sauvegarde automatique** : à chaque run, tous les signaux actionnables (BUY/SELL) du jour — sur les 3 classes d'actifs — sont ajoutés à `data/signals_log.csv` (date, prix d'entrée, SL, TP1, TP2, score, conviction, etc.). C'est un historique des signaux suggérés, pas un suivi de trades réellement pris.

## 1. Créer le repo

```bash
git init
git add .
git commit -m "FXmetrics - GitHub Actions"
git branch -M main
git remote add origin https://github.com/<toi>/<ton-repo>.git
git push -u origin main
```

Le repo peut être public ou privé — la page HTML montre des signaux calculés automatiquement, pas de données personnelles sensibles.

## 2. Autoriser le workflow à committer

Settings → Actions → General → **Workflow permissions** → coche **"Read and write permissions"** → Save.

## 3. Activer GitHub Pages

Settings → Pages → **Source** : `Deploy from a branch` → Branch : `main` → Dossier : `/docs` → Save.

Après le premier run, ta page sera disponible à `https://<toi>.github.io/<ton-repo>/`.

## 4. Secrets (tous optionnels)

Sans clé API, le script tourne entièrement sur yfinance (gratuit, pas de compte à créer) — c'est un bon point de départ.

| Secret | Effet si absent |
|---|---|
| `TWELVE_DATA_KEY` | Bascule automatique sur yfinance pour les prix (qualité légèrement moindre) |
| `FRED_API_KEY` | Les rendements obligataires US (carry trade) ne sont pas affichés |
| `NEWS_API_KEY` | Pas d'actualités contextuelles dans le dashboard |

Settings → Secrets and variables → Actions → New repository secret.

## 5. Lancer

Onglet **Actions** → **FXmetrics - Génération du dashboard** → **Run workflow**.

Chaque run :
1. télécharge les données (forex, indices, métaux/énergie),
2. calcule les signaux et génère `docs/index.html`,
3. ajoute les signaux BUY/SELL du jour à `data/signals_log.csv`,
4. commit et push les deux automatiquement.

## 6. Automatiser (optionnel)

Le workflow est en déclenchement manuel pour l'instant. Pour le faire tourner tout seul, ouvre `.github/workflows/run.yml` et décommente les 2 lignes `schedule` / `cron` en haut du fichier (déjà présentes, juste commentées) — par défaut réglées sur 07h00 UTC du lundi au vendredi, à ajuster selon tes horaires de trading préférés.

## Consulter l'historique des signaux

`data/signals_log.csv` s'enrichit à chaque run et reste dans le repo — tu peux l'ouvrir directement sur GitHub, le télécharger, ou l'importer dans Excel/Google Sheets pour analyser tes signaux dans le temps.
