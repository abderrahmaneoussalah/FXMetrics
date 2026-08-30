# ============================================================
# 🔔 Price Alerts -- LISTER LES ZONES (lecture seule)
# ============================================================
from alerts_common import load_alerts, write_summary

alerts = load_alerts()
active = [a for a in alerts if a['active']]
done = [a for a in alerts if not a['active']]

print(f"🟢 ZONES ACTIVES ({len(active)})")
if not active:
    print("   (aucune)")
for a in active:
    label = a.get('label', a['ticker'])
    print(f"   #{a['id']:<4} {label:<12} ({a['ticker']}) @ {a['level']:<10} ±{a['tolerance']:<8} créée {a['created_at']:<20} {a.get('note','')}")

print(f"\n✅ ZONES DÉCLENCHÉES ({len(done)})")
if not done:
    print("   (aucune)")
for a in done:
    label = a.get('label', a['ticker'])
    print(f"   #{a['id']:<4} {label:<12} ({a['ticker']}) @ {a['level']:<10} touché à {a.get('triggered_price','?')} le {a.get('triggered_at','?')} {a.get('note','')}")

# ── Résumé visible directement sur la page du run, sans ouvrir les logs ──
lines = [f"## 🟢 Zones actives ({len(active)})"]
if active:
    lines += ["| ID | Instrument | Niveau | Tolérance | Note | Créée le |", "|---|---|---|---|---|---|"]
    for a in active:
        lines.append(f"| **{a['id']}** | {a.get('label', a['ticker'])} | {a['level']} | ±{a['tolerance']} | {a.get('note','')} | {a['created_at']} |")
else:
    lines.append("_(aucune)_")

lines += ["", f"## ✅ Zones déclenchées ({len(done)})"]
if done:
    lines += ["| ID | Instrument | Niveau | Prix au déclenchement | Déclenchée le | Note |", "|---|---|---|---|---|---|"]
    for a in done:
        lines.append(f"| {a['id']} | {a.get('label', a['ticker'])} | {a['level']} | {a.get('triggered_price','?')} | {a.get('triggered_at','?')} | {a.get('note','')} |")
else:
    lines.append("_(aucune)_")

write_summary("\n".join(lines))
