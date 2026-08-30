# ============================================================
# 🔔 Price Alerts -- SUPPRIMER UNE ZONE (avant qu'elle se déclenche)
# Paramètre : ALERT_ID (l'id affiché par list_alerts ou add_alert)
# ============================================================
import os

from alerts_common import load_alerts, save_alerts

id_raw = os.environ.get('ALERT_ID', '').strip()
try:
    target_id = int(id_raw)
except Exception:
    raise SystemExit(f"❌ Id invalide : '{id_raw}'. Regarde la liste (workflow list_alerts) pour le bon numéro.")

alerts = load_alerts()
match = next((a for a in alerts if a['id'] == target_id), None)

if not match:
    raise SystemExit(f"❌ Aucune zone avec l'id #{target_id}.")

alerts = [a for a in alerts if a['id'] != target_id]
save_alerts(alerts)
print(f"🗑️ Zone #{target_id} supprimée : {match['ticker']} @ {match['level']} — {match.get('note','')}")
