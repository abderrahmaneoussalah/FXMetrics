# ============================================================
# 🔔 Price Alerts -- AJOUTER UNE ZONE
# Paramètres (fournis par le formulaire du workflow) :
#   ALERT_TICKER    ex: EURUSD=X, AAPL, BTC-USD, GC=F
#   ALERT_LEVEL     ex: 1.0850
#   ALERT_TOLERANCE ex: 0.001   (optionnel, défaut = 0.1% du niveau)
#   ALERT_NOTE      ex: "Résistance hebdo"
# ============================================================
import os

from alerts_common import load_alerts, save_alerts, next_id, now_iso

ticker = os.environ.get('ALERT_TICKER', '').strip()
level_raw = os.environ.get('ALERT_LEVEL', '').strip()
tol_raw = os.environ.get('ALERT_TOLERANCE', '').strip()
note = os.environ.get('ALERT_NOTE', '').strip()

if not ticker:
    raise SystemExit("❌ Ticker manquant. Exemples : EURUSD=X (forex), AAPL (action), BTC-USD (crypto), GC=F (or futures).")

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

print(f"✅ Zone #{alert['id']} créée : {ticker} @ {level} (±{tolerance})" + (f' — {note}' if note else ''))
print(f"   Se déclenchera si le prix entre dans [{level - tolerance:.6g} ; {level + tolerance:.6g}]")
print(f"\n📋 Zones actives ({sum(1 for a in alerts if a['active'])}) :")
for a in alerts:
    if a['active']:
        print(f"   #{a['id']:<4} {a['ticker']:<12} @ {a['level']:<10} ±{a['tolerance']:<8} {a['note']}")
