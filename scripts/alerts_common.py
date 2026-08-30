# ============================================================
# 🔔 Price Alerts — Module commun
# Stockage des zones (data/alerts.json), état des derniers prix
# vus (data/last_prices.json, pour détecter un franchissement
# rapide entre deux vérifications), et envoi Telegram.
# ============================================================
import os
import json
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DATA_DIR = Path(os.environ.get('ALERTS_DATA_DIR', 'data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)

ALERTS_PATH = DATA_DIR / 'alerts.json'
LAST_PRICES_PATH = DATA_DIR / 'last_prices.json'

TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TG_CHAT = os.environ.get('TELEGRAM_CHAT_ID')

PARIS_TZ = ZoneInfo('Europe/Paris')


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def load_alerts():
    if ALERTS_PATH.exists():
        with open(ALERTS_PATH) as f:
            return json.load(f)
    return []


def save_alerts(alerts):
    with open(ALERTS_PATH, 'w') as f:
        json.dump(alerts, f, indent=2, ensure_ascii=False)


def load_last_prices():
    if LAST_PRICES_PATH.exists():
        with open(LAST_PRICES_PATH) as f:
            return json.load(f)
    return {}


def save_last_prices(prices):
    with open(LAST_PRICES_PATH, 'w') as f:
        json.dump(prices, f, indent=2)


def next_id(alerts):
    if not alerts:
        return 1
    return max(a['id'] for a in alerts) + 1


def envoyer_telegram(msg):
    if not TG_TOKEN or not TG_CHAT:
        print('   ℹ️ Telegram non configuré (secrets absents) — message :')
        print('   ' + msg.replace('\n', '\n   '))
        return
    import requests
    try:
        requests.post(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                      data={'chat_id': TG_CHAT, 'text': msg, 'parse_mode': 'HTML'}, timeout=10)
    except Exception as e:
        print(f'   Telegram KO: {e}')


def is_within_active_week():
    """Lundi 00:00 -> samedi 00:00, heure de Paris. Utilise la vraie base de
    fuseaux horaires (zoneinfo), qui gère automatiquement le passage
    heure d'été / heure d'hiver -- aucun ajustement manuel du cron requis."""
    now_paris = datetime.now(PARIS_TZ)
    return now_paris.weekday() < 5  # 0=lundi ... 4=vendredi, 5=samedi, 6=dimanche


def write_summary(md_text):
    """Écrit dans le résumé du run GitHub Actions (visible directement sur la
    page du run, sans avoir besoin d'ouvrir les logs d'un job)."""
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if not path:
        return
    with open(path, 'a', encoding='utf-8') as f:
        f.write(md_text + '\n')
