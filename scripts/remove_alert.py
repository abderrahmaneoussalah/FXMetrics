# ============================================================
# 🔔 Price Alerts -- SUPPRIMER UNE ZONE (avant qu'elle se déclenche)
# Paramètre : ALERT_ID (l'id affiché par list_alerts ou add_alert,
# le nombre après le #, ex: "1" pour la zone #1)
# ============================================================
import os

from alerts_common import load_alerts, save_alerts, write_summary

id_raw = os.environ.get('ALERT_ID', '').strip()
alerts = load_alerts()
active = [a for a in alerts if a['active']]


def show_active(reason):
    print(reason)
    print(f"\n📋 Zones actives actuelles ({len(active)}) :")
    if not active:
        print("   (aucune)")
    for a in active:
        print(f"   #{a['id']:<4} {a.get('label', a['ticker']):<12} @ {a['level']:<10} ±{a['tolerance']:<8} {a.get('note','')}")
    lines = [f"## ⚠️ {reason}", "", f"### Zones actives actuelles ({len(active)})"]
    if active:
        lines += ["| ID | Instrument | Niveau | Note |", "|---|---|---|---|"]
        for a in active:
            lines.append(f"| **{a['id']}** | {a.get('label', a['ticker'])} | {a['level']} | {a.get('note','')} |")
    else:
        lines.append("_(aucune -- rien à supprimer)_")
    write_summary("\n".join(lines))


try:
    target_id = int(id_raw)
except Exception:
    show_active(f"Id invalide : '{id_raw}'. Donne juste le numéro (ex: 1), sans le #.")
    raise SystemExit(1)

match = next((a for a in alerts if a['id'] == target_id), None)
if not match:
    show_active(f"Aucune zone active avec l'id #{target_id}.")
    raise SystemExit(1)

alerts = [a for a in alerts if a['id'] != target_id]
save_alerts(alerts)
label = match.get('label', match['ticker'])
print(f"🗑️ Zone #{target_id} supprimée : {label} @ {match['level']} — {match.get('note','')}")

remaining = [a for a in alerts if a['active']]
lines = [f"## 🗑️ Zone #{target_id} supprimée", f"{label} @ {match['level']} — {match.get('note','')}",
         "", f"### Zones actives restantes ({len(remaining)})"]
if remaining:
    lines += ["| ID | Instrument | Niveau | Note |", "|---|---|---|---|"]
    for a in remaining:
        lines.append(f"| **{a['id']}** | {a.get('label', a['ticker'])} | {a['level']} | {a.get('note','')} |")
else:
    lines.append("_(aucune)_")
write_summary("\n".join(lines))
