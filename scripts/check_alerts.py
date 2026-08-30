# ============================================================
# 🔔 Price Alerts -- VERIFICATION (tourne en cron toutes les 15 min)
# Pour chaque zone active : récupère le prix actuel du ticker, et
# déclenche si le prix est DANS la zone, OU si le prix a franchi la
# zone d'un coup entre deux vérifications (gap plus rapide que le
# cron). Une fois déclenchée, la zone se désactive automatiquement
# (comportement demandé : une seule alerte par zone).
# ============================================================
import yfinance as yf

from alerts_common import (
    load_alerts, save_alerts, load_last_prices, save_last_prices, envoyer_telegram,
)

alerts = load_alerts()
active = [a for a in alerts if a['active']]

if not active:
    print("Aucune zone active -- rien à vérifier.")
    raise SystemExit(0)

tickers = sorted(set(a['ticker'] for a in active))
print(f"Vérification de {len(active)} zone(s) sur {len(tickers)} ticker(s) : {', '.join(tickers)}")

raw = yf.download(tickers, period='2d', interval='5m', group_by='column',
                   auto_adjust=True, progress=False)

current_prices = {}
for t in tickers:
    try:
        if len(tickers) == 1:
            s = raw['Close'].dropna()
        else:
            s = raw['Close'][t].dropna()
        if len(s) > 0:
            current_prices[t] = float(s.iloc[-1])
    except Exception as e:
        print(f"   ⚠️ {t}: impossible de récupérer le prix ({e})")

last_prices = load_last_prices()
n_triggered = 0

for a in active:
    t = a['ticker']
    cur = current_prices.get(t)
    if cur is None:
        continue
    lo, hi = a['level'] - a['tolerance'], a['level'] + a['tolerance']
    touched = lo <= cur <= hi
    crossed = False
    last = last_prices.get(t)
    if not touched and last is not None:
        lo_path, hi_path = min(last, cur), max(last, cur)
        crossed = not (hi_path < lo or lo_path > hi)  # chevauchement = franchissement
    if touched or crossed:
        a['active'] = False
        a['triggered_price'] = round(cur, 6)
        from alerts_common import now_iso
        a['triggered_at'] = now_iso()
        n_triggered += 1
        moyen = "prix dans la zone" if touched else "zone franchie entre 2 vérifications"
        msg = (f"🔔 <b>Alerte prix</b>\n{t} a touché ta zone {a['level']} (±{a['tolerance']})\n"
               f"Prix actuel : {cur:.6g}  ({moyen})\n"
               + (f"Note : {a['note']}\n" if a['note'] else '')
               + "Cette zone est maintenant désactivée.")
        envoyer_telegram(msg)
        print(f"   🔔 DÉCLENCHÉE #{a['id']} {t} @ {a['level']} (prix {cur:.6g}, {moyen})")

for t, p in current_prices.items():
    last_prices[t] = p

save_alerts(alerts)
save_last_prices(last_prices)

print(f"\n{n_triggered} zone(s) déclenchée(s) sur ce run. {sum(1 for a in alerts if a['active'])} zone(s) encore active(s).")
