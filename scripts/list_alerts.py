# ============================================================
# 🔔 Price Alerts -- LISTER LES ZONES (lecture seule)
# ============================================================
from alerts_common import load_alerts

alerts = load_alerts()
active = [a for a in alerts if a['active']]
done = [a for a in alerts if not a['active']]

print(f"🟢 ZONES ACTIVES ({len(active)})")
if not active:
    print("   (aucune)")
for a in active:
    print(f"   #{a['id']:<4} {a['ticker']:<12} @ {a['level']:<10} ±{a['tolerance']:<8} créée {a['created_at']:<20} {a.get('note','')}")

print(f"\n✅ ZONES DÉCLENCHÉES ({len(done)})")
if not done:
    print("   (aucune)")
for a in done:
    print(f"   #{a['id']:<4} {a['ticker']:<12} @ {a['level']:<10} touché à {a.get('triggered_price','?')} le {a.get('triggered_at','?')} {a.get('note','')}")
