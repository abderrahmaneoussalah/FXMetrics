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
    is_within_active_week, write_summary, now_iso,
)

if not is_within_active_week():
    print("⏸️ Week-end (heure de Paris) -- marchés fermés, rien à vérifier.")
    write_summary("⏸️ **Week-end (heure de Paris)** — aucune vérification effectuée.")
    raise SystemExit(0)

alerts = load_alerts()
active = [a for a in alerts if a['active']]

if not active:
    print("Aucune zone active -- rien à vérifier.")
    write_summary("ℹ️ Aucune zone active — rien à vérifier.")
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
triggered_this_run = []

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
        a['triggered_at'] = now_iso()
        n_triggered += 1
        moyen = "prix dans la zone" if touched else "zone franchie entre 2 vérifications"
        label = a.get('label', t)
        msg = (f"🔔 <b>Alerte prix</b>\n{label} ({t}) a touché ta zone {a['level']} (±{a['tolerance']})\n"
               f"Prix actuel : {cur:.6g}  ({moyen})\n"
               + (f"Note : {a['note']}\n" if a['note'] else '')
               + "Cette zone est maintenant désactivée.")
        envoyer_telegram(msg)
        print(f"   🔔 DÉCLENCHÉE #{a['id']} {label} ({t}) @ {a['level']} (prix {cur:.6g}, {moyen})")
        triggered_this_run.append(a)

for t, p in current_prices.items():
    last_prices[t] = p

save_alerts(alerts)
save_last_prices(last_prices)

print(f"\n{n_triggered} zone(s) déclenchée(s) sur ce run. {sum(1 for a in alerts if a['active'])} zone(s) encore active(s).")

if triggered_this_run:
    lines = [f"## 🔔 {n_triggered} zone(s) déclenchée(s)", "", "| Instrument | Niveau | Prix | Note |", "|---|---|---|---|"]
    for a in triggered_this_run:
        lines.append(f"| {a.get('label', a['ticker'])} | {a['level']} | {a['triggered_price']} | {a.get('note','')} |")
    write_summary("\n".join(lines))
else:
    write_summary(f"✅ Vérifié {len(active)} zone(s) — aucun déclenchement. {sum(1 for a in alerts if a['active'])} zone(s) encore active(s).")
