# ============================================================
# 🔔 Price Alerts -- AJOUTER UNE ZONE
# Paramètres (fournis par le formulaire du workflow) :
#   ALERT_TICKER    envoyé par le menu déroulant, ex: "EUR/USD (EURUSD=X)"
#   ALERT_LEVEL     ex: 1.0850
#   ALERT_TOLERANCE ex: 0.001   (optionnel, défaut = 0.1% du niveau)
#   ALERT_NOTE      ex: "Résistance hebdo"
# ============================================================
import os
import re

from alerts_common import load_alerts, save_alerts, next_id, now_iso, write_summary

raw_choice = os.environ.get('ALERT_TICKER', '').strip()
level_raw = os.environ.get('ALERT_LEVEL', '').strip()
tol_raw = os.environ.get('ALERT_TOLERANCE', '').strip()
note = os.environ.get('ALERT_NOTE', '').strip()

if not raw_choice:
    raise SystemExit("❌ Ticker manquant.")

# Le menu déroulant envoie "Label (TICKER)" -> on extrait juste le ticker.
m = re.search(r'\(([^)]+)\)\s*$', raw_choice)
ticker = m.group(1).strip() if m else raw_choice
label = raw_choice.split(' (')[0].strip() if m else raw_choice

try:
    level = float(level_raw)
    assert level > 0
except Exception:
    raise SystemExit(f"❌ Niveau de prix invalide : '{level_raw}'. Donne un nombre, ex: 1.0850")

if tol_raw:
    try:
        tolerance = float(tol_raw)
    except Exception:
        raise SystemExit(f"❌ Tolérance invalide : '{tol_raw}'. Donne un nombre, ex: 0.001")
else:
    tolerance = round(level * 0.001, 6)  # 0.1% par défaut

alerts = load_alerts()
alert = {
    'id': next_id(alerts),
    'ticker': ticker,
    'label': label,
    'level': level,
    'tolerance': tolerance,
    'note': note,
    'active': True,
    'created_at': now_iso(),
    'triggered_at': None,
    'triggered_price': None,
}
alerts.append(alert)
save_alerts(alerts)

print(f"✅ Zone #{alert['id']} créée : {label} ({ticker}) @ {level} (±{tolerance})" + (f' — {note}' if note else ''))
print(f"   Se déclenchera si le prix entre dans [{level - tolerance:.6g} ; {level + tolerance:.6g}]")
print(f"\n📋 Zones actives ({sum(1 for a in alerts if a['active'])}) :")
for a in alerts:
    if a['active']:
        print(f"   #{a['id']:<4} {a.get('label', a['ticker']):<12} @ {a['level']:<10} ±{a['tolerance']:<8} {a['note']}")

active = [a for a in alerts if a['active']]
lines = [f"## ✅ Zone #{alert['id']} créée", f"**{label}** ({ticker}) @ {level} (±{tolerance})" + (f" — {note}" if note else ""),
         "", f"### Zones actives ({len(active)})", "| ID | Instrument | Niveau | Tolérance | Note |", "|---|---|---|---|---|"]
for a in active:
    lines.append(f"| **{a['id']}** | {a.get('label', a['ticker'])} | {a['level']} | ±{a['tolerance']} | {a.get('note','')} |")
write_summary("\n".join(lines))
