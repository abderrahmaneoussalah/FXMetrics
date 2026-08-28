# ╔══════════════════════════════════════════════════════════╗
# ║  FXmetrics V7 — mémoire des chocs · zones · vent macro                ║
# ║  Cellule 1/5 : Installation + Configuration              ║
# ║                                                          ║
# ║  WORKFLOW : Exécution → Tout exécuter → 1 page HTML     ║
# ╚══════════════════════════════════════════════════════════╝
# Dépendances installées via requirements.txt (workflow CI), pas de !pip install ici
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, requests, json, time, os
from datetime import datetime, timedelta
from pathlib import Path

# ═══════════════ CONFIGURATION ═══════════════
CAPITAL          = 10_000     # Capital de référence (paper trading)
RISK_PER_TRADE   = 0.005      # 0.5% de risque par trade (sizing)
ATR_MULT_SL      = 1.5
ATR_MULT_TP1     = 2.0
ATR_MULT_TP2     = 3.5
CAPITAL_PAPER    = CAPITAL    # compat journal

USE_TWELVE_DATA  = False      # False = tout yfinance. Passe à True seulement si tes symboles
                              # Twelve Data fonctionnent (le header affiche "TD x/13" à chaque run).
                              # À 0/3, les tentatives coûtent ~25 s pour rien.
TD_PAUSE_SEC     = 8.5        # Pause entre appels Twelve Data (plan gratuit = 8 req/min)

DATA_DIR = Path(os.environ.get("FXMETRICS_DATA_DIR", "data"))
DOCS_DIR = Path(os.environ.get("FXMETRICS_DOCS_DIR", "docs"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR.mkdir(parents=True, exist_ok=True)
JOURNAL_FILE = DATA_DIR / "signals_log.csv"

# ── Clés API (GitHub Secrets → variables d'environnement) ──
TWELVE_KEY = os.environ.get("TWELVE_DATA_KEY") or None
FRED_KEY   = os.environ.get("FRED_API_KEY") or None
NEWS_KEY   = os.environ.get("NEWS_API_KEY") or None
if TWELVE_KEY or FRED_KEY or NEWS_KEY:
    print("✅ Clés API chargées depuis les variables d'environnement (GitHub Secrets)")
else:
    print("⚠️ Aucune clé API définie en secret — yfinance seul (qualité moindre)")

# Conteneur global des résultats (rempli par les cellules suivantes)
RESULTS  = {}      # données/calculs par section
FRAGMENTS = {}     # fragments HTML par section

print(f"✅ Config : capital {CAPITAL:,}$ · risque/trade {RISK_PER_TRADE*100:.1f}% · "
      f"SL {ATR_MULT_SL}×ATR · TP {ATR_MULT_TP1}/{ATR_MULT_TP2}×ATR")
print(f"   Journal : {JOURNAL_FILE}")
print(f"   Twelve Data : {'activé (pause '+str(TD_PAUSE_SEC)+'s anti rate-limit)' if USE_TWELVE_DATA and TWELVE_KEY else 'désactivé → yfinance'}")

# ╔══════════════════════════════════════════════════════════╗
# ║  Cellule 2/5 : MOTEUR FOREX — V7                         ║
# ║  Univers 24 paires · signaux (logique inchangée)         ║
# ║  + taux directeurs AUTO (BIS→FRED→table) · COT (CFTC)    ║
# ║  + accord momentum 1m/3m/12m · maturité · anti-liq       ║
# ╚══════════════════════════════════════════════════════════╝

FX_PAIRS = {
    # ── G10 Majeures ─────────────────────────────────────────
    "EURUSD": {"ticker":"EURUSD=X","label":"EUR/USD","pip":0.0001,"cat":"G10_Major",
               "currencies":("EUR","USD"),"em":False,
               "sens":{"DXY":-1.0,"VIX":-0.3,"WTI":0.1,"GOLD":0.3}},
    "GBPUSD": {"ticker":"GBPUSD=X","label":"GBP/USD","pip":0.0001,"cat":"G10_Major",
               "currencies":("GBP","USD"),"em":False,
               "sens":{"DXY":-0.9,"VIX":-0.4,"WTI":0.1,"GOLD":0.2}},
    "USDJPY": {"ticker":"JPY=X",   "label":"USD/JPY","pip":0.01,  "cat":"G10_SafeHaven",
               "currencies":("USD","JPY"),"em":False,
               "sens":{"DXY":0.8,"VIX":-0.8,"WTI":0.1,"GOLD":-0.4}},
    "AUDUSD": {"ticker":"AUDUSD=X","label":"AUD/USD","pip":0.0001,"cat":"G10_Commodity",
               "currencies":("AUD","USD"),"em":False,
               "sens":{"DXY":-0.7,"VIX":-0.7,"WTI":0.4,"GOLD":0.6}},
    "USDCAD": {"ticker":"CAD=X",   "label":"USD/CAD","pip":0.0001,"cat":"G10_Commodity",
               "currencies":("USD","CAD"),"em":False,
               "sens":{"DXY":0.7,"VIX":0.3,"WTI":-0.8,"GOLD":-0.2}},
    "USDCHF": {"ticker":"CHF=X",   "label":"USD/CHF","pip":0.0001,"cat":"G10_SafeHaven",
               "currencies":("USD","CHF"),"em":False,
               "sens":{"DXY":0.8,"VIX":-0.6,"WTI":0.1,"GOLD":-0.5}},
    "USDNOK": {"ticker":"NOK=X",   "label":"USD/NOK","pip":0.0001,"cat":"G10_Commodity",
               "currencies":("USD","NOK"),"em":False,
               "sens":{"DXY":0.6,"VIX":0.4,"WTI":-0.9,"GOLD":-0.1}},
    "NZDUSD": {"ticker":"NZDUSD=X","label":"NZD/USD","pip":0.0001,"cat":"G10_Commodity",
               "currencies":("NZD","USD"),"em":False,
               "sens":{"DXY":-0.7,"VIX":-0.6,"WTI":0.3,"GOLD":0.5}},
    # ── G10 Crosses ──────────────────────────────────────────
    "EURGBP": {"ticker":"EURGBP=X","label":"EUR/GBP","pip":0.0001,"cat":"G10_Cross",
               "currencies":("EUR","GBP"),"em":False,
               "sens":{"DXY":-0.1,"VIX":0.1,"WTI":-0.1,"GOLD":0.1}},
    "EURJPY": {"ticker":"EURJPY=X","label":"EUR/JPY","pip":0.01,  "cat":"G10_Cross",
               "currencies":("EUR","JPY"),"em":False,
               "sens":{"DXY":-0.2,"VIX":-0.6,"WTI":0.1,"GOLD":0.1}},
    "GBPJPY": {"ticker":"GBPJPY=X","label":"GBP/JPY","pip":0.01,  "cat":"G10_Cross",
               "currencies":("GBP","JPY"),"em":False,
               "sens":{"DXY":-0.2,"VIX":-0.7,"WTI":0.1,"GOLD":0.0}},
    "AUDJPY": {"ticker":"AUDJPY=X","label":"AUD/JPY","pip":0.01,  "cat":"G10_Cross",
               "currencies":("AUD","JPY"),"em":False,
               "sens":{"DXY":-0.3,"VIX":-0.8,"WTI":0.3,"GOLD":0.3}},
    "AUDNZD": {"ticker":"AUDNZD=X","label":"AUD/NZD","pip":0.0001,"cat":"G10_Cross",
               "currencies":("AUD","NZD"),"em":False,
               "sens":{"DXY":-0.1,"VIX":-0.3,"WTI":0.2,"GOLD":0.2}},
    "EURCHF": {"ticker":"EURCHF=X","label":"EUR/CHF","pip":0.0001,"cat":"G10_Cross",
               "currencies":("EUR","CHF"),"em":False,
               "sens":{"DXY":0.0,"VIX":-0.4,"WTI":0.0,"GOLD":-0.3}},
    "EURCAD": {"ticker":"EURCAD=X","label":"EUR/CAD","pip":0.0001,"cat":"G10_Cross",
               "currencies":("EUR","CAD"),"em":False,
               "sens":{"DXY":-0.3,"VIX":-0.2,"WTI":-0.6,"GOLD":0.2}},
    "GBPCAD": {"ticker":"GBPCAD=X","label":"GBP/CAD","pip":0.0001,"cat":"G10_Cross",
               "currencies":("GBP","CAD"),"em":False,
               "sens":{"DXY":-0.3,"VIX":-0.3,"WTI":-0.5,"GOLD":0.1}},
    # ── EM (script original v2.1) ─────────────────────────────
    "USDMXN": {"ticker":"USDMXN=X","label":"USD/MXN","pip":0.0001,"cat":"EM_LatAm",
               "currencies":("USD","MXN"),"em":True,
               "sens":{"DXY":0.8,"VIX":0.7,"WTI":-0.6,"GOLD":-0.1}},
    "USDBRL": {"ticker":"USDBRL=X","label":"USD/BRL","pip":0.0001,"cat":"EM_LatAm",
               "currencies":("USD","BRL"),"em":True,
               "sens":{"DXY":0.7,"VIX":0.8,"WTI":-0.5,"GOLD":-0.2}},
    "USDZAR": {"ticker":"USDZAR=X","label":"USD/ZAR","pip":0.0001,"cat":"EM_Africa",
               "currencies":("USD","ZAR"),"em":True,
               "sens":{"DXY":0.7,"VIX":0.8,"WTI":-0.3,"GOLD":-0.7}},
    "USDSEK": {"ticker":"USDSEK=X","label":"USD/SEK","pip":0.0001,"cat":"EM_Scandi",
               "currencies":("USD","SEK"),"em":False,
               "sens":{"DXY":0.7,"VIX":0.5,"WTI":-0.2,"GOLD":-0.1}},
    "USDSGD": {"ticker":"USDSGD=X","label":"USD/SGD","pip":0.0001,"cat":"EM_Asia",
               "currencies":("USD","SGD"),"em":True,
               "sens":{"DXY":0.6,"VIX":0.4,"WTI":-0.1,"GOLD":-0.1}},
    "USDPLN": {"ticker":"USDPLN=X","label":"USD/PLN","pip":0.0001,"cat":"EM_Europe",
               "currencies":("USD","PLN"),"em":True,
               "sens":{"DXY":0.7,"VIX":0.7,"WTI":-0.2,"GOLD":-0.1}},
    "USDINR": {"ticker":"USDINR=X","label":"USD/INR","pip":0.01,  "cat":"EM_Asia",
               "currencies":("USD","INR"),"em":True,
               "sens":{"DXY":0.6,"VIX":0.5,"WTI":0.3,"GOLD":-0.1}},
    "USDHUF": {"ticker":"USDHUF=X","label":"USD/HUF","pip":0.01,  "cat":"EM_Europe",
               "currencies":("USD","HUF"),"em":True,
               "sens":{"DXY":0.7,"VIX":0.8,"WTI":-0.2,"GOLD":-0.1}},
}

MACRO_TICKERS = {"DXY":"DX-Y.NYB","VIX":"^VIX","GOLD":"GC=F","WTI":"CL=F"}

# Taux directeurs actuels — mettre à jour manuellement après chaque réunion BC
# ═══════════════ V6 : TAUX DIRECTEURS AUTO (BIS → FRED → table locale) ═══════════════
# À chaque lancement : taux du jour depuis la BIS (API publique, sans clé),
# secours FRED pour USD/EUR, table locale vérifiée en dernier recours.
# → le score carry (logique inchangée) tourne sur des données FRAÎCHES.

CURRENT_RATES_FALLBACK = {   # vérifiés manuellement le 02/08/2026
    "USD":3.75,"EUR":2.25,"GBP":3.75,"JPY":1.00,
    "AUD":4.35,"CAD":2.25,"CHF":0.00,"NOK":4.25,
    "NZD":2.50,"SEK":1.75,"MXN":6.50,"BRL":14.25,
    "ZAR":7.00,"SGD":1.00,"PLN":3.75,"INR":5.25,"HUF":5.75,
}
FALLBACK_DATE = "2026-08-02"
BIS_CODES = {"USD":"US","EUR":"XM","GBP":"GB","JPY":"JP","AUD":"AU","CAD":"CA",
             "CHF":"CH","NOK":"NO","NZD":"NZ","SEK":"SE","MXN":"MX","BRL":"BR",
             "ZAR":"ZA","PLN":"PL","INR":"IN","HUF":"HU"}

def _parse_bis_sdmx(js):
    """Parseur SDMX-JSON BIS tolérant (v1 'series' ou v2 observations à plat)."""
    try:
        data = js.get("data", js)
        struct = data.get("structure") or (data.get("structures") or [{}])[0]
        dims = struct["dimensions"]["observation"]
        dates = [v["id"] for v in dims[-1]["values"]]
        dset = data["dataSets"][0]
        if "series" in dset and dset["series"]:
            obs = dset["series"][list(dset["series"].keys())[0]]["observations"]
        else:
            obs = dset.get("observations", {})
        pts = []
        for k, v in obs.items():
            i = int(str(k).split(":")[-1])
            if v and v[0] is not None and i < len(dates):
                pts.append((dates[i], float(v[0])))
        pts.sort(key=lambda x: x[0])
        return pts
    except Exception:
        return []

def _parse_bis_csv(text):
    """Parseur CSV SDMX v2 : colonnes TIME_PERIOD / OBS_VALUE (matching partiel)."""
    try:
        import io
        df = pd.read_csv(io.StringIO(text))
        tcol = next((c for c in df.columns if "TIME_PERIOD" in c.upper()), None)
        vcol = next((c for c in df.columns if "OBS_VALUE" in c.upper()), None)
        if not tcol or not vcol: return []
        df = df[[tcol, vcol]].dropna()
        pts = [(str(t)[:10], float(v)) for t, v in zip(df[tcol], df[vcol])]
        pts.sort(key=lambda x: x[0])
        return pts
    except Exception:
        return []

def fetch_bis_rates(days=730):
    """Tous les taux directeurs. Cascade : API v2 CSV (actuelle) → v2 JSON → v1 (legacy).
       Imprime un diagnostic si tout échoue (pour debug au prochain run)."""
    rates, history, n_ok, last_date, diag = {}, {}, 0, "", None
    for ccy, code in BIS_CODES.items():
        pts = []
        attempts = [
            (f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.{code}"
             f"?lastNObservations={days}&format=csv", "csv"),
            (f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.{code}"
             f"?lastNObservations={days}&format=json", "json"),
            (f"https://stats.bis.org/api/v1/data/WS_CBPOL_D/D.{code}/all"
             f"?lastNObservations={days}&detail=dataonly&format=sdmx-json", "json"),
        ]
        for url, kind in attempts:
            try:
                r = requests.get(url, timeout=12)
                if getattr(r, "status_code", 200) != 200:
                    if diag is None: diag = f"HTTP {r.status_code} sur ...{url[26:86]}"
                    continue
                pts = _parse_bis_csv(r.text) if kind == "csv" else _parse_bis_sdmx(r.json())
                if pts: break
                if diag is None: diag = f"réponse vide/illisible sur ...{url[26:86]}"
            except Exception as e:
                if diag is None: diag = f"{type(e).__name__} sur ...{url[26:86]}"
                continue
        if pts:
            rates[ccy] = round(pts[-1][1], 2)
            history[ccy] = pts
            n_ok += 1
            last_date = max(last_date, pts[-1][0])
    if n_ok == 0 and diag:
        print(f"   🔍 BIS diagnostic : {diag}")
    return rates, history, n_ok, last_date

def fetch_fred_rate(series):
    if not FRED_KEY: return None
    try:
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": series, "api_key": FRED_KEY,
                                 "file_type": "json", "sort_order": "desc", "limit": 5},
                         timeout=10)
        for o in r.json().get("observations", []):
            if o.get("value") not in (".", "", None):
                return round(float(o["value"]), 2)
    except Exception:
        pass
    return None

def build_rates():
    """Cascade BIS → FRED (USD/EUR) → table locale. SGD toujours manuel (MAS ne fixe pas de taux)."""
    rates = dict(CURRENT_RATES_FALLBACK)
    history = {}
    meta = {"source": f"table locale ({FALLBACK_DATE})", "auto": 0, "obs": FALLBACK_DATE}
    try:
        bis, hist, n_ok, obs = fetch_bis_rates()
        if n_ok >= 8:
            rates.update(bis)
            history = hist
            meta = {"source": "BIS (auto)", "auto": n_ok, "obs": obs}
            print(f"   ✅ Taux directeurs BIS : {n_ok}/16 devises · dernière obs. {obs}")
        else:
            raise RuntimeError("BIS insuffisant")
    except Exception:
        fed = fetch_fred_rate("DFF"); ecb = fetch_fred_rate("ECBDFR")
        if fed: rates["USD"] = fed; meta["auto"] += 1
        if ecb: rates["EUR"] = ecb; meta["auto"] += 1
        if meta["auto"]:
            meta["source"] = f"FRED partiel + table locale ({FALLBACK_DATE})"
            print(f"   ⚠️ BIS indisponible → FRED : USD {rates['USD']}%, EUR {rates['EUR']}% · reste = table locale")
        else:
            print(f"   ⚠️ BIS et FRED indisponibles → table locale du {FALLBACK_DATE}")
    rates["SGD"] = CURRENT_RATES_FALLBACK["SGD"]  # approximation SORA, pas de taux directeur MAS
    return rates, history, meta

CURRENT_RATES, RATES_HISTORY, RATES_META = build_rates()

def rate_cycle(ccy):
    """Direction du cycle : compare le taux actuel à ~3 et ~6 mois en arrière. ↑ / ↓ / →"""
    h = RATES_HISTORY.get(ccy, [])
    if len(h) < 70: return "→", "#94a3b8"
    cur = h[-1][1]
    m3 = h[-66][1] if len(h) >= 66 else h[0][1]
    m6 = h[-132][1] if len(h) >= 132 else h[0][1]
    if cur > m3 or (cur == m3 and cur > m6): return "↑ hausse", "#fca5a5"
    if cur < m3 or (cur == m3 and cur < m6): return "↓ baisse", "#86efac"
    return "→ pause", "#94a3b8"


print(f"✅ Univers chargé : {len(FX_PAIRS)} paires")
for cat in ["G10_Major","G10_Cross","G10_SafeHaven","G10_Commodity"]:
    n = sum(1 for p in FX_PAIRS.values() if p["cat"]==cat)
    if n: print(f"   {cat:<20} : {n}")
n_em = sum(1 for p in FX_PAIRS.values() if p["em"])
print(f"   EM currencies        : {n_em}")


def ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def compute_rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(p).mean()
    l = (-d.clip(upper=0)).rolling(p).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def compute_atr(h, l, c, p=14):
    prev = c.shift(1)
    tr = pd.concat([h-l, (h-prev).abs(), (l-prev).abs()], axis=1).max(axis=1)
    return tr.rolling(p).mean()

def indicators(closes, highs, lows):
    if len(closes) < 30: return None
    c = closes.copy()
    e20  = ema(c, 20);  e50 = ema(c, 50);  e200 = ema(c, 200)
    rsi  = compute_rsi(c)
    atr  = compute_atr(highs, lows, c) if highs is not None else c.pct_change().abs().rolling(14).mean()*c
    sma20 = c.rolling(20).mean(); std20 = c.rolling(20).std()
    bb_up = sma20 + 2*std20;  bb_lo = sma20 - 2*std20
    cur = float(c.iloc[-1])
    rng = float(bb_up.iloc[-1]) - float(bb_lo.iloc[-1])
    return {
        "close": cur,
        "ema20": float(e20.iloc[-1]),
        "ema50": float(e50.iloc[-1]) if len(c)>=50 else cur,
        "ema200":float(e200.iloc[-1]) if len(c)>=200 else cur,
        "rsi":   float(rsi.iloc[-1]),
        "atr":   float(atr.iloc[-1]),
        "atr_pct": float(atr.iloc[-1]/cur*100) if cur>0 else 0,
        "dist_ema20_atr": float((cur - float(e20.iloc[-1])) / atr.iloc[-1]) if atr.iloc[-1] > 0 else 0,
        "bb_pct":float((cur-float(bb_lo.iloc[-1]))/rng*100) if rng>0 else 50,
    }

def h4_trend(c4):
    if c4 is None or len(c4)<20: return "NEUTRAL", 50
    e20 = ema(c4,20); e50 = ema(c4,50) if len(c4)>=50 else e20
    rsi = compute_rsi(c4)
    cur = float(c4.iloc[-1]); r = float(rsi.iloc[-1])
    if cur>float(e20.iloc[-1])>float(e50.iloc[-1]) and r>50: return "BULLISH", min(int(r),90)
    if cur<float(e20.iloc[-1])<float(e50.iloc[-1]) and r<50: return "BEARISH", max(int(100-r),10)
    return "NEUTRAL", 50

def sup_res(closes, highs, lows):
    if highs is None or len(closes)<20: return [],[]
    h = highs.iloc[-60:].values; l = lows.iloc[-60:].values; cur = float(closes.iloc[-1])
    res = sorted({round(float(h[i]),5) for i in range(2,len(h)-2)
                  if h[i]>h[i-1] and h[i]>h[i+1] and h[i]>h[i-2] and h[i]>h[i+2] and h[i]>cur})[:2]
    sup = sorted({round(float(l[i]),5) for i in range(2,len(l)-2)
                  if l[i]<l[i-1] and l[i]<l[i+1] and l[i]<l[i-2] and l[i]<l[i+2] and l[i]<cur},
                 reverse=True)[:2]
    return sup, res

# ── Signaux (logique script original + DXY) ───────────────────

def carry_score(pair):
    b, q = FX_PAIRS[pair]["currencies"]
    diff = CURRENT_RATES.get(b,2.0) - CURRENT_RATES.get(q,2.0)
    return round(50 + np.clip(diff/5,-1,1)*50, 1), round(diff,2), CURRENT_RATES.get(b,2.0), CURRENT_RATES.get(q,2.0)

def momentum_raw(closes):
    if closes is None or len(closes)<230: return None
    if len(closes)>=252:
        px_r = float(closes.iloc[-21]); px_o = float(closes.iloc[-252])
        return (px_r-px_o)/px_o if px_o>0 else None
    return None

def ppp_score(closes):
    if closes is None or len(closes)<100: return 50.0, 0.0
    cur = float(closes.iloc[-1]); mean = float(closes.iloc[-min(252,len(closes)):].mean())
    dev = (cur-mean)/mean if mean>0 else 0
    return round(50-np.clip(dev/0.10,-1,1)*50,1), round(dev*100,1)

def dxy_score(macro, pair):
    if "DXY" not in macro or len(macro["DXY"])<60: return 50.0, "NEUTRE", 0.0
    dxy = macro["DXY"]
    f20 = float(dxy.iloc[-1]/dxy.iloc[-20]-1) if len(dxy)>=20 else 0
    f60 = float(dxy.iloc[-1]/dxy.iloc[-60]-1) if len(dxy)>=60 else 0
    dxy_dir = 1 if (f20>0.005 and f60>0.005) else (-1 if (f20<-0.005 and f60<-0.005) else 0)
    sens = FX_PAIRS[pair].get("sens",{}).get("DXY",0)
    sc = round(50 + np.clip(dxy_dir*sens,-1,1)*25, 1)
    lbl = "USD FORT" if dxy_dir==1 else ("USD FAIBLE" if dxy_dir==-1 else "NEUTRE")
    return sc, lbl, round(f20*100,2)

def vix_status(macro):
    if "VIX" not in macro or len(macro["VIX"])==0: return float("nan"),"UNKNOWN"
    v = float(macro["VIX"].iloc[-1])
    if v<15: return v,"LOW"
    if v<22: return v,"NORMAL"
    if v<30: return v,"ELEVATED"
    return v,"HIGH"

def compute_signal(pair, closes_d, highs_d, lows_d, closes_h4, macro, all_mom_raw):
    meta = FX_PAIRS[pair]
    c = closes_d.get(pair); h = highs_d.get(pair); l = lows_d.get(pair)
    if c is None or len(c)<30: return None
    ind = indicators(c, h, l)
    if ind is None: return None
    cur = ind["close"]

    # 4 facteurs
    s_carry, diff, rb, rq = carry_score(pair)
    # Momentum cross-sectionnel (rank dans l univers)
    valid = [(p,v) for p,v in all_mom_raw.items() if v is not None]
    if len(valid)>1:
        ranked = sorted(valid, key=lambda x:x[1])
        rm = {p: i/(len(ranked)-1)*100 for i,(p,_) in enumerate(ranked)}
        s_mom = round(rm.get(pair,50),1)
    else:
        s_mom = 50.0
    s_ppp, ppp_dev = ppp_score(c)
    s_dxy, dxy_lbl, dxy_ret = dxy_score(macro, pair)

    score = round(np.clip(s_carry*0.40 + s_mom*0.30 + s_ppp*0.10 + s_dxy*0.20, 0, 100), 1)

    vix_val, vix_lvl = vix_status(macro)
    em_blocked = meta["em"] and vix_lvl in ("ELEVATED","HIGH")

    ema_trend = ("BULLISH" if ind["ema20"]>ind["ema50"]>ind["ema200"]
                 else "BEARISH" if ind["ema20"]<ind["ema50"]<ind["ema200"] else "MIXED")
    h4_dir, h4_str = h4_trend(closes_h4.get(pair))
    b, q = meta["currencies"]

    if em_blocked:          direction = "NEUTRAL"; conv = 0
    elif score >= 65:
        direction = "BUY";  conv = score
        if ema_trend=="BULLISH": conv = min(conv+5,100)
        if h4_dir=="BULLISH":   conv = min(conv+5,100)
        if ind["rsi"]>70:        conv = max(conv-10,0)
    elif score <= 35:
        direction = "SELL"; conv = 100-score
        if ema_trend=="BEARISH": conv = min(conv+5,100)
        if h4_dir=="BEARISH":   conv = min(conv+5,100)
        if ind["rsi"]<30:        conv = max(conv-10,0)
    else:
        direction = "NEUTRAL"; conv = abs(score-50)*2
    conv = round(conv,1)

    pip = meta["pip"]; atr = ind["atr"]
    if direction=="BUY":
        sl=round(cur-ATR_MULT_SL*atr,5); tp1=round(cur+ATR_MULT_TP1*atr,5); tp2=round(cur+ATR_MULT_TP2*atr,5)
    elif direction=="SELL":
        sl=round(cur+ATR_MULT_SL*atr,5); tp1=round(cur-ATR_MULT_TP1*atr,5); tp2=round(cur-ATR_MULT_TP2*atr,5)
    else:
        sl=round(cur-ATR_MULT_SL*atr,5); tp1=round(cur+ATR_MULT_TP1*atr,5); tp2=round(cur+ATR_MULT_TP2*atr,5)

    sl_p=round(abs(cur-sl)/pip); tp1_p=round(abs(cur-tp1)/pip); tp2_p=round(abs(cur-tp2)/pip)
    sup, res = sup_res(c, h, l)

    # ── Explication à 2 niveaux : humain (résumé) + technique (détail) ──
    dist_ema = ind.get("dist_ema20_atr", 0)
    entry_lbl = ("Extension" if abs(dist_ema)>1.5 else ("Pullback" if abs(dist_ema)<0.5 else "Neutre"))
    r = ind["rsi"]

    if em_blocked:
        resume_humain = f"🚫 On ne touche pas. Le marché est stressé en ce moment (indice de peur VIX à {vix_val:.0f}, c'est élevé) et cette paire est risquée. Mieux vaut attendre que ça se calme."
        detail_tech = f"Paire EM bloquée — VIX {vix_val:.1f} > seuil 22."
    else:
        # ── RÉSUMÉ HUMAIN ──
        if direction == "BUY":
            phrase = f"📈 Le script voit une opportunité d'ACHAT sur {meta['label']}. "
            raisons = []
            if abs(diff) > 0.5 and diff > 0:
                raisons.append(f"tu es payé pour tenir la position (différence de taux d'intérêt de +{diff:.1f}% en ta faveur)")
            if s_mom >= 70:
                raisons.append("la tendance de fond est clairement haussière depuis plusieurs mois")
            if ema_trend == "BULLISH":
                raisons.append("toutes les moyennes mobiles pointent vers le haut")
            if raisons:
                phrase += "Pourquoi : " + ", ".join(raisons) + ". "
        elif direction == "SELL":
            phrase = f"📉 Le script voit une opportunité de VENTE sur {meta['label']}. "
            raisons = []
            if abs(diff) > 0.5 and diff < 0:
                raisons.append(f"tu es payé pour tenir la position (différence de taux de {diff:.1f}% en ta faveur)")
            if s_mom <= 30:
                raisons.append("la tendance de fond est clairement baissière depuis plusieurs mois")
            if ema_trend == "BEARISH":
                raisons.append("toutes les moyennes mobiles pointent vers le bas")
            if raisons:
                phrase += "Pourquoi : " + ", ".join(raisons) + ". "
        else:
            phrase = f"⏸ Pas de signal clair sur {meta['label']} aujourd'hui. Les indicateurs se contredisent — mieux vaut passer son tour. "

        # Avertissement RSI en langage humain
        if direction == "BUY" and r > 70:
            phrase += f"⚠️ Attention : le prix a déjà beaucoup monté (RSI {r:.0f}, c'est haut). Tu risques d'arriver en fin de mouvement. Si tu veux entrer, ça peut valoir le coup d'attendre que le prix redescende un peu vers sa moyenne avant de rentrer. "
        elif direction == "SELL" and r < 30:
            phrase += f"⚠️ Attention : le prix a déjà beaucoup baissé (RSI {r:.0f}, c'est bas). Tu risques d'arriver en fin de mouvement. Attendre un petit rebond avant d'entrer peut donner un meilleur prix. "

        # Info pullback NEUTRE (mesure, pas conseil)
        if entry_lbl == "Extension":
            phrase += f"📏 Note : le prix est actuellement loin de sa moyenne mobile ({abs(dist_ema):.1f}× la volatilité moyenne). Statistiquement, c'est une entrée 'tardive'. "
        elif entry_lbl == "Pullback":
            phrase += f"📏 Note : le prix est proche de sa moyenne mobile ({abs(dist_ema):.1f}× la volatilité). C'est plutôt une zone d'entrée 'fraîche'. "

        resume_humain = phrase

        # ── DÉTAIL TECHNIQUE (comme avant) ──
        parts = []
        icon = "📈 BUY" if direction=="BUY" else ("📉 SELL" if direction=="SELL" else "⏸ NO TRADE")
        parts.append(f"{icon} — Score {score}/100, conviction {conv:.0f}%.")
        cd = diff
        if abs(cd)>0.5:
            fav = ("BUY" if cd>0 else "SELL")
            parts.append(f"{'✅' if direction==fav else '⚠️'} Carry : {b}({rb:.2f}%) vs {q}({rq:.2f}%), diff {cd:+.2f}%.")
        else:
            parts.append(f"➖ Carry neutre ({cd:+.2f}%).")
        if s_mom>=70: parts.append(f"✅ Momentum top {100-s_mom:.0f}% univers.")
        elif s_mom<=30: parts.append(f"✅ Momentum bottom {s_mom:.0f}%.")
        else: parts.append(f"➖ Momentum neutre (rang {s_mom:.0f}/100).")
        if ema_trend=="BULLISH": parts.append(f"✅ Daily : EMA20 > EMA50 > EMA200.")
        elif ema_trend=="BEARISH": parts.append(f"✅ Daily : EMA20 < EMA50 < EMA200.")
        else: parts.append(f"⚠️ EMAs mixtes.")
        if r>70: parts.append(f"⚠️ RSI {r:.0f} — surachat.")
        elif r<30: parts.append(f"⚠️ RSI {r:.0f} — survente.")
        else: parts.append(f"✅ RSI {r:.0f} — zone saine.")
        parts.append(f"📏 Dist EMA20 : {dist_ema:+.2f} ATR ({entry_lbl}).")
        if h4_dir!="NEUTRAL":
            ok = (direction=="BUY" and h4_dir=="BULLISH") or (direction=="SELL" and h4_dir=="BEARISH")
            parts.append(f"{'✅' if ok else '⚠️'} H4 {h4_dir} — {'confirme' if ok else 'diverge'}.")
        if dxy_lbl!="NEUTRE":
            parts.append(f"{'✅' if (s_dxy>=55 and direction=='BUY') or (s_dxy<=45 and direction=='SELL') else '➖'} DXY {dxy_lbl} ({dxy_ret:+.1f}%/20j).")
        if not np.isnan(vix_val) and vix_lvl=="ELEVATED":
            parts.append(f"⚠️ VIX {vix_val:.1f} — réduire taille.")
        detail_tech = " ".join(parts)

    # expl combine les deux niveaux avec un séparateur reconnaissable
    expl = resume_humain + " ||| " + detail_tech

    return {
        "pair":pair,"label":meta["label"],"cat":meta["cat"],"em":meta["em"],
        "direction":direction,"conviction":conv,"score":score,"price":cur,
        "sl":sl,"sl_pips":sl_p,"tp1":tp1,"tp1_pips":tp1_p,"tp2":tp2,"tp2_pips":tp2_p,
        "rr1":round(tp1_p/sl_p,2) if sl_p>0 else 0,
        "rr2":round(tp2_p/sl_p,2) if sl_p>0 else 0,
        "atr":round(atr,5),"atr_pct":round(ind["atr_pct"],3),
        "rsi":round(ind["rsi"],1),"ema20":round(ind["ema20"],5),
        "ema50":round(ind["ema50"],5),"ema200":round(ind["ema200"],5),
        "ema_trend":ema_trend,"h4_dir":h4_dir,
        "carry_diff":diff,"rate_b":rb,"rate_q":rq,"b":b,"q":q,
        "ppp_dev":ppp_dev,"dxy_label":dxy_lbl,"dxy_ret":dxy_ret,
        "vix_val":round(vix_val,1) if not np.isnan(vix_val) else 0,
        "vix_level":vix_lvl,"em_blocked":em_blocked,
        "s_carry":s_carry,"s_mom":s_mom,"s_ppp":s_ppp,"s_dxy":s_dxy,
        "sup":sup,"res":res,"explanation":expl,
        "dist_ema20_atr":round(ind.get("dist_ema20_atr",0),2),
        "entry_label": ("Extension" if abs(ind.get("dist_ema20_atr",0))>1.5
                        else ("Pullback" if abs(ind.get("dist_ema20_atr",0))<0.5 else "Neutre")),
    }

print("✅ Fonctions techniques chargées")


JOURNAL_COLS = [
    "Date_Signal","Heure_UTC","Asset_Class","Paire","Direction","Prix_Entree",
    "SL","TP1","TP2","SL_Pips","TP1_Pips","TP2_Pips",
    "Score","Conviction","Carry_Diff","RSI","EMA_Trend","H4",
    "DXY_Context","ATR","Categorie",
    "Date_Sortie","Prix_Sortie","Raison_Sortie",
    "PnL_Pips","PnL_USD","Resultat","Notes"
]

def load_journal():
    """Journal au format CSV (plus lisible en diff git qu'un .xlsx binaire)."""
    if JOURNAL_FILE.exists():
        return pd.read_csv(JOURNAL_FILE)
    return pd.DataFrame(columns=JOURNAL_COLS)

def save_journal(df):
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(JOURNAL_FILE, index=False)
    print(f"✅ Journal sauvegardé : {JOURNAL_FILE} ({len(df)} lignes)")

def add_trade(sig, notes="", asset_class=None):
    """Ajoute une ligne au journal. Fonctionne avec les signaux forex,
    indices et matières premières (schémas de champs légèrement différents,
    on utilise .get() partout avec une valeur par défaut vide)."""
    df = load_journal()
    row = {
        "Date_Signal": datetime.now().strftime("%Y-%m-%d"),
        "Heure_UTC": datetime.utcnow().strftime("%H:%M"),
        "Asset_Class": asset_class or sig.get("asset_class", "Forex"),
        "Paire": sig.get("label", sig.get("pair", "")),
        "Direction": sig.get("direction", ""),
        "Prix_Entree": sig.get("price", ""), "SL": sig.get("sl", ""),
        "TP1": sig.get("tp1", ""), "TP2": sig.get("tp2", ""),
        "SL_Pips": sig.get("sl_pips", ""), "TP1_Pips": sig.get("tp1_pips", ""),
        "TP2_Pips": sig.get("tp2_pips", ""),
        "Score": sig.get("score", ""), "Conviction": sig.get("conviction", ""),
        "Carry_Diff": sig.get("carry_diff", ""), "RSI": sig.get("rsi", ""),
        "EMA_Trend": sig.get("ema_trend", ""), "H4": sig.get("h4_dir", ""),
        "DXY_Context": sig.get("dxy_label", ""), "ATR": sig.get("atr", ""),
        "Categorie": sig.get("cat", sig.get("asset_class", "")), "Notes": notes,
        "Date_Sortie":"","Prix_Sortie":"","Raison_Sortie":"",
        "PnL_Pips":"","PnL_USD":"","Resultat":"",
    }
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_journal(df)
    return df

def close_trade(paire_label, prix_sortie, raison="TP1", notes=""):
    """Ferme un trade ouvert et calcule le P&L"""
    df = load_journal()
    mask = (df["Paire"]==paire_label) & (df["Date_Sortie"]=="")
    if mask.sum()==0:
        print(f"⚠️ Aucun trade ouvert trouvé pour {paire_label}")
        return df
    idx = df[mask].index[-1]
    entry = float(df.loc[idx,"Prix_Entree"])
    sl    = float(df.loc[idx,"SL"])
    pip   = FX_PAIRS.get([k for k,v in FX_PAIRS.items() if v["label"]==paire_label][0],{}).get("pip",0.0001)
    direction = df.loc[idx,"Direction"]

    pnl_price = (prix_sortie-entry) if direction=="BUY" else (entry-prix_sortie)
    pnl_pips  = round(pnl_price/pip)
    pnl_usd   = round(pnl_pips * 1.0, 2)  # à ajuster selon lot size
    resultat  = "WIN" if pnl_price>0 else "LOSS"

    df.loc[idx,"Date_Sortie"]  = datetime.now().strftime("%Y-%m-%d")
    df.loc[idx,"Prix_Sortie"]  = prix_sortie
    df.loc[idx,"Raison_Sortie"]= raison
    df.loc[idx,"PnL_Pips"]     = pnl_pips
    df.loc[idx,"PnL_USD"]      = pnl_usd
    df.loc[idx,"Resultat"]     = resultat
    df.loc[idx,"Notes"]        = notes
    save_journal(df)
    print(f"{'✅ WIN' if resultat=='WIN' else '❌ LOSS'} — {paire_label} | {pnl_pips:+d} pips | P&L: ${pnl_usd}")
    return df

def perf_stats(df=None):
    if df is None: df = load_journal()
    closed = df[df["Resultat"].isin(["WIN","LOSS"])].copy()
    if len(closed)==0: return {}
    wins = (closed["Resultat"]=="WIN").sum()
    pnls = pd.to_numeric(closed["PnL_USD"], errors="coerce").dropna()
    w_pnl = pnls[pnls>0]; l_pnl = pnls[pnls<0]
    eq = CAPITAL_PAPER + pnls.cumsum()
    rets = eq.pct_change().dropna()
    sharpe = float(rets.mean()/rets.std()*np.sqrt(252)) if len(rets)>1 and rets.std()>0 else 0
    dd = float(((eq-eq.cummax())/eq.cummax()).min()) if len(eq)>1 else 0
    pf = w_pnl.sum()/abs(l_pnl.sum()) if len(l_pnl)>0 and abs(l_pnl.sum())>0 else float("inf")
    return {
        "total":len(closed),"wins":int(wins),"losses":int(len(closed)-wins),
        "win_rate":round(wins/len(closed)*100,1),
        "profit_factor":round(pf,2),"sharpe":round(sharpe,2),
        "max_dd":round(dd*100,2),"total_pnl":round(pnls.sum(),2),
        "avg_win":round(w_pnl.mean(),2) if len(w_pnl)>0 else 0,
        "avg_loss":round(l_pnl.mean(),2) if len(l_pnl)>0 else 0,
        "expectancy":round(pnls.mean(),2),
    }

print("✅ Journal chargé")
df_journal = load_journal()
print(f"   {len(df_journal)} trades enregistrés")
if len(df_journal)>0:
    p = perf_stats(df_journal)
    if p:
        print(f"   Win Rate : {p['win_rate']}% | PF : {p['profit_factor']} | Sharpe : {p['sharpe']} | DD : {p['max_dd']}%")

# ═══════════════ AMÉLIORATIONS v4 : maturité · double entrée · stop anti-liquidité · sizing ═══════════════

def candle_impulsive_against(closes, highs, lows, direction, atr_val):
    """Détecte une bougie impulsive récente CONTRE le sens du signal (couteau qui tombe)."""
    if closes is None or len(closes) < 3 or atr_val <= 0:
        return False
    last_moves = closes.diff().iloc[-2:]
    if direction == "BUY":
        return bool((last_moves < -1.2 * atr_val).any())
    if direction == "SELL":
        return bool((last_moves > +1.2 * atr_val).any())
    return False

def compute_maturity(sig, closes, highs, lows):
    """
    État de maturité du signal — la leçon GBP/JPY codée en garde-fou.
    🔴 PAS MÛR : H4 diverge du Daily OU bougie impulsive contraire récente
    🟡 EN FORMATION : H4 neutre OU prix en extension (>1.5 ATR de l'EMA20)
    🟢 EXÉCUTABLE : H4 aligné + pas d'extension + pas de chute/montée violente en cours
    """
    d = sig["direction"]
    if d == "NEUTRAL":
        return "—", "#64748b", "Pas de signal directionnel — maturité non applicable."
    h4 = sig.get("h4_dir", "NEUTRAL")
    dist = abs(sig.get("dist_ema20_atr", 0))
    atr_val = sig.get("atr", 0)
    impulsive = candle_impulsive_against(closes, highs, lows, d, atr_val)
    h4_aligned  = (d == "BUY" and h4 == "BULLISH") or (d == "SELL" and h4 == "BEARISH")
    h4_diverge  = (d == "BUY" and h4 == "BEARISH") or (d == "SELL" and h4 == "BULLISH")

    if h4_diverge or impulsive:
        reasons = []
        if h4_diverge: reasons.append("le H4 va dans le sens inverse du signal")
        if impulsive:  reasons.append("le prix vient de faire un mouvement violent contre le signal (couteau qui tombe)")
        tail = (" Attendre que le prix se stabilise et que le H4 se réaligne."
                if h4_diverge else
                " Attendre que le prix se stabilise et forme une base (bougie de rejet, petit creux plus haut).")
        return ("🔴 PAS MÛR", "#ef4444",
                "Ne pas entrer maintenant : " + " et ".join(reasons) + "." + tail)
    if (not h4_aligned) or dist > 1.5:
        reasons = []
        if not h4_aligned: reasons.append("le H4 n'a pas encore confirmé")
        if dist > 1.5:     reasons.append(f"le prix est en extension ({dist:.1f}×ATR de sa moyenne — entrée tardive)")
        return ("🟡 EN FORMATION", "#f59e0b",
                "Setup à surveiller, pas encore optimal : " + " et ".join(reasons) +
                ". Préparer le plan, attendre une meilleure entrée.")
    return ("🟢 EXÉCUTABLE", "#22c55e",
            "Biais et timing alignés : H4 confirme le Daily, le prix n'est pas en extension, "
            "pas de mouvement violent contraire en cours.")

def anti_liquidity_stop(direction, entry, sl_raw, sup_levels, res_levels, atr_val, nd=5):
    """
    Vérifie si le SL mécanique tombe dans la zone de liquidité évidente
    (pile sur/sous un swing visible par tout le monde) — la leçon du stop hunt GBP/JPY.
    Retourne (sl_final, ajusté?, note)
    """
    if atr_val <= 0:
        return sl_raw, False, ""
    if direction == "BUY" and sup_levels:
        nearest_sup = max([s for s in sup_levels if s < entry], default=None)
        if nearest_sup is not None and abs(sl_raw - nearest_sup) < 0.30 * atr_val and sl_raw >= nearest_sup - 0.1*atr_val:
            sl_adj = round(nearest_sup - 0.5 * atr_val, nd)
            return sl_adj, True, (f"SL ajusté sous la zone de liquidité : le SL mécanique tombait pile sur le support évident "
                                  f"{nearest_sup} — là où tout le monde met son stop et où le marché vient le chercher.")
    if direction == "SELL" and res_levels:
        nearest_res = min([r for r in res_levels if r > entry], default=None)
        if nearest_res is not None and abs(sl_raw - nearest_res) < 0.30 * atr_val and sl_raw <= nearest_res + 0.1*atr_val:
            sl_adj = round(nearest_res + 0.5 * atr_val, nd)
            return sl_adj, True, (f"SL ajusté au-dessus de la zone de liquidité : le SL mécanique tombait pile sur la résistance évidente "
                                  f"{nearest_res} — zone de stop hunt classique.")
    return sl_raw, False, ""

def usd_per_quote(quote_ccy):
    """Combien vaut 1 USD exprimé dans la devise de cotation (pour convertir le pip en USD).
       Lit les prix réels du jour — plus de valeur figée."""
    if quote_ccy == "USD":
        return 1.0
    try:
        for p, meta in FX_PAIRS.items():
            b, q = meta.get("currencies", (None, None))
            s = closes_d.get(p)
            if s is None or len(s) == 0:
                continue
            if b == "USD" and q == quote_ccy:
                return float(s.iloc[-1])
            if q == "USD" and b == quote_ccy:
                v = float(s.iloc[-1])
                if v > 0: return 1.0 / v
    except Exception:
        pass
    return None

def pip_value_usd(pair):
    """Valeur d'1 pip pour 1 lot standard (100 000 unités), en USD, calculée sur les taux du jour.
       Corrige le bug des paires exotiques (ZAR/MXN/HUF/PLN... valaient ~0.5-3$ et non 10$)."""
    meta = FX_PAIRS.get(pair, {})
    pip = meta.get("pip", 0.0001)
    b, q = meta.get("currencies", (None, None))
    rate = usd_per_quote(q) if q else None
    if not rate or rate <= 0:
        return 6.5 if "JPY" in pair else 10.0     # filet de sécurité
    return (100_000 * pip) / rate

def position_size_fx(sl_pips, pair):
    """Sizing : risque RISK_PER_TRADE du capital, avec valeur de pip RÉELLE par paire."""
    if sl_pips <= 0: return 0.0, 0.0
    risk_amount = CAPITAL * RISK_PER_TRADE
    pip_val = pip_value_usd(pair)
    if pip_val <= 0: return 0.0, round(risk_amount, 2)
    lots = risk_amount / (sl_pips * pip_val)
    return (round(lots, 2) if lots >= 0.01 else round(lots, 3)), round(risk_amount, 2)

def double_entry_plan(sig, nd=5):
    """
    Plan à deux entrées : directe (prix actuel) vs pullback (zone EMA20).
    Matérialise la pratique réelle : attendre le retracement = meilleur RR.
    """
    d = sig["direction"]
    if d == "NEUTRAL":
        return None
    cur  = sig["price"]; e20 = sig["ema20"]; atr_v = sig["atr"]
    tp1  = sig["tp1"];  tp2 = sig["tp2"]
    pip  = FX_PAIRS.get(sig["pair"], {}).get("pip", 0.0001)

    # Entrée directe — SL anti-liquidité
    sl_dir, adj_dir, note_dir = anti_liquidity_stop(d, cur, sig["sl"], sig.get("sup", []), sig.get("res", []), atr_v, nd)
    sl_dir_pips  = round(abs(cur - sl_dir) / pip)
    rr1_dir = round(abs(tp1 - cur) / abs(cur - sl_dir), 2) if cur != sl_dir else 0
    lots_dir, risk_amt = position_size_fx(sl_dir_pips, sig["pair"])

    # Entrée pullback — zone EMA20 (si pertinente dans le sens du trade)
    pb_entry = None
    if d == "BUY" and cur > e20 + 0.15 * atr_v:
        pb_entry = round(e20, nd)
    elif d == "SELL" and cur < e20 - 0.15 * atr_v:
        pb_entry = round(e20, nd)
    pullback = None
    if pb_entry is not None:
        sl_pb_raw = round(pb_entry - ATR_MULT_SL * atr_v, nd) if d == "BUY" else round(pb_entry + ATR_MULT_SL * atr_v, nd)
        sl_pb, adj_pb, note_pb = anti_liquidity_stop(d, pb_entry, sl_pb_raw, sig.get("sup", []), sig.get("res", []), atr_v, nd)
        sl_pb_pips = round(abs(pb_entry - sl_pb) / pip)
        rr1_pb = round(abs(tp1 - pb_entry) / abs(pb_entry - sl_pb), 2) if pb_entry != sl_pb else 0
        lots_pb, _ = position_size_fx(sl_pb_pips, sig["pair"])
        pullback = {"entry": pb_entry, "sl": sl_pb, "sl_pips": sl_pb_pips,
                    "rr1": rr1_pb, "lots": lots_pb, "adjusted": adj_pb, "note": note_pb}

    return {"direct": {"entry": cur, "sl": sl_dir, "sl_pips": sl_dir_pips,
                       "rr1": rr1_dir, "lots": lots_dir, "adjusted": adj_dir, "note": note_dir},
            "pullback": pullback, "risk_amount": risk_amt}

# ═══════════════ V6 : POSITIONNEMENT COT (CFTC, API publique sans clé) ═══════════════
# Rapport hebdomadaire Legacy Futures-Only : positions nettes des non-commerciaux
# (hedge funds / CTA). COT Index 0-100 = où se situe la position nette actuelle
# dans sa fourchette 3 ans. ≥90 ou ≤10 = extrême = trade encombré.
# Contexte hebdomadaire (données du mardi, publiées le vendredi) — PAS un signal de timing.

COT_MARKETS = {   # fragment de recherche plein-texte → clé interne
    "EURO FX": "EUR", "BRITISH POUND": "GBP", "JAPANESE YEN": "JPY",
    "AUSTRALIAN DOLLAR": "AUD", "CANADIAN DOLLAR": "CAD", "SWISS FRANC": "CHF",
    "NZ DOLLAR": "NZD", "MEXICAN PESO": "MXN", "BRAZILIAN REAL": "BRL",
    "U.S. DOLLAR INDEX": "USD",
    "GOLD": "GOLD", "SILVER": "SILVER", "COPPER": "COPPER", "PLATINUM": "PLATINUM",
    "CRUDE OIL": "WTI", "NATURAL GAS": "NATGAS",
    "E-MINI S&P 500": "SPX", "NASDAQ-100": "NDX", "NIKKEI": "NKY",
}

def fetch_cot_data():
    """COT Index par marché. Retourne dict {key: {net, index, date, extreme}} — {} si API down."""
    out = {}
    base = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
    for frag, key in COT_MARKETS.items():
        try:
            r = requests.get(base, params={
                "$q": frag, "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 160,
                "$select": "market_and_exchange_names,report_date_as_yyyy_mm_dd,"
                           "noncomm_positions_long_all,noncomm_positions_short_all"},
                timeout=12)
            rows = [x for x in r.json()
                    if frag in x.get("market_and_exchange_names", "").upper()]
            if len(rows) < 30: continue
            nets = [int(float(x["noncomm_positions_long_all"])) - int(float(x["noncomm_positions_short_all"]))
                    for x in rows]
            cur = nets[0]
            lo, hi = min(nets), max(nets)
            idx = round((cur - lo) / (hi - lo) * 100) if hi > lo else 50
            extreme = "LONG" if idx >= 90 else ("SHORT" if idx <= 10 else None)
            out[key] = {"net": cur, "index": idx, "date": rows[0]["report_date_as_yyyy_mm_dd"][:10],
                        "extreme": extreme,
                        "elevated": "LONG" if 80 <= idx < 90 else ("SHORT" if 10 < idx <= 20 else None)}
            time.sleep(0.4)
        except Exception:
            continue
    return out

def cot_chip_html(s):
    """Chip COT sur une carte : n'apparaît QUE si une jambe est en zone extrême/élevée."""
    keys = []
    if s.get("asset_class") == "Forex":
        cur = FX_PAIRS.get(s.get("pair", ""), {}).get("currencies")
        if cur: keys = [c for c in cur if c in COT_DATA]
    elif s.get("pair") in COT_DATA:
        keys = [s["pair"]]
    chips = ""
    for k in keys:
        d = COT_DATA[k]
        if d["extreme"]:
            side = "acheteur" if d["extreme"] == "LONG" else "vendeur"
            chips += (f'<div style="font-size:10px;color:#f0abfc;background:rgba(217,70,239,.08);'
                      f'border-left:3px solid #d946ef;border-radius:0 6px 6px 0;padding:5px 10px;margin-bottom:6px">'
                      f'🐘 <strong>Positionnement {k} extrême {side}</strong> (COT {d["index"]}/100 sur 3 ans, rapport {d["date"]}) — '
                      f'trade encombré : tout le monde a déjà ce pari, l’unwind peut être violent. Taille réduite, sécurise tôt.</div>')
        elif d["elevated"]:
            side = "acheteur" if d["elevated"] == "LONG" else "vendeur"
            chips += (f'<div style="font-size:10px;color:#c4b5fd;padding:3px 0 6px 2px">'
                      f'🐘 COT {k} : positionnement {side} élevé ({d["index"]}/100, {d["date"]})</div>')
    return chips

def cot_table_html():
    if not COT_DATA:
        return ('<div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:12px;'
                'margin-top:14px;font-size:12px;color:#64748b">🐘 Positionnement COT indisponible cette semaine '
                '(API CFTC injoignable) — le reste du dashboard n’est pas affecté.</div>')
    rows = ""
    for k, d in sorted(COT_DATA.items(), key=lambda x: -abs(x[1]["index"] - 50)):
        col = "#f0abfc" if d["extreme"] else ("#c4b5fd" if d["elevated"] else "#94a3b8")
        bar_col = "#d946ef" if d["extreme"] else ("#8b5cf6" if d["elevated"] else "#475569")
        tag = " ⚠️ EXTRÊME" if d["extreme"] else ""
        rows += (f'<div style="display:flex;align-items:center;gap:10px;font-size:11px;margin-bottom:5px">'
                 f'<span style="width:64px;font-family:monospace;color:#e2e8f0">{k}</span>'
                 f'<div style="flex:1;height:5px;background:#1e293b;border-radius:3px;position:relative">'
                 f'<div style="position:absolute;left:{d["index"]}%;top:-2px;width:3px;height:9px;background:{bar_col};border-radius:2px"></div></div>'
                 f'<span style="width:120px;text-align:right;font-family:monospace;color:{col}">{d["index"]}/100 · net {d["net"]:+,}{tag}</span></div>')
    dt = next(iter(COT_DATA.values()))["date"]
    return (f'<div style="background:#111827;border:1px solid #1e293b;border-radius:12px;padding:14px;margin-top:14px">'
            f'<div style="font-size:13px;font-weight:700;color:#e2e8f0;margin-bottom:4px">🐘 Positionnement spéculatif (COT · CFTC)</div>'
            f'<div style="font-size:10px;color:#64748b;margin-bottom:10px;line-height:1.6">Position nette des non-commerciaux '
            f'(hedge funds/CTA) située dans sa fourchette 3 ans : 0 = extrême vendeur, 100 = extrême acheteur. '
            f'Rapport du {dt} (données du mardi, publiées le vendredi) — contexte hebdomadaire, pas un signal de timing.</div>'
            f'{rows}</div>')

# ═══════════════ V6 : ACCORD MOMENTUM MULTI-HORIZON (1m/3m/12m — version AQR) ═══════════════
def mom_agreement(closes):
    """Signes des performances 21/63/252 jours. Accord total = tendance de qualité ;
       1m divergent = tendance vieillissante (entrée tardive risquée)."""
    if closes is None or len(closes) < 70: return None
    c = closes
    n = len(c)
    # Horizons 1m/3m/12m — bornés à l'historique réellement disponible.
    # ("1y" de yfinance renvoie 252 à 262 bougies selon les fériés : sans ce garde-fou,
    #  la pastille disparaissait silencieusement les jours où il manquait quelques bougies.)
    i1, i3, i12 = min(22, n - 1), min(64, n - 1), min(253, n - 1)
    approx = i12 < 253
    r1 = float(c.iloc[-1] / c.iloc[-i1] - 1)
    r3 = float(c.iloc[-1] / c.iloc[-i3] - 1)
    r12 = float(c.iloc[-1] / c.iloc[-i12] - 1)
    s = lambda x: "↑" if x > 0 else "↓"
    aligned = (r1 > 0) == (r3 > 0) == (r12 > 0)
    if aligned:
        label, col = f"Tendance {s(r1)}{s(r3)}{s(r12)} accord total", ("#86efac" if r1 > 0 else "#fca5a5")
    elif (r3 > 0) == (r12 > 0):
        label, col = f"1m{s(r1)} diverge de 3m/12m{s(r3)} — tendance vieillissante", "#fcd34d"
    else:
        label, col = f"Horizons mixtes {s(r1)}{s(r3)}{s(r12)} — pas de tendance nette", "#94a3b8"
    return {"r1": round(r1*100,1), "r3": round(r3*100,1), "r12": round(r12*100,1),
            "aligned": aligned, "label": label, "color": col, "approx": approx,
            "horizon_days": i12}

def mom_pill_html(s):
    m = s.get("mom_h")
    if not m: return ""
    return (f'<span style="font-size:10px;padding:2px 8px;background:#1f2937;border-radius:20px;color:{m["color"]}" '
            f'title="1m {m["r1"]:+}% · 3m {m["r3"]:+}% · {m.get("horizon_days",253)}j {m["r12"]:+}%">📈 {m["label"]}</span>')


# ═══════════════ V7 : MÉMOIRE DES CHOCS ═══════════════
# Le détecteur 🔥 ne voit que 1-3 jours : un choc de J-5 devient invisible alors que
# le marché en digère encore les conséquences (cas USD/CHF, krach du 19/08 vu le 24/08).
# Cette couche garde 10 séances en mémoire et mesure OÙ EN EST le retracement du choc.

def shock_memory(closes, atr_val, lookback=10, seuil_atr=2.0):
    """Plus gros mouvement >2 ATR des 10 dernières séances + état du retracement.
       Retourne None si aucun choc — la carte reste silencieuse."""
    if closes is None or len(closes) < lookback + 2 or not atr_val or atr_val <= 0:
        return None
    c = closes.iloc[-(lookback + 1):].reset_index(drop=True)
    d = c.diff()
    if d.abs().max() != d.abs().max():   # NaN
        return None
    i = int(d.abs().idxmax())
    mv = float(d.iloc[i])
    if abs(mv) < seuil_atr * atr_val:
        return None
    origin = float(c.iloc[i - 1])        # prix AVANT le choc
    end    = float(c.iloc[i])            # prix APRÈS le choc
    cur    = float(c.iloc[-1])
    days   = len(c) - 1 - i
    if days == 0:                        # choc du jour = déjà couvert par 🔥
        return None
    denom = origin - end
    retr = ((cur - end) / denom * 100) if abs(denom) > 1e-12 else 0.0
    recovered = (cur >= origin) if mv < 0 else (cur <= origin)
    return {"days": days, "atr_mult": round(abs(mv) / atr_val, 1),
            "pct": round(mv / origin * 100, 2), "dir": "baissier" if mv < 0 else "haussier",
            "origin": origin, "end": end, "retr": int(round(retr)), "recovered": recovered}

def shock_html(s, nd=5):
    """Bandeau mémoire de choc, orienté selon le sens du trade envisagé."""
    sh = s.get("shock")
    if not sh: return ""
    d = s.get("direction", "NEUTRAL")
    contre = (d == "BUY" and sh["dir"] == "baissier") or (d == "SELL" and sh["dir"] == "haussier")
    base = (f'Choc {sh["dir"]} {sh["pct"]:+.2f}% il y a {sh["days"]}j ({sh["atr_mult"]}×ATR). '
            f'Retracement actuel : <strong>{sh["retr"]}%</strong> du choc — ')
    if sh["recovered"]:
        tail = (f'le prix a <strong>dépassé l\'origine {sh["origin"]:.{nd}f}</strong> : '
                f'le choc est digéré, la reprise est validée.')
        col, bg = "#86efac", "34,197,94"
    elif contre:
        sens = "acheter" if d == "BUY" else "vendre"
        tail = (f'toujours {"sous" if sh["dir"]=="baissier" else "au-dessus de"} l\'origine '
                f'<strong>{sh["origin"]:.{nd}f}</strong>. {sens.capitalize()} ici, c\'est {sens} un '
                f'<strong>retracement</strong>, pas une reprise. La reprise se confirme seulement '
                f'{"au-dessus de" if sh["dir"]=="baissier" else "sous"} {sh["origin"]:.{nd}f}.')
        col, bg = "#fca5a5", "239,68,68"
    else:
        tail = (f'le mouvement va dans ton sens et n\'est pas encore effacé '
                f'(origine {sh["origin"]:.{nd}f}). Le flux du choc te porte encore.')
        col, bg = "#fdba74", "249,115,22"
    return (f'<div style="background:rgba({bg},.08);border-left:3px solid {col};border-radius:0 8px 8px 0;'
            f'padding:8px 12px;margin-bottom:8px;font-size:11px;color:{col};line-height:1.6">'
            f'⚡ <strong>MÉMOIRE DE CHOC</strong> — {base}{tail}</div>')

# ═══════════════ V7 : ZONES VISIBLES — distance, RR comparé, jauge ═══════════════
# Les zones S/D étaient calculées depuis la V5 mais enfermées dans un <details> replié.
# On les sort au niveau du plan, avec ce qui manquait : à quelle distance, et ce que ça change au RR.

def dist_txt(s, cur, target):
    """Distance zone↔prix dans l'unité NATURELLE de l'actif.
       Forex = pips · Indices = points · Métaux/Énergie = points (2 décimales si prix < 100)."""
    diff = abs(cur - target)
    ac = s.get("asset_class", "")
    if ac == "Forex":
        pip = FX_PAIRS.get(s.get("pair", ""), {}).get("pip", 0.0001)
        return f"{int(round(diff / pip))} pips"
    if diff >= 100:
        return f"{diff:,.0f} points".replace(",", " ")
    if cur and cur < 100:
        return f"{diff:.2f} points"
    return f"{diff:,.1f} points".replace(",", " ")

def zone_context(s):
    """Zone pertinente selon le sens, distance dans l'unité de l'actif, RR zone vs direct, jauge 0-100."""
    d = s.get("direction", "NEUTRAL")
    cur = s.get("price"); atr_v = s.get("atr", 0) or 0
    dz = s.get("sd_demand") or []; sz = s.get("sd_supply") or []
    pip = FX_PAIRS.get(s.get("pair", ""), {}).get("pip") if s.get("asset_class") == "Forex" else None
    if pip is None:
        pip = 0.01 if (cur and cur > 10) else 0.0001
    out = {"gauge": None, "zone": None}

    # Jauge : où se situe le prix entre la demande la plus proche et l'offre la plus proche
    lo = max([z["hi"] for z in dz], default=None)
    hi = min([z["lo"] for z in sz], default=None)
    if lo is not None and hi is not None and hi > lo:
        out["gauge"] = {"pct": round((cur - lo) / (hi - lo) * 100), "lo": lo, "hi": hi}

    if d == "NEUTRAL" or not cur:
        return out
    cand = dz if d == "BUY" else sz
    if not cand:
        return out
    z = cand[0]
    entry_z = z["hi"] if d == "BUY" else z["lo"]
    dist_pips = int(round(abs(cur - entry_z) / pip))   # conservé pour compat
    dist_label = dist_txt(s, cur, entry_z)
    tp1 = s.get("tp1")
    rr_zone = None
    if tp1 and atr_v > 0:
        sl_z = (z["lo"] - 0.5 * atr_v) if d == "BUY" else (z["hi"] + 0.5 * atr_v)
        risk = abs(entry_z - sl_z)
        if risk > 0:
            rr_zone = round(abs(tp1 - entry_z) / risk, 2)
    out["zone"] = {"lo": z["lo"], "hi": z["hi"], "fresh": z["fresh"], "strength": z["strength"],
                   "entry": entry_z, "dist_pips": dist_pips, "dist_label": dist_label, "rr_zone": rr_zone,
                   "rr_direct": s.get("rr1"), "in_zone": (z["lo"] <= cur <= z["hi"])}
    return out

def zone_visual_html(s, nd=5):
    zc = s.get("zone_ctx") or {}
    z, g = zc.get("zone"), zc.get("gauge")
    if not z and not g: return ""
    parts = ""
    if g:
        pos = max(0, min(100, g["pct"]))
        col = "#86efac" if pos <= 33 else ("#fcd34d" if pos <= 66 else "#fca5a5")
        lbl = ("bas de fourchette — favorable à l'achat" if pos <= 33 else
               "milieu de fourchette" if pos <= 66 else "haut de fourchette — favorable à la vente")
        parts += (f'<div style="margin-bottom:6px">'
                  f'<div style="display:flex;justify-content:space-between;font-size:9px;color:#64748b;margin-bottom:3px">'
                  f'<span style="font-family:monospace">D {g["lo"]:.{nd}f}</span>'
                  f'<span style="color:{col}">{lbl}</span>'
                  f'<span style="font-family:monospace">O {g["hi"]:.{nd}f}</span></div>'
                  f'<div style="position:relative;height:6px;background:linear-gradient(90deg,'
                  f'rgba(34,197,94,.35),rgba(100,116,139,.25),rgba(239,68,68,.35));border-radius:3px">'
                  f'<div style="position:absolute;left:{pos}%;top:-3px;width:3px;height:12px;'
                  f'background:{col};border-radius:2px"></div></div></div>')
    if z:
        badge = "🌱 fraîche" if z["fresh"] else "♻️ testée"
        if z["in_zone"]:
            txt = (f'<strong>Le prix est DANS la zone</strong> {z["lo"]:.{nd}f}–{z["hi"]:.{nd}f} '
                   f'({badge}, {z["strength"]}×ATR) — c\'est le bon endroit pour entrer.')
            col = "#86efac"
        else:
            gain = ""
            if z["rr_zone"] and z["rr_direct"]:
                gain = (f' → RR <strong>{z["rr_zone"]}</strong> depuis la zone contre '
                        f'<strong>{z["rr_direct"]}</strong> en direct')
            txt = (f'Zone {"de demande" if s["direction"]=="BUY" else "d\'offre"} {badge} à '
                   f'<strong>{z["lo"]:.{nd}f}–{z["hi"]:.{nd}f}</strong>, soit <strong>{z.get("dist_label", str(z["dist_pips"])+" pips")}</strong> '
                   f'{"sous le prix" if s["direction"]=="BUY" else "au-dessus du prix"}{gain}.')
            col = "#fcd34d" if (z["rr_zone"] or 0) > (z["rr_direct"] or 0) * 1.4 else "#94a3b8"
        parts += f'<div style="font-size:11px;color:{col};line-height:1.6">🎯 {txt}</div>'
    return (f'<div style="background:#0a0e1a;border:1px solid #1e293b;border-radius:8px;'
            f'padding:8px 10px;margin-bottom:8px">{parts}</div>')

# ═══════════════ V7 : VENT MACRO — rendements US (FRED) ═══════════════
# Le carry utilise les TAUX DIRECTEURS (photo, bouge toutes les 6 semaines).
# Le marché trade les taux ANTICIPÉS, visibles dans les rendements obligataires.
# Le 19/08 : taux directeur inchangé, rendements en chute → dollar en chute.

def fetch_fred_series(series, n=40):
    if not FRED_KEY: return []
    try:
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": series, "api_key": FRED_KEY, "file_type": "json",
                                 "sort_order": "desc", "limit": n}, timeout=10)
        vals = [(o["date"], float(o["value"])) for o in r.json().get("observations", [])
                if o.get("value") not in (".", "", None)]
        return vals
    except Exception:
        return []

def build_yield_context():
    """Rendements US 10a et 2a + variations 5j/20j en points de base."""
    out = {}
    for key, sid in [("10a", "DGS10"), ("2a", "DGS2")]:
        v = fetch_fred_series(sid)
        if len(v) < 21: continue
        cur = v[0][1]
        out[key] = {"level": cur, "d5": round((cur - v[5][1]) * 100),
                    "d20": round((cur - v[20][1]) * 100), "date": v[0][0]}
    if not out: return None
    d5 = out.get("10a", {}).get("d5", 0)
    if d5 <= -12:   bias, col = "USD sous pression", "#fca5a5"
    elif d5 >= 12:  bias, col = "USD soutenu", "#86efac"
    else:           bias, col = "neutre", "#94a3b8"
    out["bias"] = bias; out["color"] = col; out["d5_10a"] = d5
    return out

def yield_banner_html(s):
    """Bandeau sur les paires impliquant l'USD, quand les rendements bougent nettement."""
    y = YIELD_CTX
    if not y or y.get("bias") == "neutre": return ""
    if s.get("asset_class") == "Forex":
        cur = FX_PAIRS.get(s.get("pair", ""), {}).get("currencies", ())
        if "USD" not in cur: return ""
        usd_long = (cur[0] == "USD" and s.get("direction") == "BUY") or \
                   (cur[1] == "USD" and s.get("direction") == "SELL")
    elif s.get("pair") in ("GOLD", "SILVER"):
        usd_long = (s.get("direction") == "SELL")
    else:
        return ""
    if s.get("direction") == "NEUTRAL": return ""
    d5 = y["d5_10a"]
    contre = (usd_long and d5 <= -12) or ((not usd_long) and d5 >= 12)
    txt = (f'Rendement US 10a {d5:+d} bp sur 5j ({y["10a"]["level"]:.2f}%) — '
           + ("<strong>vent contraire structurel</strong> : le marché anticipe des taux plus bas, "
              "le carry se vide plus vite qu\'il ne rapporte." if contre else
              "<strong>vent porteur</strong> : le différentiel anticipé joue pour toi."))
    col = "#fca5a5" if contre else "#86efac"
    return (f'<div style="font-size:10px;color:{col};background:rgba(0,0,0,.2);border-left:3px solid {col};'
            f'border-radius:0 6px 6px 0;padding:6px 10px;margin-bottom:8px">🌊 {txt}</div>')

def yield_block_html():
    y = YIELD_CTX
    if not y:
        return ('<div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:12px;'
                'margin-top:14px;font-size:12px;color:#64748b">🌊 Rendements US indisponibles (FRED).</div>')
    rows = ""
    for k in ("10a", "2a"):
        if k not in y: continue
        d = y[k]
        c5 = "#fca5a5" if d["d5"] < 0 else ("#86efac" if d["d5"] > 0 else "#94a3b8")
        rows += (f'<div style="display:flex;gap:14px;font-size:12px;margin-bottom:4px">'
                 f'<span style="width:60px;color:#94a3b8">US {k}</span>'
                 f'<span style="font-family:monospace;color:#e2e8f0;width:60px">{d["level"]:.2f}%</span>'
                 f'<span style="font-family:monospace;color:{c5};width:90px">{d["d5"]:+d} bp / 5j</span>'
                 f'<span style="font-family:monospace;color:#64748b">{d["d20"]:+d} bp / 20j</span></div>')
    return (f'<div style="background:#111827;border:1px solid #1e293b;border-radius:12px;padding:14px;margin-top:14px">'
            f'<div style="font-size:13px;font-weight:700;color:#e2e8f0;margin-bottom:4px">🌊 Vent macro — rendements US</div>'
            f'<div style="font-size:10px;color:#64748b;margin-bottom:10px;line-height:1.6">'
            f'Le carry mesure les taux DIRECTEURS (photo). Les rendements mesurent les taux ANTICIPÉS (le film). '
            f'Quand ils divergent, c\'est le rendement qui gagne à court terme. '
            f'Biais actuel : <strong style="color:{y["color"]}">{y["bias"]}</strong>.</div>{rows}</div>')


# ═══════════════ V5 : fonctions d'observation (scores v4 intacts) ═══════════════

def fresh_momentum(closes, atr_val):
    """Impulsion anormale 1-3 jours (chocs macro type FOMC). (flag, data)"""
    if closes is None or len(closes) < 5 or atr_val is None or atr_val <= 0:
        return False, None
    m1 = float(closes.iloc[-1] - closes.iloc[-2]) / atr_val
    m3 = float(closes.iloc[-1] - closes.iloc[-4]) / atr_val
    flag = abs(m1) >= 1.5 or abs(m3) >= 2.5
    direction = "haussière" if (m3 if abs(m3) > abs(m1) else m1) > 0 else "baissière"
    return flag, {"m1_atr": round(m1, 2), "m3_atr": round(m3, 2), "dir": direction}

def detect_sd_zones(closes, highs, lows, atr_val, lookback=180, max_zones=2):
    """Zones S/D : base étroite (≤1.2 ATR) + départ impulsif (≥1.5 ATR). Fraîche = non retestée."""
    if closes is None or len(closes) < 30 or atr_val is None or atr_val <= 0:
        return [], []
    c = closes.iloc[-lookback:] if len(closes) > lookback else closes
    h = highs.iloc[-lookback:] if len(highs) > lookback else highs
    l = lows.iloc[-lookback:] if len(lows) > lookback else lows
    n = len(c); cur = float(c.iloc[-1])
    demand, supply = [], []
    i = 2
    while i < n - 3:
        matched = False
        for base_len in (1, 2, 3, 4):
            if i + base_len + 2 >= n:
                break
            base_hi = float(h.iloc[i:i+base_len].max())
            base_lo = float(l.iloc[i:i+base_len].min())
            if (base_hi - base_lo) > 1.2 * atr_val:
                continue
            after = float(c.iloc[i+base_len+1]) - float(c.iloc[i+base_len-1])
            if after >= 1.5 * atr_val:
                revisited = bool((l.iloc[i+base_len+2:] <= base_hi).any())
                demand.append({"lo": base_lo, "hi": base_hi, "fresh": not revisited,
                               "strength": round(after / atr_val, 1)})
                i += base_len + 1; matched = True; break
            elif after <= -1.5 * atr_val:
                revisited = bool((h.iloc[i+base_len+2:] >= base_lo).any())
                supply.append({"lo": base_lo, "hi": base_hi, "fresh": not revisited,
                               "strength": round(-after / atr_val, 1)})
                i += base_len + 1; matched = True; break
        if not matched:
            i += 1
    demand = [z for z in demand if z["hi"] < cur]
    supply = [z for z in supply if z["lo"] > cur]
    demand.sort(key=lambda z: (not z["fresh"], cur - z["hi"]))
    supply.sort(key=lambda z: (not z["fresh"], z["lo"] - cur))
    return demand[:max_zones], supply[:max_zones]

def exit_plan_2steps(sig, nd=5):
    """Sortie 2 temps sur le SL FINAL, plafonnée au TP1 (compression signalée)."""
    d = sig["direction"]
    if d == "NEUTRAL": return None
    entry = sig["price"]; sl = sig["sl"]; tp1 = sig.get("tp1")
    r = abs(entry - sl)
    if r <= 0: return None
    compressed = False
    if d == "BUY":
        t1 = entry + 1.5 * r; be = entry + 1.0 * r
        if tp1 is not None:
            if t1 > tp1: t1 = tp1; compressed = True
            if be > tp1: be = tp1
    else:
        t1 = entry - 1.5 * r; be = entry - 1.0 * r
        if tp1 is not None:
            if t1 < tp1: t1 = tp1; compressed = True
            if be < tp1: be = tp1
    return {"t1": round(t1, nd), "be_trigger": round(be, nd), "compressed": compressed}

# ── VERDICT DE TIMING UNIFIÉ : une seule bannière, une seule phrase ──
def unified_timing(sig):
    """
    Fusionne maturité + momentum frais + extension en UN verdict :
    (label, couleur, phrase unique). Remplace les 3 bandeaux empilés.
    """
    d = sig["direction"]
    if d == "NEUTRAL":
        return ("⚖️ NEUTRE", "#64748b", "Facteurs contradictoires — détails dans l'analyse ci-dessous.")
    fresh = sig.get("fresh_data") or {}
    fresh_flag = sig.get("fresh_flag", False)
    imp = fresh.get("dir", "")
    against = fresh_flag and ((d == "BUY" and imp == "baissière") or (d == "SELL" and imp == "haussière"))
    with_ = fresh_flag and not against
    h4 = sig.get("h4_dir", "NEUTRAL")
    h4_aligned = (d == "BUY" and h4 == "BULLISH") or (d == "SELL" and h4 == "BEARISH")
    h4_diverge = (d == "BUY" and h4 == "BEARISH") or (d == "SELL" and h4 == "BULLISH")
    dist = sig.get("dist_ema20_atr", 0)
    extended = abs(dist) > 1.5
    stats = f"({fresh.get('m1_atr',0):+.1f} ATR/1j, {fresh.get('m3_atr',0):+.1f} ATR/3j)"

    # ROUGE — ne pas entrer
    if against:
        verb = "chute" if imp == "baissière" else "hausse"
        return ("🔴 PAS MAINTENANT", "#ef4444",
                f"{verb.capitalize()} violente en cours {stats} contre ton signal — couteau qui tombe. "
                f"Attends que le prix forme une base (bougie de rejet, petit creux plus haut).")
    if h4_diverge:
        return ("🔴 PAS MAINTENANT", "#ef4444",
                "Le H4 contredit le Daily — c'est le trade GBP/JPY à ne pas refaire. Attends le réalignement.")
    # JAUNE — préparer, pas exécuter
    if with_:
        return ("🟡 ATTENDS LE RETRACEMENT", "#f59e0b",
                f"Impulsion {imp} {stats} dans ton sens — ne chasse pas le sommet, "
                f"laisse le prix respirer et entre sur le repli.")
    if extended:
        side = "au-dessus" if dist > 0 else "en-dessous"
        return ("🟡 PRIX ÉTIRÉ", "#f59e0b",
                f"Le prix est à {abs(dist):.1f} ATR {side} de sa moyenne — entrée tardive. "
                f"Attends le pullback vers l'EMA20 (meilleur RR).")
    if not h4_aligned:
        return ("🟡 EN FORMATION", "#f59e0b",
                "Le H4 n'a pas encore confirmé le Daily. Prépare le plan, attends la confirmation.")
    # VERT
    return ("🟢 TIMING OK", "#22c55e",
            "H4 aligné, prix pas étiré, pas de choc en cours — applique le plan ci-dessous.")

def timing_banner_html(s):
    label, color, phrase = s.get("timing", ("", "#64748b", ""))
    if not label: return ""
    return (f'<div style="display:flex;align-items:flex-start;gap:10px;background:rgba(0,0,0,.25);'
            f'border-left:3px solid {color};border-radius:0 8px 8px 0;padding:9px 12px;margin-bottom:10px">'
            f'<span style="font-size:12px;font-weight:700;color:{color};white-space:nowrap">{label}</span>'
            f'<span style="font-size:11px;color:#94a3b8;line-height:1.55">{phrase}</span></div>')

def details_wrap(title, inner):
    """Section repliée par défaut — un clic pour ouvrir."""
    if not inner: return ""
    return (f'<details style="margin-top:8px"><summary style="font-size:10px;color:#64748b;cursor:pointer;'
            f'user-select:none;text-transform:uppercase;letter-spacing:.04em">{title}</summary>'
            f'<div style="margin-top:8px">{inner}</div></details>')

def sd_zones_inner(s, nd=5):
    dz = s.get("sd_demand", []); sz = s.get("sd_supply", [])
    rows = ""
    for z in sz:
        badge = '🌱 fraîche' if z["fresh"] else '♻️ testée'
        rows += (f'<div style="display:flex;justify-content:space-between;font-size:11px;background:rgba(239,68,68,.08);'
                 f'border-left:3px solid #ef4444;border-radius:0 6px 6px 0;padding:5px 10px;margin-bottom:4px">'
                 f'<span style="color:#fca5a5;font-family:monospace">OFFRE {z["lo"]:.{nd}f} → {z["hi"]:.{nd}f}</span>'
                 f'<span style="color:#94a3b8">{badge} · {z["strength"]}×ATR</span></div>')
    for z in dz:
        badge = '🌱 fraîche' if z["fresh"] else '♻️ testée'
        rows += (f'<div style="display:flex;justify-content:space-between;font-size:11px;background:rgba(34,197,94,.08);'
                 f'border-left:3px solid #22c55e;border-radius:0 6px 6px 0;padding:5px 10px;margin-bottom:4px">'
                 f'<span style="color:#86efac;font-family:monospace">DEMANDE {z["lo"]:.{nd}f} → {z["hi"]:.{nd}f}</span>'
                 f'<span style="color:#94a3b8">{badge} · {z["strength"]}×ATR</span></div>')
    sr = ""
    for r_ in s.get("res", [])[:2]:
        sr += f'<span style="font-size:10px;padding:1px 8px;background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.4);border-radius:3px;color:#fca5a5;font-family:monospace;margin-right:4px">R {r_}</span>'
    for sp in s.get("sup", [])[:2]:
        sr += f'<span style="font-size:10px;padding:1px 8px;background:rgba(34,197,94,.15);border:1px solid rgba(34,197,94,.4);border-radius:3px;color:#86efac;font-family:monospace;margin-right:4px">S {sp}</span>'
    if sr:
        rows += f'<div style="margin-top:6px">{sr}</div>'
    return rows


def neutral_explanation(sig):
    """Pour les cartes NEUTRES : POURQUOI c'est neutre — la contradiction est une info (cas AUD/NZD)."""
    bull, bear = [], []
    if sig["s_carry"] >= 60: bull.append(f"carry favorable ({sig['carry_diff']:+.2f}%)")
    elif sig["s_carry"] <= 40: bear.append(f"carry défavorable ({sig['carry_diff']:+.2f}%)")
    if sig["s_mom"] >= 65: bull.append(f"momentum fort (top {100-sig['s_mom']:.0f}% univers)")
    elif sig["s_mom"] <= 35: bear.append(f"momentum faible (bottom {sig['s_mom']:.0f}%)")
    if sig["ema_trend"] == "BULLISH": bull.append("EMAs alignées haussières")
    elif sig["ema_trend"] == "BEARISH": bear.append("EMAs alignées baissières")
    if sig["h4_dir"] == "BULLISH": bull.append("H4 haussier")
    elif sig["h4_dir"] == "BEARISH": bear.append("H4 baissier")
    if sig["s_dxy"] >= 60: bull.append("DXY favorable")
    elif sig["s_dxy"] <= 40: bear.append("DXY défavorable")
    if not bull and not bear:
        return "Tous les facteurs sont au point mort — vraiment rien à voir ici."
    return ("⚖️ Facteurs contradictoires — c'est parfois là que se cache un retournement précoce que le score ne capte pas (cf. ton AUD/NZD). "
            + ("Côté haussier : " + ", ".join(bull) + ". " if bull else "")
            + ("Côté baissier : " + ", ".join(bear) + "." if bear else "")
            + " À toi de lire la structure sur le chart si un côté t'interpelle.")


# ═══════════════ DONNÉES FOREX (Daily 1y + H4 60j) ═══════════════
import yfinance as yf

print("📥 [1/6] Téléchargement données FOREX + Macro...")
fx_tickers    = [v["ticker"] for v in FX_PAIRS.values()]
MACRO_TICKERS = {"DXY":"DX-Y.NYB","VIX":"^VIX","GOLD":"GC=F","WTI":"CL=F"}
macro_tickers = list(MACRO_TICKERS.values())

raw_d  = yf.download(fx_tickers + macro_tickers, period="1y",  interval="1d",
                     auto_adjust=True, progress=False, group_by="ticker")
raw_h4 = yf.download(fx_tickers, period="60d", interval="4h",
                     auto_adjust=True, progress=False, group_by="ticker")

closes_d, highs_d, lows_d, closes_h4, macro_data = {}, {}, {}, {}, {}
for pair, meta in FX_PAIRS.items():
    t = meta["ticker"]
    try:
        if t in raw_d.columns.get_level_values(0):
            closes_d[pair] = raw_d[t]["Close"].dropna()
            highs_d[pair]  = raw_d[t]["High"].dropna()
            lows_d[pair]   = raw_d[t]["Low"].dropna()
    except Exception: pass
    try:
        if t in raw_h4.columns.get_level_values(0):
            closes_h4[pair] = raw_h4[t]["Close"].dropna()
    except Exception: pass
for name, t in MACRO_TICKERS.items():
    try:
        if t in raw_d.columns.get_level_values(0):
            macro_data[name] = raw_d[t]["Close"].dropna()
    except Exception: pass

available = list(closes_d.keys())
print(f"   ✅ {len(available)}/{len(FX_PAIRS)} paires | macro : {', '.join(macro_data.keys())}")

# ═══════════════ CALCUL SIGNAUX FOREX (moteur inchangé + enrichissement v4) ═══════════════
print("🌊 [2a/6] Rendements US (FRED)...")
YIELD_CTX = build_yield_context()
if YIELD_CTX:
    print(f"   ✅ US 10a {YIELD_CTX['10a']['level']:.2f}% ({YIELD_CTX['10a']['d5']:+d} bp/5j) · biais {YIELD_CTX['bias']}")
else:
    print("   ⚠️ Rendements indisponibles — le dashboard fonctionne sans")

print("🐘 [2b/6] Positionnement COT (CFTC)...")
COT_DATA = fetch_cot_data()
if COT_DATA:
    _n_ext = sum(1 for d in COT_DATA.values() if d["extreme"])
    print(f"   ✅ COT : {len(COT_DATA)} marchés · {_n_ext} positionnement(s) extrême(s)")
else:
    print("   ⚠️ COT indisponible — le dashboard fonctionne sans")

print("📊 [2c/6] Signaux forex...")
all_mom_raw = {p: momentum_raw(closes_d.get(p)) for p in FX_PAIRS}

signals = []
for pair in FX_PAIRS:
    try:
        sig = compute_signal(pair, closes_d, highs_d, lows_d, closes_h4, macro_data, all_mom_raw)
        if sig:
            # ── Enrichissement v4 (n'altère PAS le calcul existant) ──
            mat_label, mat_color, mat_note = compute_maturity(sig, closes_d.get(pair), highs_d.get(pair), lows_d.get(pair))
            sig["maturity"] = mat_label; sig["maturity_color"] = mat_color; sig["maturity_note"] = mat_note
            sig["plan"] = double_entry_plan(sig)
            # ── Harmonisation : le SL anti-liquidité (s'il existe) devient LE SL officiel ──
            # → le bloc principal, les RR, le sizing et la sortie 2 temps affichent le même SL
            if sig["plan"] and sig["plan"]["direct"].get("adjusted"):
                _d = sig["plan"]["direct"]
                sig["sl"] = _d["sl"]
                sig["sl_pips"] = _d["sl_pips"]
                _r_dist = abs(sig["price"] - sig["sl"])
                if _r_dist > 0:
                    sig["rr1"] = round(abs(sig["tp1"] - sig["price"]) / _r_dist, 2)
                    sig["rr2"] = round(abs(sig["tp2"] - sig["price"]) / _r_dist, 2)
                sig["sl_adjusted"] = True
            if sig["direction"] == "NEUTRAL":
                sig["neutral_why"] = neutral_explanation(sig)
            sig["asset_class"] = "Forex"
            # ── V5 : couches d'observation + verdict unifié ──
            _av = sig.get("atr", 0)
            sig["fresh_flag"], sig["fresh_data"] = fresh_momentum(closes_d.get(pair), _av)
            sig["sd_demand"], sig["sd_supply"] = detect_sd_zones(
                closes_d.get(pair), highs_d.get(pair), lows_d.get(pair), _av)
            sig["exit_plan"] = exit_plan_2steps(sig)
            sig["timing"] = unified_timing(sig)
            sig["mom_h"] = mom_agreement(closes_d.get(pair))
            sig["shock"] = shock_memory(closes_d.get(pair), _av)
            sig["zone_ctx"] = zone_context(sig)
            signals.append(sig)
    except Exception as e:
        print(f"   ⚠️ {pair} : {e}")

fx_buys    = sorted([s for s in signals if s["direction"]=="BUY"],    key=lambda x: x["conviction"], reverse=True)
fx_sells   = sorted([s for s in signals if s["direction"]=="SELL"],   key=lambda x: x["conviction"], reverse=True)
fx_neutral = sorted([s for s in signals if s["direction"]=="NEUTRAL"],key=lambda x: x["score"],      reverse=True)
print(f"   ✅ {len(fx_buys)} BUY · {len(fx_sells)} SELL · {len(fx_neutral)} NEUTRAL")

RESULTS["fx_signals"] = signals
RESULTS["macro"] = macro_data
RESULTS["closes_d"] = closes_d; RESULTS["highs_d"] = highs_d; RESULTS["lows_d"] = lows_d
RESULTS["closes_h4"] = closes_h4

# ═══════════════ FRAGMENT HTML FOREX ═══════════════

def _plan_block(s):
    """Bloc double entrée + sizing + anti-liquidité"""
    p = s.get("plan")
    if not p: return ""
    d = p["direct"]
    rows = f'''<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
      <div style="background:#1f2937;border-radius:8px;padding:9px">
        <div style="font-size:9px;color:#64748b;text-transform:uppercase;margin-bottom:4px">⚡ Entrée directe (maintenant)</div>
        <div style="font-size:11px;color:#cbd5e1;line-height:1.7">
          Entrée <span style="font-family:monospace">{d["entry"]:.5f}</span> · SL <span style="font-family:monospace;color:#fca5a5">{d["sl"]:.5f}</span> (−{d["sl_pips"]} pips)<br>
          RR vers TP1 : <strong style="color:{'#86efac' if d['rr1']>=1.3 else '#fcd34d'}">{d["rr1"]}</strong> · Taille : <strong>{d["lots"]} lot</strong> <span style="color:#64748b">(risque {p["risk_amount"]:.0f}$)</span>
        </div>
      </div>'''
    if p["pullback"]:
        pb = p["pullback"]
        rows += f'''<div style="background:#1f2937;border:1px solid rgba(34,197,94,.25);border-radius:8px;padding:9px">
        <div style="font-size:9px;color:#86efac;text-transform:uppercase;margin-bottom:4px">🎯 Entrée pullback (zone EMA20)</div>
        <div style="font-size:11px;color:#cbd5e1;line-height:1.7">
          Entrée <span style="font-family:monospace">{pb["entry"]:.5f}</span> · SL <span style="font-family:monospace;color:#fca5a5">{pb["sl"]:.5f}</span> (−{pb["sl_pips"]} pips)<br>
          RR vers TP1 : <strong style="color:#86efac">{pb["rr1"]}</strong> · Taille : <strong>{pb["lots"]} lot</strong> <span style="color:#64748b">— RR supérieur si le retracement vient</span>
        </div>
      </div>'''
    else:
        if str(s.get("maturity","")).startswith("🔴"):
            rows += '''<div style="background:#1f2937;border:1px solid rgba(239,68,68,.25);border-radius:8px;padding:9px;display:flex;align-items:center">
        <div style="font-size:11px;color:#fca5a5;line-height:1.6">Prix proche de l'EMA20 (zone fraîche) MAIS signal 🔴 PAS MÛR — attends la stabilisation avant d'exploiter cette zone.</div></div>'''
        else:
            rows += '''<div style="background:#1f2937;border-radius:8px;padding:9px;display:flex;align-items:center">
        <div style="font-size:11px;color:#64748b;line-height:1.6">Le prix est déjà dans la zone pullback (proche EMA20) — l'entrée directe EST l'entrée fraîche.</div></div>'''
    rows += "</div>"
    notes = ""
    if d.get("adjusted"):
        _rr_warn = ' ⚠️ Conséquence : SL élargi → RR TP1 = ' + str(d["rr1"]) + (' — setup peu attractif en entrée directe, privilégier le pullback ou passer.' if d["rr1"] < 1 else '.')
        notes += f'<div style="font-size:10px;color:#fcd34d;background:rgba(245,158,11,.08);border-left:3px solid #f59e0b;border-radius:0 6px 6px 0;padding:6px 10px;margin-bottom:8px">🛡️ {d["note"]}{_rr_warn}</div>'
    if p["pullback"] and p["pullback"].get("adjusted"):
        notes += f'<div style="font-size:10px;color:#fcd34d;background:rgba(245,158,11,.08);border-left:3px solid #f59e0b;border-radius:0 6px 6px 0;padding:6px 10px;margin-bottom:8px">🛡️ {p["pullback"]["note"]}</div>'
    return rows + notes

def _maturity_badge(s):
    if s.get("maturity","—") == "—": return ""
    return (f'<div style="display:flex;align-items:flex-start;gap:8px;background:rgba(0,0,0,.25);'
            f'border-left:3px solid {s["maturity_color"]};border-radius:0 8px 8px 0;padding:8px 12px;margin-bottom:10px">'
            f'<span style="font-size:13px;font-weight:700;color:{s["maturity_color"]};white-space:nowrap">{s["maturity"]}</span>'
            f'<span style="font-size:11px;color:#94a3b8;line-height:1.6">{s["maturity_note"]}</span></div>')

def build_card_v5(s):
    """Carte V5 clean — 3 questions : QUOI (header) · MAINTENANT (verdict unique) · COMMENT (plan compact).
       Tout le reste replié dans des <details>."""
    col  = "#22c55e" if s["direction"]=="BUY" else ("#ef4444" if s["direction"]=="SELL" else "#94a3b8")
    icon = "↑" if s["direction"]=="BUY" else ("↓" if s["direction"]=="SELL" else "→")
    em_b = ' <span style="font-size:9px;color:#f59e0b;background:#431407;padding:1px 6px;border-radius:3px">EM</span>' if s.get("em") else ""
    blk  = ' <span style="color:#ef4444;font-size:10px">⛔ VIX</span>' if s.get("em_blocked") else ""

    # ── 1. QUOI ──
    header = f'''
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:9px">
        <div style="display:flex;align-items:center;gap:8px">
          <span style="background:{col};color:#fff;font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px">{icon} {s['direction']}</span>
          <span style="font-size:16px;font-weight:600;font-family:monospace;color:#e2e8f0">{s['label']}</span>{em_b}{blk}
        </div>
        <div style="display:flex;align-items:baseline;gap:10px">
          <span style="font-size:10px;color:#64748b;font-family:monospace">score {s['score']:.0f}</span>
          <span style="font-size:21px;font-weight:700;color:{col};font-family:monospace">{s['conviction']:.0f}<span style="font-size:10px;color:#64748b">%</span></span>
        </div>
      </div>'''

    # ── 2. MAINTENANT (verdict unique) ──
    verdict = timing_banner_html(s)

    cot_chips = cot_chip_html(s)

    # ── 3. COMMENT (plan compact) ──
    plan_html = ""
    if s["direction"] != "NEUTRAL":
        p = s.get("plan") or {}
        d = p.get("direct", {})
        ep = s.get("exit_plan") or {}
        shield = ' <span title="SL décalé sous la zone de liquidité évidente (anti stop-hunt)" style="cursor:help">🛡️</span>' if s.get("sl_adjusted") else ""
        rr_c = "#86efac" if s["rr1"] >= 1.3 else ("#fcd34d" if s["rr1"] >= 1 else "#fca5a5")
        cells = f'''
        <div style="background:#1f2937;border-radius:7px;padding:7px;text-align:center">
          <div style="font-size:8px;color:#64748b;text-transform:uppercase">Entrée</div>
          <div style="font-family:monospace;font-size:12px;color:#e2e8f0">{s['price']:.5f}</div></div>
        <div style="background:#1f2937;border-radius:7px;padding:7px;text-align:center">
          <div style="font-size:8px;color:#64748b;text-transform:uppercase">Stop{shield}</div>
          <div style="font-family:monospace;font-size:12px;color:#fca5a5">{s['sl']:.5f}</div>
          <div style="font-size:8px;color:#64748b">−{s['sl_pips']}p</div></div>
        <div style="background:#1f2937;border-radius:7px;padding:7px;text-align:center">
          <div style="font-size:8px;color:#64748b;text-transform:uppercase">TP1 · RR <span style="color:{rr_c}">{s['rr1']}</span></div>
          <div style="font-family:monospace;font-size:12px;color:#86efac">{s['tp1']:.5f}</div>
          <div style="font-size:8px;color:#64748b">+{s['tp1_pips']}p</div></div>
        <div style="background:#1f2937;border-radius:7px;padding:7px;text-align:center">
          <div style="font-size:8px;color:#64748b;text-transform:uppercase">TP2 · RR {s['rr2']}</div>
          <div style="font-family:monospace;font-size:12px;color:#86efac">{s['tp2']:.5f}</div>
          <div style="font-size:8px;color:#64748b">+{s['tp2_pips']}p</div></div>'''
        exit_txt = ""
        if ep:
            if ep.get("compressed"):
                exit_txt = f"Sécurise ½ au <strong>TP1 {ep['t1']:.5f}</strong> (SL élargi compresse le RR) · BE dès {ep['be_trigger']:.5f}"
            else:
                exit_txt = f"Sécurise ½ à <strong>{ep['t1']:.5f}</strong> (1.5R) · stop à BE dès <strong>{ep['be_trigger']:.5f}</strong> (1R)"
        _pv = pip_value_usd(s.get("pair","")) if s.get("asset_class") == "Forex" else None
        size_txt = (f"{d.get('lots','?')} lot · risque {p.get('risk_amount',0):.0f}$"
                    + (f" · pip ≈ {_pv:.2f}$/lot" if _pv and _pv < 5 else "")) if d else ""
        pb = p.get("pullback")
        pb_txt = f' · <span style="color:#86efac">Alt. pullback : entrée {pb["entry"]:.5f} → RR {pb["rr1"]}</span>' if pb else ""
        warn = ""
        if s["rr1"] < 1:
            warn = '<div style="font-size:10px;color:#fca5a5;margin-top:5px">⚠️ RR &lt; 1 en entrée directe — privilégier le pullback ou passer.</div>'
        plan_html = f'''
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:7px">{cells}</div>
      <div style="font-size:11px;color:#93c5fd;line-height:1.65;background:rgba(59,130,246,.07);border-radius:7px;padding:7px 10px">🎯 {exit_txt} · <span style="color:#94a3b8">{size_txt}</span>{pb_txt}</div>
      {warn}'''

    # ── Pills essentielles (1 ligne) ──
    rsi_c = "#fca5a5" if s["rsi"]>70 else ("#86efac" if s["rsi"]<30 else "#94a3b8")
    ema_ok = (s["direction"]=="BUY" and s["ema_trend"]=="BULLISH") or (s["direction"]=="SELL" and s["ema_trend"]=="BEARISH")
    h4_ok  = (s["direction"]=="BUY" and s["h4_dir"]=="BULLISH")   or (s["direction"]=="SELL" and s["h4_dir"]=="BEARISH")
    el = s.get("entry_label","?")
    el_c = "#fca5a5" if el=="Extension" else ("#86efac" if el=="Pullback" else "#94a3b8")
    pills = f'''
      <div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:8px">
        <span style="font-size:10px;padding:2px 8px;background:#1f2937;border-radius:20px;color:{rsi_c}">RSI {s['rsi']:.0f}</span>
        <span style="font-size:10px;padding:2px 8px;background:#1f2937;border-radius:20px">{"✅" if ema_ok else "⚠️"} EMA {s['ema_trend']}</span>
        <span style="font-size:10px;padding:2px 8px;background:#1f2937;border-radius:20px">{"✅" if h4_ok else "➖"} H4 {s['h4_dir']}</span>
        <span style="font-size:10px;padding:2px 8px;background:#1f2937;border-radius:20px">Carry {s['carry_diff']:+.2f}%</span>
        <span style="font-size:10px;padding:2px 8px;background:#1f2937;border-radius:20px;color:{el_c}">📏 {el} {s.get('dist_ema20_atr',0):+.2f}</span>
        {mom_pill_html(s)}
      </div>'''

    # ── Détails repliés ──
    resume, _, tech = s["explanation"].partition(" ||| ")
    neutral_block = ""
    if s["direction"]=="NEUTRAL" and s.get("neutral_why"):
        neutral_block = f'<div style="font-size:12px;color:#cbd5e1;line-height:1.7;margin-bottom:8px">{s["neutral_why"]}</div>'
    factors = "".join(
        f'<div style="display:flex;align-items:center;gap:8px;font-size:11px"><span style="width:70px;color:#64748b">{n}</span>'
        f'<div style="flex:1;height:3px;background:#1e293b;border-radius:2px"><div style="width:{v}%;height:100%;background:{c2};border-radius:2px"></div></div>'
        f'<span style="font-family:monospace;color:#94a3b8;width:28px;text-align:right">{v:.0f}</span></div>'
        for n,v,c2 in [("Carry",s["s_carry"],"#3b82f6"),("Momentum",s["s_mom"],"#8b5cf6"),
                       ("PPP",s["s_ppp"],"#f59e0b"),("DXY",s["s_dxy"],"#06b6d4")])
    analysis_inner = f'''{neutral_block}
      <div style="font-size:12px;color:#e2e8f0;line-height:1.7;margin-bottom:8px">{resume}</div>
      <div style="font-size:11px;color:#94a3b8;line-height:1.65;margin-bottom:10px">{tech if tech else ""}</div>
      <div style="display:flex;flex-direction:column;gap:4px">{factors}</div>'''
    details = (details_wrap("📖 Analyse complète", analysis_inner)
               + details_wrap("🗺️ Zones &amp; niveaux", sd_zones_inner(s)))

    return f'''
    <div class="sig-card" data-dir="{s['direction']}" style="background:#111827;border:1px solid #1e293b;border-radius:12px;padding:14px;margin-bottom:10px">
      {header}{verdict}{shock_html(s)}{yield_banner_html(s)}{cot_chips}{zone_visual_html(s)}{plan_html}{pills}{details}
    </div>'''

build_card_v4 = build_card_v5  # le fragment utilise la carte clean

# Construire le fragment forex avec sous-onglets (TOUS les neutres affichés)
_fx_buy  = "".join(build_card_v4(s) for s in fx_buys)  or '<div style="color:#64748b;text-align:center;padding:20px">Aucun signal BUY aujourd\'hui</div>'
_fx_sell = "".join(build_card_v4(s) for s in fx_sells) or '<div style="color:#64748b;text-align:center;padding:20px">Aucun signal SELL aujourd\'hui</div>'
_fx_neu  = "".join(build_card_v4(s) for s in fx_neutral) or '<div style="color:#64748b;text-align:center;padding:20px">Aucune paire neutre</div>'

FRAGMENTS["forex"] = f"""
<div style="padding:0 0 8px">
  <div style="display:flex;gap:4px;border-bottom:1px solid #1e293b;margin-bottom:14px;flex-wrap:wrap">
    <span class="sub-tab act" onclick="subTab('fx','buy',this)">↑ BUY ({len(fx_buys)})</span>
    <span class="sub-tab" onclick="subTab('fx','sell',this)">↓ SELL ({len(fx_sells)})</span>
    <span class="sub-tab" onclick="subTab('fx','neu',this)">⚖️ NEUTRES ({len(fx_neutral)})</span>
  </div>
  <div id="fx-buy"  class="sub-tc act">{_fx_buy}</div>
  <div id="fx-sell" class="sub-tc">{_fx_sell}</div>
  <div id="fx-neu"  class="sub-tc">
    <div style="font-size:12px;color:#94a3b8;background:#1f2937;border-radius:8px;padding:10px;margin-bottom:12px;line-height:1.6">
      💡 Un NEUTRE = facteurs contradictoires, pas "rien à voir". Chaque carte explique la contradiction —
      c'est parfois là que se cache un retournement précoce que le score ne capte pas encore.
    </div>
    {_fx_neu}
  </div>
</div>"""
print(f"   ✅ Fragment forex généré ({len(signals)} cartes complètes, y compris tous les neutres)")

# ╔══════════════════════════════════════════════════════════╗
# ║  Cellule 3/5 : MULTI-ACTIFS — V7                         ║
# ║  DXY · Indices · Métaux · circuit-breaker Twelve Data    ║
# ║  Harmonisés v4 : maturité · timing · plan · S/R          ║
# ╚══════════════════════════════════════════════════════════╝

# ── Helpers partagés indices/métaux (plan générique + badges HTML) ──

def generic_plan(sig):
    """Plan de risque générique pour indices/commodities : sizing en unités + entrée pullback EMA20."""
    d = sig["direction"]
    if d == "NEUTRAL": return None
    cur = sig["price"]; sl = sig["sl"]; tp1 = sig["tp1"]
    atr_v = sig.get("atr", 0); e20 = sig.get("ema20", cur)
    risk_amount = CAPITAL * RISK_PER_TRADE
    dist_sl = abs(cur - sl)
    units = round(risk_amount / dist_sl, 2) if dist_sl > 0 else 0
    rr1 = round(abs(tp1 - cur) / dist_sl, 2) if dist_sl > 0 else 0
    pb = None
    if atr_v > 0:
        if d == "BUY" and cur > e20 + 0.15 * atr_v:
            pb_entry = e20
            pb_sl = pb_entry - ATR_MULT_SL * atr_v
            pb_rr = round(abs(tp1 - pb_entry) / abs(pb_entry - pb_sl), 2)
            pb = {"entry": round(pb_entry, 4), "sl": round(pb_sl, 4), "rr1": pb_rr}
        elif d == "SELL" and cur < e20 - 0.15 * atr_v:
            pb_entry = e20
            pb_sl = pb_entry + ATR_MULT_SL * atr_v
            pb_rr = round(abs(tp1 - pb_entry) / abs(pb_entry - pb_sl), 2)
            pb = {"entry": round(pb_entry, 4), "sl": round(pb_sl, 4), "rr1": pb_rr}
    return {"risk_amount": round(risk_amount, 2), "units": units, "rr1": rr1, "pullback": pb}

def maturity_badge_html(s):
    if s.get("maturity", "—") in ("—", None): return ""
    return (f'<div style="display:flex;align-items:flex-start;gap:8px;background:rgba(0,0,0,.25);'
            f'border-left:3px solid {s["maturity_color"]};border-radius:0 8px 8px 0;padding:8px 12px;margin-bottom:10px">'
            f'<span style="font-size:13px;font-weight:700;color:{s["maturity_color"]};white-space:nowrap">{s["maturity"]}</span>'
            f'<span style="font-size:11px;color:#94a3b8;line-height:1.6">{s["maturity_note"]}</span></div>')

def plan_generic_html(s):
    p = s.get("plan_generic")
    if not p: return ""
    pb_html = ""
    if p["pullback"]:
        pb = p["pullback"]
        pb_html = (f'<div style="background:#1f2937;border:1px solid rgba(34,197,94,.25);border-radius:8px;padding:9px">'
                   f'<div style="font-size:9px;color:#86efac;text-transform:uppercase;margin-bottom:4px">🎯 Entrée pullback (EMA20)</div>'
                   f'<div style="font-size:11px;color:#cbd5e1;line-height:1.7">Entrée <span style="font-family:monospace">{pb["entry"]}</span> · '
                   f'SL <span style="font-family:monospace;color:#fca5a5">{pb["sl"]}</span> · RR <strong style="color:#86efac">{pb["rr1"]}</strong></div></div>')
    else:
        pb_html = ('<div style="background:#1f2937;border-radius:8px;padding:9px;display:flex;align-items:center">'
                   '<div style="font-size:11px;color:#64748b">Prix déjà en zone fraîche (proche EMA20).</div></div>')
    return (f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">'
            f'<div style="background:#1f2937;border-radius:8px;padding:9px">'
            f'<div style="font-size:9px;color:#64748b;text-transform:uppercase;margin-bottom:4px">⚡ Entrée directe + risque</div>'
            f'<div style="font-size:11px;color:#cbd5e1;line-height:1.7">RR vers TP1 : <strong style="color:{"#86efac" if p["rr1"]>=1.3 else "#fcd34d"}">{p["rr1"]}</strong> · '
            f'Taille : <strong>{p["units"]} unités</strong> <span style="color:#64748b">(risque {p["risk_amount"]:.0f}$)</span></div></div>'
            f'{pb_html}</div>')

print("✅ Helpers multi-actifs chargés")


# ═══════════════ SECTION DXY MULTI-TIMEFRAME (logique C8 inchangée) ═══════════════
print("📥 [3/6] Analyse DXY multi-timeframe...")

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import warnings; warnings.filterwarnings("ignore")

# ── TÉLÉCHARGEMENT DXY multi-timeframe ────────────────────────
print("📥 Chargement DXY (Daily / Weekly / Monthly)...")

dxy_d  = yf.download("DX-Y.NYB", period="2y",  interval="1d",  auto_adjust=True, progress=False)
dxy_w  = yf.download("DX-Y.NYB", period="5y",  interval="1wk", auto_adjust=True, progress=False)
dxy_m  = yf.download("DX-Y.NYB", period="10y", interval="1mo", auto_adjust=True, progress=False)
# Spread US10Y - DE10Y (proxy différentiel taux)
us10y  = yf.download("^TNX",   period="2y", interval="1d", auto_adjust=True, progress=False)
de10y  = yf.download("^TENZ.DE" if False else "^TNX", period="2y", interval="1d", auto_adjust=True, progress=False)

# Fallback propre si colonne multi-index
def get_ohlcv(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open","High","Low","Close"]].dropna()

D  = get_ohlcv(dxy_d)
W  = get_ohlcv(dxy_w)
M  = get_ohlcv(dxy_m)

print(f"✅ Daily  : {len(D)} barres  ({D.index[0].date()} → {D.index[-1].date()})")
print(f"✅ Weekly : {len(W)} barres")
print(f"✅ Monthly: {len(M)} barres")

# ── FONCTIONS INDICATEURS ─────────────────────────────────────

def ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(p).mean()
    l = (-d.clip(upper=0)).rolling(p).mean()
    return 100 - 100/(1 + g/l.replace(0, np.nan))

def macd(s, fast=12, slow=26, sig=9):
    m = ema(s,fast) - ema(s,slow)
    signal = ema(m, sig)
    hist   = m - signal
    return m, signal, hist

def atr(h, l, c, p=14):
    prev = c.shift(1)
    tr   = pd.concat([h-l, (h-prev).abs(), (l-prev).abs()], axis=1).max(axis=1)
    return tr.rolling(p).mean()

def bollinger(s, p=20, k=2):
    sma = s.rolling(p).mean()
    std = s.rolling(p).std()
    return sma+k*std, sma-k*std, sma

def roc(s, p):
    return (s/s.shift(p) - 1)*100

def swing_highs_lows(h, l, lookback=3):
    """Détecte les swing highs et lows"""
    highs_idx, lows_idx = [], []
    for i in range(lookback, len(h)-lookback):
        if all(float(h.iloc[i]) >= float(h.iloc[i-j]) for j in range(1,lookback+1)) and            all(float(h.iloc[i]) >= float(h.iloc[i+j]) for j in range(1,lookback+1)):
            highs_idx.append(i)
        if all(float(l.iloc[i]) <= float(l.iloc[i-j]) for j in range(1,lookback+1)) and            all(float(l.iloc[i]) <= float(l.iloc[i+j]) for j in range(1,lookback+1)):
            lows_idx.append(i)
    return highs_idx, lows_idx

def detect_supply_demand(df, lookback=3, impulse_pct=0.003):
    """
    Zones Supply/Demand :
    - Supply : consolidation (base) suivie d'un drop fort → zone = corps de la base
    - Demand : consolidation (base) suivie d'un rally fort → zone = corps de la base
    """
    c = df["Close"]; o = df["Open"]; h = df["High"]; l = df["Low"]
    zones = []
    for i in range(lookback+1, len(c)-1):
        # Bougie impulsive baissière (Supply)
        drop = (float(c.iloc[i]) - float(c.iloc[i-1]))/float(c.iloc[i-1])
        if drop < -impulse_pct:
            # Base = les lookback bougies avant
            base_h = float(h.iloc[i-lookback:i].max())
            base_l = float(l.iloc[i-lookback:i].min())
            zones.append({"type":"supply","top":round(base_h,3),"bot":round(base_l,3),
                          "date":str(df.index[i].date()),"strength":abs(drop)*100})
        # Bougie impulsive haussière (Demand)
        rally = (float(c.iloc[i]) - float(c.iloc[i-1]))/float(c.iloc[i-1])
        if rally > impulse_pct:
            base_h = float(h.iloc[i-lookback:i].max())
            base_l = float(l.iloc[i-lookback:i].min())
            zones.append({"type":"demand","top":round(base_h,3),"bot":round(base_l,3),
                          "date":str(df.index[i].date()),"strength":abs(rally)*100})

    # Garder les zones les plus récentes et non invalidées
    cur = float(c.iloc[-1])
    valid = []
    seen = set()
    for z in sorted(zones, key=lambda x:x["date"], reverse=True):
        key = f"{z['type']}_{z['top']:.2f}"
        if key in seen: continue
        # Supply valide = zone au-dessus du prix actuel
        if z["type"]=="supply" and z["bot"] > cur:
            valid.append(z); seen.add(key)
        # Demand valide = zone en dessous du prix actuel
        elif z["type"]=="demand" and z["top"] < cur:
            valid.append(z); seen.add(key)
        if len(valid) >= 6: break
    return valid

def confluence_levels(levels_d, levels_w, levels_m, tol=0.003):
    """
    Trouve les niveaux présents sur 2+ timeframes (confluence)
    tol = tolérance en pourcentage
    """
    all_levels = (
        [(v,"D") for v in levels_d] +
        [(v,"W") for v in levels_w] +
        [(v,"M") for v in levels_m]
    )
    confluences = []
    used = set()
    for i,(v1,tf1) in enumerate(all_levels):
        if i in used: continue
        group = [(v1,tf1)]; used.add(i)
        for j,(v2,tf2) in enumerate(all_levels):
            if j in used or tf2==tf1: continue
            if abs(v2-v1)/v1 < tol:
                group.append((v2,tf2)); used.add(j)
        if len(group) >= 2:
            avg = round(sum(v for v,_ in group)/len(group), 3)
            tfs = [tf for _,tf in group]
            strength = len(set(tfs))  # 2 = fort, 3 = très fort
            confluences.append({"level":avg,"timeframes":tfs,"strength":strength})
    return sorted(confluences, key=lambda x:x["level"])

def trend_structure(h_idx, l_idx, highs, lows):
    """HH/HL = uptrend, LH/LL = downtrend"""
    if len(h_idx)<2 or len(l_idx)<2: return "UNDEFINED"
    recent_highs = [float(highs.iloc[i]) for i in h_idx[-3:]]
    recent_lows  = [float(lows.iloc[i])  for i in l_idx[-3:]]
    hh = all(recent_highs[i]>recent_highs[i-1] for i in range(1,len(recent_highs)))
    ll = all(recent_lows[i] <recent_lows[i-1]  for i in range(1,len(recent_lows)))
    lh = all(recent_highs[i]<recent_highs[i-1] for i in range(1,len(recent_highs)))
    hl = all(recent_lows[i] >recent_lows[i-1]  for i in range(1,len(recent_lows)))
    if hh and hl: return "UPTREND"
    if lh and ll: return "DOWNTREND"
    if hh and ll: return "EXPANDING"
    if lh and hl: return "CONTRACTING"
    return "MIXED"

# ── CALCUL COMPLET PAR TIMEFRAME ──────────────────────────────

def analyse_tf(df, tf_name, lookback_swing=3):
    c = df["Close"]; h = df["High"]; l = df["Low"]; o = df["Open"]
    cur = float(c.iloc[-1])

    # EMAs
    e20  = float(ema(c,20).iloc[-1])
    e50  = float(ema(c,50).iloc[-1])  if len(c)>=50  else cur
    e200 = float(ema(c,200).iloc[-1]) if len(c)>=200 else cur

    # EMA trend
    if cur>e20>e50>e200:     ema_trend = "BULL FORT"
    elif cur>e20 and e20>e50: ema_trend = "BULL"
    elif cur<e20<e50<e200:   ema_trend = "BEAR FORT"
    elif cur<e20 and e20<e50: ema_trend = "BEAR"
    else:                     ema_trend = "MIXTE"

    # RSI
    r = rsi(c,14)
    rsi_val = round(float(r.iloc[-1]),1)
    # Divergence RSI (5 barres)
    price_dir = float(c.iloc[-1]) - float(c.iloc[-5]) if len(c)>=5 else 0
    rsi_dir   = float(r.iloc[-1])  - float(r.iloc[-5])  if len(r)>=5 else 0
    rsi_div = "BULL_DIV" if price_dir<0 and rsi_dir>0 else               ("BEAR_DIV" if price_dir>0 and rsi_dir<0 else "NONE")

    # MACD
    ml, ms, mh = macd(c)
    macd_val   = round(float(ml.iloc[-1]),4)
    macd_sig   = round(float(ms.iloc[-1]),4)
    macd_hist  = round(float(mh.iloc[-1]),4)
    macd_cross = "BULL" if macd_val>macd_sig and float(mh.iloc[-1])>float(mh.iloc[-2]) else                  ("BEAR" if macd_val<macd_sig and float(mh.iloc[-1])<float(mh.iloc[-2]) else "NEUTRE")

    # ATR
    atr_val = round(float(atr(h,l,c,14).iloc[-1]),3)
    atr_pct  = round(atr_val/cur*100,2)

    # Bollinger
    bb_up, bb_lo, bb_mid = bollinger(c)
    bb_top = round(float(bb_up.iloc[-1]),3)
    bb_bot = round(float(bb_lo.iloc[-1]),3)
    bb_pct = round((cur-float(bb_lo.iloc[-1]))/(float(bb_up.iloc[-1])-float(bb_lo.iloc[-1]))*100,1)              if (float(bb_up.iloc[-1])-float(bb_lo.iloc[-1]))>0 else 50
    # Squeeze = bandes très serrées
    bb_width = (float(bb_up.iloc[-1])-float(bb_lo.iloc[-1]))/float(bb_mid.iloc[-1])
    bb_squeeze = bb_width < float((bb_up-bb_lo).rolling(20).mean().iloc[-1]/float(bb_mid.iloc[-1])*0.7)                  if len(c)>=20 else False

    # ROC
    roc20 = round(float(roc(c,20).iloc[-1]),2) if len(c)>=21 else 0
    roc60 = round(float(roc(c,60).iloc[-1]),2) if len(c)>=61 else 0

    # Swing highs/lows
    h_idx, l_idx = swing_highs_lows(h, l, lookback_swing)
    struct = trend_structure(h_idx, l_idx, h, l)

    # Niveaux swing récents
    swing_h = sorted(set(round(float(h.iloc[i]),3) for i in h_idx[-5:]), reverse=True)
    swing_l = sorted(set(round(float(l.iloc[i]),3) for i in l_idx[-5:]))

    # Range 52 semaines (sur daily) ou adapté
    high52 = round(float(h.tail(252).max()),3) if len(h)>=252 else round(float(h.max()),3)
    low52  = round(float(l.tail(252).min()),3) if len(l)>=252 else round(float(l.min()),3)
    pct52  = round((cur-low52)/(high52-low52)*100,1) if (high52-low52)>0 else 50

    return {
        "tf":tf_name, "cur":round(cur,3),
        "e20":round(e20,3),"e50":round(e50,3),"e200":round(e200,3),
        "ema_trend":ema_trend,
        "rsi":rsi_val,"rsi_div":rsi_div,
        "macd_val":macd_val,"macd_sig":macd_sig,"macd_hist":macd_hist,"macd_cross":macd_cross,
        "atr":atr_val,"atr_pct":atr_pct,
        "bb_top":bb_top,"bb_bot":bb_bot,"bb_pct":bb_pct,"bb_squeeze":bb_squeeze,
        "roc20":roc20,"roc60":roc60,
        "structure":struct,
        "swing_h":swing_h[:3],"swing_l":swing_l[:3],
        "high52":high52,"low52":low52,"pct52":pct52,
    }

print("\n⚙️  Calcul des indicateurs...")
tf_d = analyse_tf(D, "Daily",   lookback_swing=3)
tf_w = analyse_tf(W, "Weekly",  lookback_swing=2)
tf_m = analyse_tf(M, "Monthly", lookback_swing=2)

# Supply/Demand zones
sd_d = detect_supply_demand(D.tail(120), lookback=3, impulse_pct=0.003)
sd_w = detect_supply_demand(W.tail(80),  lookback=2, impulse_pct=0.005)
sd_m = detect_supply_demand(M.tail(36),  lookback=2, impulse_pct=0.008)

# Confluence
all_res_d = tf_d["swing_h"]; all_sup_d = tf_d["swing_l"]
all_res_w = tf_w["swing_h"]; all_sup_w = tf_w["swing_l"]
all_res_m = tf_m["swing_h"]; all_sup_m = tf_m["swing_l"]
conf_res = confluence_levels(all_res_d, all_res_w, all_res_m)
conf_sup = confluence_levels(all_sup_d, all_sup_w, all_sup_m)
cur_price = tf_d["cur"]
conf_res_above = [c for c in conf_res if c["level"] > cur_price]
conf_sup_below = [c for c in conf_sup if c["level"] < cur_price]

# ── SCORE DXY GLOBAL ─────────────────────────────────────────
def compute_dxy_score(tf_d, tf_w, tf_m):
    score = 50.0
    # EMA alignment (poids fort)
    for tf, w in [(tf_d,0.40),(tf_w,0.35),(tf_m,0.25)]:
        if "BULL FORT" in tf["ema_trend"]: score += 15*w
        elif "BULL"    in tf["ema_trend"]: score += 8*w
        elif "BEAR FORT" in tf["ema_trend"]: score -= 15*w
        elif "BEAR"    in tf["ema_trend"]: score -= 8*w
    # RSI
    for tf, w in [(tf_d,0.40),(tf_w,0.35),(tf_m,0.25)]:
        r = tf["rsi"]
        if 50<r<70:  score += 5*w
        elif r>=70:  score += 2*w   # surachat = ralentissement
        elif 30<r<50: score -= 5*w
        elif r<=30:  score -= 2*w
    # MACD
    for tf, w in [(tf_d,0.40),(tf_w,0.35),(tf_m,0.25)]:
        if tf["macd_cross"]=="BULL":   score += 5*w
        elif tf["macd_cross"]=="BEAR": score -= 5*w
    # ROC
    if tf_d["roc20"]>0: score += 5
    if tf_d["roc60"]>0: score += 5
    if tf_w["roc20"]>0: score += 3
    # Structure
    for tf, w in [(tf_d,0.40),(tf_w,0.35),(tf_m,0.25)]:
        if tf["structure"]=="UPTREND":    score += 8*w
        elif tf["structure"]=="DOWNTREND": score -= 8*w
    return round(np.clip(score,0,100),1)

dxy_score = compute_dxy_score(tf_d, tf_w, tf_m)

# Verdict
if dxy_score >= 65:
    verdict = "USD BULL"
    verdict_col = "#22c55e"
    verdict_icon = "📈"
    implication = "USD fort sur tous les timeframes. Favoriser les SHORT sur XX/USD (EUR/USD, GBP/USD, AUD/USD) et les LONG sur USD/XX (USD/JPY, USD/CAD, USD/CHF). Carry USD dominant."
elif dxy_score <= 35:
    verdict = "USD BEAR"
    verdict_col = "#ef4444"
    verdict_icon = "📉"
    implication = "USD faible sur tous les timeframes. Favoriser les LONG sur XX/USD et les SHORT sur USD/XX. Attention aux paires EM — carry favorable mais risque de reversal USD."
else:
    verdict = "USD TRANSITION"
    verdict_col = "#f59e0b"
    verdict_icon = "⚠️"
    implication = "DXY en zone de transition — pas de conviction directionnelle claire. Réduire la taille des positions USD, privilégier les crosses sans USD (EUR/GBP, AUD/JPY, EUR/JPY) ou attendre un signal plus clair."

# Niveau clé le plus proche
nearest_res = min(conf_res_above, key=lambda x:x["level"]-cur_price)["level"] if conf_res_above else tf_d["swing_h"][0] if tf_d["swing_h"] else round(cur_price*1.01,3)
nearest_sup = max(conf_sup_below, key=lambda x:x["level"])["level"] if conf_sup_below else tf_d["swing_l"][0] if tf_d["swing_l"] else round(cur_price*0.99,3)

dist_res = round((nearest_res-cur_price)/cur_price*100,2)
dist_sup = round((cur_price-nearest_sup)/cur_price*100,2)

print(f"\n{'='*50}")
print(f"  DXY Score : {dxy_score}/100 → {verdict}")
print(f"  Prix      : {cur_price}")
print(f"  Résistance la plus proche : {nearest_res} (+{dist_res}%)")
print(f"  Support le plus proche    : {nearest_sup} (−{dist_sup}%)")
print(f"{'='*50}")

# ── HTML DASHBOARD DXY ───────────────────────────────────────

def tf_card(tf, sd_zones):
    c = tf["cur"]
    trend_c = ("#22c55e" if "BULL" in tf["ema_trend"]
               else ("#ef4444" if "BEAR" in tf["ema_trend"] else "#f59e0b"))
    struct_c = ("#22c55e" if tf["structure"]=="UPTREND"
                else ("#ef4444" if tf["structure"]=="DOWNTREND" else "#f59e0b"))
    rsi_c = ("#fca5a5" if tf["rsi"]>70 else ("#86efac" if tf["rsi"]<30 else "#94a3b8"))
    macd_c = ("#22c55e" if tf["macd_cross"]=="BULL"
              else ("#ef4444" if tf["macd_cross"]=="BEAR" else "#94a3b8"))
    roc_c  = "#22c55e" if tf["roc20"]>0 else "#ef4444"
    div_badge = ""
    if tf["rsi_div"]=="BULL_DIV":
        div_badge = '<span style="font-size:9px;background:rgba(34,197,94,.2);color:#86efac;padding:1px 5px;border-radius:3px;margin-left:4px">DIV BULL</span>'
    elif tf["rsi_div"]=="BEAR_DIV":
        div_badge = '<span style="font-size:9px;background:rgba(239,68,68,.2);color:#fca5a5;padding:1px 5px;border-radius:3px;margin-left:4px">DIV BEAR</span>'
    squeeze_badge = '<span style="font-size:9px;background:rgba(245,158,11,.2);color:#fcd34d;padding:1px 5px;border-radius:3px;margin-left:4px">SQUEEZE</span>' if tf["bb_squeeze"] else ""

    # S/D zones pour ce tf
    supply_z = [z for z in sd_zones if z["type"]=="supply"][:2]
    demand_z = [z for z in sd_zones if z["type"]=="demand"][:2]
    sd_html = ""
    for z in supply_z:
        sd_html += f'<div style="display:flex;justify-content:space-between;padding:4px 8px;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.25);border-radius:5px;margin-bottom:4px;font-size:11px"><span style="color:#fca5a5">🔴 SUPPLY</span><span style="font-family:monospace">{z["bot"]:.3f} – {z["top"]:.3f}</span><span style="color:#64748b">{z["strength"]:.2f}%</span></div>'
    for z in demand_z:
        sd_html += f'<div style="display:flex;justify-content:space-between;padding:4px 8px;background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.25);border-radius:5px;margin-bottom:4px;font-size:11px"><span style="color:#86efac">🟢 DEMAND</span><span style="font-family:monospace">{z["bot"]:.3f} – {z["top"]:.3f}</span><span style="color:#64748b">{z["strength"]:.2f}%</span></div>'

    # Range 52W bar
    pct52_w = tf["pct52"]

    return f"""
    <div style="background:#111827;border:1px solid #1e293b;border-radius:12px;padding:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <div>
          <span style="font-size:12px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.1em">{tf["tf"]}</span>
          <span style="font-family:monospace;font-size:18px;font-weight:700;color:#e2e8f0;margin-left:10px">{c:.3f}</span>
        </div>
        <div style="text-align:right">
          <div style="font-size:12px;font-weight:600;color:{trend_c}">{tf["ema_trend"]}</div>
          <div style="font-size:11px;color:{struct_c}">{tf["structure"]}</div>
        </div>
      </div>

      <!-- EMAs -->
      <div style="margin-bottom:10px">
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px">Moyennes Mobiles (EMA)</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          {"".join(f'<span style="font-size:11px;padding:2px 8px;background:#1f2937;border:1px solid {("#22c55e" if c>v else "#ef4444")};border-radius:4px;font-family:monospace">EMA{p} {v:.3f}</span>'
            for p,v in [(20,tf["e20"]),(50,tf["e50"]),(200,tf["e200"])])}
        </div>
      </div>

      <!-- RSI + MACD + ATR -->
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:10px">
        <div style="background:#1f2937;border-radius:8px;padding:8px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase;margin-bottom:3px">RSI 14 {div_badge}</div>
          <div style="font-size:18px;font-weight:700;font-family:monospace;color:{rsi_c}">{tf["rsi"]}</div>
          <div style="font-size:9px;color:#64748b">{"Surachat" if tf["rsi"]>70 else ("Survente" if tf["rsi"]<30 else "Zone saine")}</div>
        </div>
        <div style="background:#1f2937;border-radius:8px;padding:8px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase;margin-bottom:3px">MACD</div>
          <div style="font-size:14px;font-weight:700;font-family:monospace;color:{macd_c}">{tf["macd_cross"]}</div>
          <div style="font-size:9px;color:#64748b">hist {tf["macd_hist"]:+.4f}</div>
        </div>
        <div style="background:#1f2937;border-radius:8px;padding:8px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase;margin-bottom:3px">ATR 14</div>
          <div style="font-size:14px;font-weight:700;font-family:monospace;color:#e2e8f0">{tf["atr"]}</div>
          <div style="font-size:9px;color:#64748b">{tf["atr_pct"]:.2f}%</div>
        </div>
      </div>

      <!-- Bollinger + ROC -->
      <div style="margin-bottom:10px">
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px">Bollinger Bands {squeeze_badge}</div>
        <div style="background:#1f2937;border-radius:6px;padding:6px 10px">
          <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:5px">
            <span style="color:#fca5a5">Low {tf["bb_bot"]:.3f}</span>
            <span style="color:#94a3b8">Position {tf["bb_pct"]:.0f}%</span>
            <span style="color:#86efac">High {tf["bb_top"]:.3f}</span>
          </div>
          <div style="height:5px;background:#374151;border-radius:3px;position:relative">
            <div style="position:absolute;left:{tf["bb_pct"]}%;top:-2px;width:9px;height:9px;background:#3b82f6;border-radius:50%;transform:translateX(-50%)"></div>
          </div>
        </div>
      </div>

      <!-- ROC -->
      <div style="display:flex;gap:8px;margin-bottom:10px">
        <div style="flex:1;background:#1f2937;border-radius:6px;padding:6px 10px;text-align:center">
          <div style="font-size:9px;color:#64748b;margin-bottom:2px">ROC 20</div>
          <div style="font-size:13px;font-weight:600;font-family:monospace;color:{roc_c}">{tf["roc20"]:+.2f}%</div>
        </div>
        <div style="flex:1;background:#1f2937;border-radius:6px;padding:6px 10px;text-align:center">
          <div style="font-size:9px;color:#64748b;margin-bottom:2px">ROC 60</div>
          <div style="font-size:13px;font-weight:600;font-family:monospace;color:{"#22c55e" if tf["roc60"]>0 else "#ef4444"}">{tf["roc60"]:+.2f}%</div>
        </div>
        <div style="flex:1;background:#1f2937;border-radius:6px;padding:6px 10px;text-align:center">
          <div style="font-size:9px;color:#64748b;margin-bottom:2px">Range 52W</div>
          <div style="font-size:13px;font-weight:600;font-family:monospace;color:#94a3b8">{pct52_w:.0f}%</div>
        </div>
      </div>

      <!-- Swing levels -->
      <div style="margin-bottom:10px">
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px">Swing Highs / Lows</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          {"".join(f'<span style="font-size:10px;padding:2px 7px;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.3);border-radius:4px;font-family:monospace;color:#fca5a5">R {v}</span>' for v in tf["swing_h"])}
          {"".join(f'<span style="font-size:10px;padding:2px 7px;background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.3);border-radius:4px;font-family:monospace;color:#86efac">S {v}</span>' for v in tf["swing_l"])}
        </div>
      </div>

      <!-- Supply/Demand -->
      {f'<div><div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px">Zones Supply / Demand</div>'+sd_html+'</div>' if sd_html else ""}
    </div>"""

# Confluence cards
def confluence_card(zones, cur_price, zone_type):
    if not zones: return f'<div style="color:#64748b;font-size:12px;padding:8px">Aucune confluence {zone_type} détectée</div>'
    html = ""
    for z in zones[:4]:
        dist = abs(z["level"]-cur_price)/cur_price*100
        strength_label = "🔥 TRÈS FORT" if z["strength"]==3 else "💪 FORT"
        strength_c = "#ef4444" if z["strength"]==3 else "#f59e0b"
        tfs = " + ".join(z["timeframes"])
        is_supply = z["level"] > cur_price
        col = "#fca5a5" if is_supply else "#86efac"
        html += f'<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 10px;background:#1f2937;border:1px solid {"rgba(239,68,68,.3)" if is_supply else "rgba(34,197,94,.3)"};border-radius:7px;margin-bottom:5px"><div><span style="font-family:monospace;font-size:14px;font-weight:600;color:{col}">{z["level"]:.3f}</span><span style="font-size:10px;color:#64748b;margin-left:8px">{tfs}</span></div><div style="text-align:right"><span style="font-size:10px;color:{strength_c}">{strength_label}</span><div style="font-size:10px;color:#64748b">{dist:.2f}% du prix</div></div></div>'
    return html

# Implication par paire
pair_implications = []
USD_QUOTE_PAIRS = ["EUR/USD","GBP/USD","AUD/USD","NZD/USD"]
USD_BASE_PAIRS  = ["USD/JPY","USD/CAD","USD/CHF","USD/NOK"]
if dxy_score >= 65:
    for p in USD_QUOTE_PAIRS: pair_implications.append((p,"SELL","Fort signal SELL — USD bull","#ef4444"))
    for p in USD_BASE_PAIRS:  pair_implications.append((p,"BUY", "Fort signal BUY — USD bull","#22c55e"))
elif dxy_score <= 35:
    for p in USD_QUOTE_PAIRS: pair_implications.append((p,"BUY", "Fort signal BUY — USD bear","#22c55e"))
    for p in USD_BASE_PAIRS:  pair_implications.append((p,"SELL","Fort signal SELL — USD bear","#ef4444"))
else:
    for p in USD_QUOTE_PAIRS+USD_BASE_PAIRS:
        pair_implications.append((p,"NEUTRE","DXY en transition — attendre","#f59e0b"))

impl_html = "".join(
    f'<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:#1f2937;border-radius:6px;margin-bottom:4px"><span style="font-family:monospace;font-size:12px;color:#e2e8f0">{p}</span><span style="font-size:11px;font-weight:600;color:{c}">{d}</span><span style="font-size:10px;color:#64748b;max-width:180px;text-align:right">{note}</span></div>'
    for p,d,note,c in pair_implications
)

now = datetime.now().strftime("%d/%m/%Y %H:%M")

html_dxy = f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
  .dxy-wrap {{ font-family:'Space Grotesk',sans-serif; background:#0a0e1a; color:#e2e8f0; border-radius:14px; overflow:hidden; }}
  .dxy-tab {{ padding:9px 16px; font-size:13px; font-weight:500; cursor:pointer;
              border-bottom:2px solid transparent; color:#64748b; display:inline-block; }}
  .dxy-tab.act {{ color:#e2e8f0; border-bottom-color:#f59e0b; }}
  .dxy-tc {{ display:none; padding:16px; }}
  .dxy-tc.act {{ display:block; }}
</style>

<div class="dxy-wrap">
  <!-- Header -->
  <div style="background:#111827;border-bottom:1px solid #1e293b;padding:14px 18px;display:flex;justify-content:space-between;align-items:center">
    <div>
      <span style="font-size:17px;font-weight:700">DXY <span style="color:#f59e0b">Analysis</span></span>
      <span style="font-size:12px;color:#64748b;margin-left:10px">Daily · Weekly · Monthly</span>
    </div>
    <div style="font-size:11px;color:#64748b;font-family:monospace">{now}</div>
  </div>

  <!-- Score verdict -->
  <div style="background:linear-gradient(135deg,#111827,#1f2937);padding:20px 18px;border-bottom:1px solid #1e293b">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
      <div>
        <div style="font-size:28px;font-weight:700;color:{verdict_col}">{verdict_icon} {verdict}</div>
        <div style="font-size:13px;color:#94a3b8;margin-top:4px;max-width:460px;line-height:1.6">{implication}</div>
      </div>
      <div style="text-align:center;background:#0a0e1a;border:2px solid {verdict_col};border-radius:50%;width:80px;height:80px;display:flex;flex-direction:column;align-items:center;justify-content:center">
        <div style="font-size:26px;font-weight:700;font-family:monospace;color:{verdict_col}">{dxy_score:.0f}</div>
        <div style="font-size:9px;color:#64748b">/ 100</div>
      </div>
    </div>
    <!-- Score bar -->
    <div style="height:6px;background:#1e293b;border-radius:3px;margin-bottom:10px">
      <div style="width:{dxy_score}%;height:100%;background:linear-gradient(90deg,#ef4444,#f59e0b,#22c55e);border-radius:3px"></div>
    </div>
    <!-- Niveaux clés -->
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px">
      <div style="background:#0a0e1a;border:1px solid rgba(239,68,68,.3);border-radius:8px;padding:10px;text-align:center">
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;margin-bottom:3px">Résistance clé</div>
        <div style="font-family:monospace;font-size:16px;font-weight:600;color:#fca5a5">{nearest_res}</div>
        <div style="font-size:10px;color:#64748b">+{dist_res}% du prix</div>
      </div>
      <div style="background:#0a0e1a;border:1px solid #1e293b;border-radius:8px;padding:10px;text-align:center">
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;margin-bottom:3px">DXY Actuel</div>
        <div style="font-family:monospace;font-size:20px;font-weight:700;color:#e2e8f0">{cur_price:.3f}</div>
        <div style="font-size:10px;color:#64748b">52W : {tf_d["pct52"]:.0f}%ile</div>
      </div>
      <div style="background:#0a0e1a;border:1px solid rgba(34,197,94,.3);border-radius:8px;padding:10px;text-align:center">
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;margin-bottom:3px">Support clé</div>
        <div style="font-family:monospace;font-size:16px;font-weight:600;color:#86efac">{nearest_sup}</div>
        <div style="font-size:10px;color:#64748b">−{dist_sup}% du prix</div>
      </div>
    </div>
  </div>

  <!-- Tabs -->
  <div style="background:#111827;border-bottom:1px solid #1e293b;padding:0 18px">
    <span class="dxy-tab act" onclick="dxyTab('daily',this)">📅 Daily</span>
    <span class="dxy-tab" onclick="dxyTab('weekly',this)">📆 Weekly</span>
    <span class="dxy-tab" onclick="dxyTab('monthly',this)">🗓️ Monthly</span>
    <span class="dxy-tab" onclick="dxyTab('confluence',this)">🎯 Confluence</span>
    <span class="dxy-tab" onclick="dxyTab('implications',this)">💱 Paires</span>
  </div>

  <div id="dxy-daily"       class="dxy-tc act">{tf_card(tf_d, sd_d)}</div>
  <div id="dxy-weekly"      class="dxy-tc">{tf_card(tf_w, sd_w)}</div>
  <div id="dxy-monthly"     class="dxy-tc">{tf_card(tf_m, sd_m)}</div>
  <div id="dxy-confluence"  class="dxy-tc">
    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;margin-bottom:8px;color:#fca5a5">🔴 Zones de résistance en confluence</div>
      {confluence_card(conf_res_above, cur_price, "résistance")}
    </div>
    <div>
      <div style="font-size:13px;font-weight:600;margin-bottom:8px;color:#86efac">🟢 Zones de support en confluence</div>
      {confluence_card(conf_sup_below, cur_price, "support")}
    </div>
  </div>
  <div id="dxy-implications" class="dxy-tc">
    <div style="font-size:13px;color:#94a3b8;margin-bottom:14px;line-height:1.6">
      Implications directes sur les paires USD en fonction du verdict <strong style="color:{verdict_col}">{verdict}</strong> (score {dxy_score:.0f}/100).
    </div>
    {impl_html}
  </div>
</div>

<script>
function dxyTab(name, el) {{
  document.querySelectorAll(".dxy-tc").forEach(t=>t.classList.remove("act"));
  document.querySelectorAll(".dxy-tab").forEach(t=>t.classList.remove("act"));
  document.getElementById("dxy-"+name).classList.add("act");
  el.classList.add("act");
}}
</script>
"""

FRAGMENTS["dxy"] = html_dxy  # stocké pour la page unique
print(f"\n✅ Analyse DXY générée — Score : {dxy_score}/100 → {verdict}")

# ═══════════════ SECTION INDICES (logique C14 + harmonisation v4) ═══════════════
print("📥 [4/6] Indices...")
# Forex (cellules 1-13) inchangé. Cette cellule est autonome.

import requests, numpy as np, pandas as pd
from datetime import datetime
import warnings; warnings.filterwarnings("ignore")

# (clés déjà chargées plus haut dans TWELVE_KEY / FRED_KEY)

# ── Univers INDICES ───────────────────────────────────────────
# symbol Twelve Data + ticker yfinance de secours
INDICES = {
    "SPX":    {"td":"SPX",      "yf":"^GSPC",  "label":"S&P 500",    "region":"US",   "ccy_link":None},
    "NDX":    {"td":"NDX",      "yf":"^NDX",   "label":"Nasdaq 100", "region":"US",   "ccy_link":None},
    "DJI":    {"td":"DJI",      "yf":"^DJI",   "label":"Dow Jones",  "region":"US",   "ccy_link":None},
    "DAX":    {"td":"DAX",      "yf":"^GDAXI", "label":"DAX 40",     "region":"EU",   "ccy_link":"EUR"},
    "FTSE":   {"td":"FTSE",     "yf":"^FTSE",  "label":"FTSE 100",   "region":"UK",   "ccy_link":"GBP"},
    "NIKKEI": {"td":"NKY",      "yf":"^N225",  "label":"Nikkei 225", "region":"ASIA", "ccy_link":"JPY"},
}

# ── Récupération données : Twelve Data prioritaire ────────────
def fetch_twelve(symbol, interval="1day", outputsize=260):
    global TD_FAILS, TD_OK
    try: TD_FAILS
    except NameError: TD_FAILS = 0; TD_OK = 0
    if not TWELVE_KEY or not USE_TWELVE_DATA or TD_FAILS >= 3:
        return None
    global _TD_LAST
    try: _TD_LAST
    except NameError: _TD_LAST = 0
    _w = TD_PAUSE_SEC - (time.time() - _TD_LAST)
    if _w > 0: time.sleep(_w)
    _TD_LAST = time.time()
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol":symbol,"interval":interval,"outputsize":outputsize,
              "apikey":TWELVE_KEY,"format":"JSON"}
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if "values" not in data:
            TD_FAILS += 1
            return None
        TD_FAILS = 0; TD_OK += 1
        df = pd.DataFrame(data["values"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime").sort_index()
        for c in ["open","high","low","close"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df[["open","high","low","close"]].dropna()
    except Exception as e:
        return None

def fetch_yf_fallback(ticker, period="1y"):
    try:
        import yfinance as yf
        df = yf.download(ticker, period=period, interval="1d",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close"})
        return df[["open","high","low","close"]].dropna()
    except Exception:
        return None

def get_data(asset_meta):
    df = fetch_twelve(asset_meta["td"], "1day", 260)
    src = "TwelveData"
    if df is None or len(df) < 50:
        df = fetch_yf_fallback(asset_meta["yf"])
        src = "yfinance"
    return df, src

print("📥 Chargement INDICES...")
indices_data = {}
for key, meta in INDICES.items():
    df, src = get_data(meta)
    if df is not None and len(df) >= 50:
        indices_data[key] = {"df":df, "src":src, "meta":meta}
        print(f"  ✅ {meta['label']:<14} {len(df)} barres ({src})")
    else:
        print(f"  ❌ {meta['label']:<14} indisponible")

# ── H4 indices (yfinance, batch unique — pour confirmation timing) ──
h4_idx = {}
try:
    import yfinance as _yf
    _h4raw = _yf.download([m["yf"] for m in INDICES.values()], period="60d",
                          interval="4h", auto_adjust=True, progress=False, group_by="ticker")
    for _k, _m in INDICES.items():
        try:
            if _m["yf"] in _h4raw.columns.get_level_values(0):
                h4_idx[_k] = _h4raw[_m["yf"]]["Close"].dropna()
        except Exception: pass
    print(f"   ✅ H4 chargé pour {len(h4_idx)} indices")
except Exception: pass

# ── VIX (risk-on/off) ─────────────────────────────────────────
vix_df, _ = get_data({"td":"VIX","yf":"^VIX"})
vix_now = float(vix_df["close"].iloc[-1]) if vix_df is not None and len(vix_df)>0 else 18.0
vix_ma20 = float(vix_df["close"].rolling(20).mean().iloc[-1]) if vix_df is not None and len(vix_df)>20 else vix_now
vix_rising = vix_now > vix_ma20 * 1.05   # VIX en expansion = risk-off
vix_regime = ("RISK-OFF" if vix_now > 25 or vix_rising else
              "RISK-ON" if vix_now < 16 else "NEUTRE")
print(f"\n  VIX : {vix_now:.1f} | régime : {vix_regime}")

# ── Indicateurs ───────────────────────────────────────────────
def ema(s,p): return s.ewm(span=p,adjust=False).mean()
def rsi(s,p=14):
    d=s.diff(); g=d.clip(lower=0).rolling(p).mean(); l=(-d.clip(upper=0)).rolling(p).mean()
    return 100-100/(1+g/l.replace(0,np.nan))
def atr(h,l,c,p=14):
    pc=c.shift(1); tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return tr.rolling(p).mean()

def sup_res_levels(c, h, l, n_levels=2):
    """Swing highs/lows significatifs sur 60 barres — comme le forex"""
    if len(c) < 20: return [], []
    hh = h.iloc[-60:].values if len(h)>=60 else h.values
    ll = l.iloc[-60:].values if len(l)>=60 else l.values
    cur = float(c.iloc[-1])
    res = sorted({round(float(hh[i]),2) for i in range(2,len(hh)-2)
                  if hh[i]>hh[i-1] and hh[i]>hh[i+1] and hh[i]>hh[i-2] and hh[i]>hh[i+2]
                  and hh[i]>cur})[:n_levels]
    sup = sorted({round(float(ll[i]),2) for i in range(2,len(ll)-2)
                  if ll[i]<ll[i-1] and ll[i]<ll[i+1] and ll[i]<ll[i-2] and ll[i]<ll[i+2]
                  and ll[i]<cur}, reverse=True)[:n_levels]
    return sup, res

MONTH_NAMES={1:"Janvier",2:"Février",3:"Mars",4:"Avril",5:"Mai",6:"Juin",
             7:"Juillet",8:"Août",9:"Septembre",10:"Octobre",11:"Novembre",12:"Décembre"}
cur_month = datetime.now().month

def index_seasonality(month):
    """Saisonnalité indices US prouvée : Nov-Avr fort, Mai-Oct faible"""
    strong = month in [11,12,1,2,3,4]   # 'Sell in May' inversé
    if month in [9]:  return -1, "Septembre historiquement faible"
    if month in [5,6,7,8,10]: return 0, "Période estivale — rendements plus faibles"
    if strong: return +1, "Saison favorable (Nov-Avr)"
    return 0, "Neutre"

# ── SCORE INDICES : trend 35 + momentum 35 + risk 20 + saison 10 ─
def score_index(key, data):
    df = data["df"]; meta = data["meta"]
    c=df["close"]; h=df["high"]; l=df["low"]
    cur=float(c.iloc[-1])
    e20=float(ema(c,20).iloc[-1]); e50=float(ema(c,50).iloc[-1])
    e200=float(ema(c,200).iloc[-1]) if len(c)>=200 else float(ema(c,min(len(c)-1,100)).iloc[-1])
    r=float(rsi(c).iloc[-1])
    a=float(atr(h,l,c).iloc[-1]); atr_pct=a/cur*100
    sup, res = sup_res_levels(c, h, l)
    # Harmonisation v4 : mêmes mesures de timing que le forex
    dist_ema20_atr = (cur - e20) / a if a > 0 else 0
    entry_label = ("Extension" if abs(dist_ema20_atr) > 1.5
                   else ("Pullback" if abs(dist_ema20_atr) < 0.5 else "Neutre"))
    h4_dir, _h4s = h4_trend(h4_idx.get(key))

    # 1. TENDANCE (35%) — règle MM200 de Meb Faber + alignement EMA
    trend=50.0
    if cur>e200: trend+=20
    else: trend-=20
    if e20>e50: trend+=15
    else: trend-=15
    trend=np.clip(trend,0,100)

    # 2. MOMENTUM (35%) — ROC 60j + ROC 120j
    roc60=float(c.iloc[-1]/c.iloc[-60]-1)*100 if len(c)>=60 else 0
    roc120=float(c.iloc[-1]/c.iloc[-120]-1)*100 if len(c)>=120 else roc60
    mom=50.0+np.clip(roc60/10,-1,1)*30+np.clip(roc120/15,-1,1)*20
    mom=np.clip(mom,0,100)

    # 3. RISK-ON/OFF (20%) — VIX
    if vix_regime=="RISK-ON": risk=70
    elif vix_regime=="RISK-OFF": risk=25
    else: risk=50

    # 4. SAISONNALITÉ (10%)
    seas_bias, seas_note = index_seasonality(cur_month)
    seas=50+seas_bias*25

    score=round(trend*0.35+mom*0.35+risk*0.20+seas*0.10,1)

    # Direction — SELL exige plus de preuves sur indices (anti biais long)
    ema_trend=("BULLISH" if cur>e20>e50 else "BEARISH" if cur<e20<e50 else "MIXED")
    structure_bear = cur<e200 and ema_trend=="BEARISH"
    if score>=65:
        direction="BUY"; conv=score
    elif score<=35 and structure_bear and vix_regime=="RISK-OFF":
        # SELL seulement si structure baissière confirmée ET risk-off
        direction="SELL"; conv=100-score
    elif score<=30 and structure_bear:
        direction="SELL"; conv=100-score
    else:
        direction="NEUTRAL"; conv=abs(score-50)*2
    conv=round(min(conv,100),1)

    # SL/TP basés ATR
    if direction=="BUY":
        sl=round(cur-1.5*a,2); tp1=round(cur+2*a,2); tp2=round(cur+3.5*a,2)
    elif direction=="SELL":
        sl=round(cur+1.5*a,2); tp1=round(cur-2*a,2); tp2=round(cur-3.5*a,2)
    else:
        sl=round(cur-1.5*a,2); tp1=round(cur+2*a,2); tp2=round(cur+3.5*a,2)

    # Explication
    if direction=="BUY":
        resume=f"📈 Signal ACHAT sur {meta['label']}. "
        rs=[]
        if cur>e200: rs.append("au-dessus de la MM200 (tendance long terme haussière, règle clé sur indices)")
        if roc60>0: rs.append(f"momentum positif (+{roc60:.1f}% sur 60j)")
        if vix_regime=="RISK-ON": rs.append("marché en mode risk-on (VIX bas)")
        if rs: resume+="Pourquoi : "+", ".join(rs)+". "
    elif direction=="SELL":
        resume=f"📉 Signal VENTE sur {meta['label']} — signal fort requis car les indices montent structurellement. "
        rs=[]
        if cur<e200: rs.append("sous la MM200 (tendance cassée)")
        if vix_regime=="RISK-OFF": rs.append("marché en risk-off (VIX élevé/montant)")
        if roc60<0: rs.append(f"momentum négatif ({roc60:.1f}% sur 60j)")
        if rs: resume+="Pourquoi : "+", ".join(rs)+". "
    else:
        resume=f"⏸ Pas de signal clair sur {meta['label']}. "
        if 35<score<65: resume+="Tendance pas assez nette pour engager. "

    if r>70: resume+=f"⚠️ RSI {r:.0f} élevé — le prix a beaucoup monté, risque de pause. "
    elif r<30: resume+=f"⚠️ RSI {r:.0f} bas — survente, risque de rebond. "

    detail=(f"{'📈 BUY' if direction=='BUY' else '📉 SELL' if direction=='SELL' else '⏸ NO TRADE'} — "
            f"Score {score}/100, conviction {conv:.0f}%. "
            f"{'✅' if cur>e200 else '❌'} MM200 : prix {'au-dessus' if cur>e200 else 'en-dessous'}. "
            f"Tendance {ema_trend}. Momentum 60j {roc60:+.1f}%. "
            f"RSI {r:.0f}. VIX {vix_now:.0f} ({vix_regime}). "
            f"Saison : {seas_note}. ATR {atr_pct:.2f}%.")

    return {
        "key":key,"label":meta["label"],"region":meta["region"],
        "direction":direction,"conviction":conv,"score":score,"price":round(cur,2),
        "sl":sl,"tp1":tp1,"tp2":tp2,
        "ema_trend":ema_trend,"rsi":round(r,1),"roc60":round(roc60,1),
        "above_ma200":cur>e200,"atr_pct":round(atr_pct,2),
        "trend_sc":round(trend,0),"mom_sc":round(mom,0),"risk_sc":risk,"seas_sc":seas,
        "sup":sup,"res":res,
        "dist_ema20_atr":round(dist_ema20_atr,2),"entry_label":entry_label,"h4_dir":h4_dir,
        "atr":round(a,4),"ema20":round(e20,2),"asset_class":"Indices","pair":key,
        "resume":resume,"detail":detail,"src":data["src"],
    }

print("\n📊 Calcul des signaux indices...")
indices_signals=[]
for key,data in indices_data.items():
    try:
        sig=score_index(key,data)
        # Harmonisation v4 : maturité + plan risque
        _c = data["df"]["close"]; _h = data["df"]["high"]; _l = data["df"]["low"]
        ml, mc, mn = compute_maturity(sig, _c, _h, _l)
        sig["maturity"]=ml; sig["maturity_color"]=mc; sig["maturity_note"]=mn
        sig["plan_generic"] = generic_plan(sig)
        _av = sig.get("atr", 0)
        sig["fresh_flag"], sig["fresh_data"] = fresh_momentum(_c, _av)
        sig["sd_demand"], sig["sd_supply"] = detect_sd_zones(_c, _h, _l, _av)
        sig["exit_plan"] = exit_plan_2steps(sig, nd=2)
        sig["timing"] = unified_timing(sig)
        sig["mom_h"] = mom_agreement(_c)
        sig["shock"] = shock_memory(_c, _av)
        sig["zone_ctx"] = zone_context(sig)
        indices_signals.append(sig)
        ic="↑" if sig["direction"]=="BUY" else ("↓" if sig["direction"]=="SELL" else "→")
        print(f"  {ic} {sig['label']:<14} {sig['direction']:<8} score:{sig['score']:.0f} conv:{sig['conviction']:.0f}%")
    except Exception as e:
        print(f"  ⚠️ {key} : {e}")

# ── DASHBOARD HTML ────────────────────────────────────────────
def card_index(s):
    col="#22c55e" if s["direction"]=="BUY" else ("#ef4444" if s["direction"]=="SELL" else "#94a3b8")
    icon="↑" if s["direction"]=="BUY" else ("↓" if s["direction"]=="SELL" else "→")
    ma200_badge=(f'<span style="font-size:10px;padding:2px 8px;border-radius:20px;background:#1f2937;'
                 f'border:1px solid {"#22c55e" if s["above_ma200"] else "#ef4444"};'
                 f'color:{"#86efac" if s["above_ma200"] else "#fca5a5"}">'
                 f'{"✅ &gt; MM200" if s["above_ma200"] else "❌ &lt; MM200"}</span>')
    return f"""
    <div style="background:#111827;border:1px solid #1e293b;border-radius:12px;padding:16px;margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="background:{col};color:#fff;font-size:12px;font-weight:700;padding:3px 10px;border-radius:6px">{icon} {s['direction']}</span>
          <span style="font-size:17px;font-weight:600;color:#e2e8f0">{s['label']}</span>
          <span style="font-size:10px;color:#64748b;background:#1f2937;padding:1px 7px;border-radius:4px">{s['region']}</span>
          <span style="font-size:9px;color:#475569">{s['src']}</span>
        </div>
        <div style="text-align:right">
          <div style="font-size:24px;font-weight:700;color:{col};font-family:monospace">{s['conviction']:.0f}</div>
          <div style="font-size:10px;color:#64748b">conviction</div>
        </div>
      </div>
      {timing_banner_html(s)}
      {shock_html(s, nd=2)}
      {yield_banner_html(s)}
      {cot_chip_html(s)}
      {zone_visual_html(s, nd=2)}
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
        <div style="flex:1;height:4px;background:#1e293b;border-radius:2px">
          <div style="width:{s['score']}%;height:100%;background:{col};border-radius:2px"></div>
        </div>
        <span style="font-size:11px;color:#64748b;font-family:monospace">Score {s['score']:.0f}/100</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:10px">
        <div style="background:#1f2937;border-radius:7px;padding:7px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase">PRIX</div>
          <div style="font-family:monospace;font-size:12px;color:#e2e8f0">{s['price']}</div></div>
        <div style="background:#1f2937;border:1px solid rgba(239,68,68,.3);border-radius:7px;padding:7px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase">STOP</div>
          <div style="font-family:monospace;font-size:12px;color:#fca5a5">{s['sl']}</div></div>
        <div style="background:#1f2937;border:1px solid rgba(34,197,94,.25);border-radius:7px;padding:7px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase">TP1</div>
          <div style="font-family:monospace;font-size:12px;color:#86efac">{s['tp1']}</div></div>
        <div style="background:#1f2937;border:1px solid rgba(34,197,94,.15);border-radius:7px;padding:7px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase">TP2</div>
          <div style="font-family:monospace;font-size:12px;color:#86efac">{s['tp2']}</div></div>
      </div>
      <div style="display:flex;gap:5px;flex-wrap:wrap;margin-bottom:8px">
        <span style="font-size:10px;padding:2px 8px;border-radius:20px;background:#1f2937;border:1px solid #1e293b;color:{'#fca5a5' if s['rsi']>70 or s['rsi']<30 else '#94a3b8'}">RSI {s['rsi']:.0f}</span>
        <span style="font-size:10px;padding:2px 8px;border-radius:20px;background:#1f2937;border:1px solid #1e293b">EMA {s['ema_trend']}</span>
        {ma200_badge}
        <span style="font-size:10px;padding:2px 8px;border-radius:20px;background:#1f2937;border:1px solid #1e293b;color:{'#86efac' if s['roc60']>0 else '#fca5a5'}">Mom60 {s['roc60']:+.1f}%</span>
        <span style="font-size:10px;padding:2px 8px;border-radius:20px;background:#1f2937;border:1px solid #1e293b">ATR {s['atr_pct']:.2f}%</span>
        <span style="font-size:10px;padding:2px 8px;border-radius:20px;background:#1f2937;border:1px solid {'#ef4444' if s.get('entry_label')=='Extension' else '#22c55e' if s.get('entry_label')=='Pullback' else '#64748b'};color:{'#fca5a5' if s.get('entry_label')=='Extension' else '#86efac' if s.get('entry_label')=='Pullback' else '#94a3b8'}">📏 {s.get('entry_label','?')} {s.get('dist_ema20_atr',0):+.1f}</span>
        <span style="font-size:10px;padding:2px 8px;border-radius:20px;background:#1f2937;border:1px solid #1e293b">H4 {s.get('h4_dir','—')}</span>
        {mom_pill_html(s)}
      </div>
      {plan_generic_html(s)}
      {details_wrap("🗺️ Zones &amp; niveaux", sd_zones_inner(s, nd=2))}
      {f'<div style="display:flex;gap:5px;flex-wrap:wrap;margin-bottom:8px">' + ''.join(f'<span style="font-size:10px;padding:2px 8px;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.3);border-radius:4px;font-family:monospace;color:#fca5a5">R {r}</span>' for r in s.get('res',[])) + ''.join(f'<span style="font-size:10px;padding:2px 8px;background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.3);border-radius:4px;font-family:monospace;color:#86efac">S {sp}</span>' for sp in s.get('sup',[])) + '</div>' if s.get('res') or s.get('sup') else ''}
      <div style="background:#0a0e1a;border-radius:8px;padding:12px">
        <div style="font-size:13px;color:#e2e8f0;line-height:1.75;margin-bottom:8px">{s['resume']}</div>
        <div style="font-size:11px;color:#94a3b8;line-height:1.7;padding-top:8px;border-top:1px solid #1e293b">
          <span style="color:#64748b;text-transform:uppercase;font-size:9px">Détail technique</span><br>{s['detail']}
        </div>
      </div>
    </div>"""

buys=[s for s in indices_signals if s["direction"]=="BUY"]
sells=[s for s in indices_signals if s["direction"]=="SELL"]
neutral=[s for s in indices_signals if s["direction"]=="NEUTRAL"]
alls=sorted(indices_signals,key=lambda x:x["score"],reverse=True)
now=datetime.now().strftime("%d/%m/%Y %H:%M")
vix_c="#22c55e" if vix_regime=="RISK-ON" else ("#ef4444" if vix_regime=="RISK-OFF" else "#f59e0b")

cards_html="".join(card_index(s) for s in alls)

html_idx=f"""
<div style="font-family:'Space Grotesk',sans-serif;background:#0a0e1a;color:#e2e8f0;border-radius:14px;overflow:hidden">
  <div style="background:#111827;border-bottom:1px solid #1e293b;padding:14px 18px;display:flex;justify-content:space-between;align-items:center">
    <div><span style="font-size:17px;font-weight:700">📊 <span style="color:#06b6d4">Indices</span></span>
    <span style="font-size:12px;color:#64748b;margin-left:10px">Trend following + macro</span></div>
    <div style="font-size:11px;color:#64748b;font-family:monospace">{now}</div>
  </div>
  <div style="background:linear-gradient(135deg,#111827,#1f2937);padding:12px 18px;border-bottom:1px solid #1e293b;display:flex;gap:24px;align-items:center;flex-wrap:wrap">
    <div><div style="font-size:10px;color:#64748b;text-transform:uppercase">Régime marché</div>
    <div style="font-size:15px;font-weight:700;color:{vix_c}">{vix_regime}</div></div>
    <div><div style="font-size:10px;color:#64748b;text-transform:uppercase">VIX</div>
    <div style="font-size:15px;font-weight:700;color:{vix_c};font-family:monospace">{vix_now:.1f}</div></div>
    <div style="display:flex;gap:14px;margin-left:auto">
      <div style="text-align:center"><div style="font-size:20px;font-weight:700;color:#22c55e;font-family:monospace">{len(buys)}</div><div style="font-size:10px;color:#64748b">↑ BUY</div></div>
      <div style="text-align:center"><div style="font-size:20px;font-weight:700;color:#ef4444;font-family:monospace">{len(sells)}</div><div style="font-size:10px;color:#64748b">↓ SELL</div></div>
      <div style="text-align:center"><div style="font-size:20px;font-weight:700;color:#94a3b8;font-family:monospace">{len(neutral)}</div><div style="font-size:10px;color:#64748b">→ NEU</div></div>
    </div>
  </div>
  <div style="padding:16px">{cards_html}</div>
</div>"""

FRAGMENTS["indices"] = html_idx
print(f"\n📊 Indices : {len(buys)} BUY · {len(sells)} SELL · {len(neutral)} NEUTRAL | Régime : {vix_regime}")

# ═══════════════ SECTION MÉTAUX & ÉNERGIE (logique C15 + harmonisation v4) ═══════════════
print("📥 [5/6] Métaux & Énergie...")
# Forex inchangé. Cellule autonome. BUY et SELL traités à égalité.

import requests, numpy as np, pandas as pd
from datetime import datetime
import warnings; warnings.filterwarnings("ignore")

# (clés déjà chargées plus haut dans TWELVE_KEY / FRED_KEY)

# ── Univers MÉTAUX + ÉNERGIE ──────────────────────────────────
COMMODITIES = {
    "GOLD":     {"td":"XAU/USD","yf":"GC=F","label":"Or",        "fam":"Métal",  "dxy_sens":-0.8,"real_rate":True},
    "SILVER":   {"td":"XAG/USD","yf":"SI=F","label":"Argent",    "fam":"Métal",  "dxy_sens":-0.7,"real_rate":True},
    "COPPER":   {"td":"XCU/USD","yf":"HG=F","label":"Cuivre",    "fam":"Métal",  "dxy_sens":-0.4,"real_rate":False},
    "PLATINUM": {"td":"XPT/USD","yf":"PL=F","label":"Platine",   "fam":"Métal",  "dxy_sens":-0.5,"real_rate":False},
    "WTI":      {"td":"WTI/USD","yf":"CL=F","label":"WTI",       "fam":"Énergie","dxy_sens":-0.4,"real_rate":False},
    "BRENT":    {"td":"BRENT/USD","yf":"BZ=F","label":"Brent",   "fam":"Énergie","dxy_sens":-0.4,"real_rate":False},
    "NATGAS":   {"td":"NG/USD", "yf":"NG=F","label":"Gaz nat.",  "fam":"Énergie","dxy_sens":-0.1,"real_rate":False},
}

def fetch_twelve(symbol, outputsize=260):
    global TD_FAILS, TD_OK
    try: TD_FAILS
    except NameError: TD_FAILS = 0; TD_OK = 0
    if not TWELVE_KEY or not USE_TWELVE_DATA or TD_FAILS >= 3: return None
    global _TD_LAST
    try: _TD_LAST
    except NameError: _TD_LAST = 0
    _w = TD_PAUSE_SEC - (time.time() - _TD_LAST)
    if _w > 0: time.sleep(_w)
    _TD_LAST = time.time()
    try:
        r=requests.get("https://api.twelvedata.com/time_series",
            params={"symbol":symbol,"interval":"1day","outputsize":outputsize,
                    "apikey":TWELVE_KEY,"format":"JSON"},timeout=15)
        d=r.json()
        if "values" not in d:
            TD_FAILS += 1
            return None
        TD_FAILS = 0; TD_OK += 1
        df=pd.DataFrame(d["values"]); df["datetime"]=pd.to_datetime(df["datetime"])
        df=df.set_index("datetime").sort_index()
        for c in ["open","high","low","close"]: df[c]=pd.to_numeric(df[c],errors="coerce")
        return df[["open","high","low","close"]].dropna()
    except Exception: return None

def fetch_yf(ticker):
    try:
        import yfinance as yf
        df=yf.download(ticker,period="1y",interval="1d",auto_adjust=True,progress=False)
        if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        df=df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close"})
        return df[["open","high","low","close"]].dropna()
    except Exception: return None

def get_data(meta):
    df=fetch_twelve(meta["td"]); src="TwelveData"
    if df is None or len(df)<50:
        df=fetch_yf(meta["yf"]); src="yfinance"
    return df, src

# ── FRED : Taux réels US 10 ans (DFII10) = LE driver de l'or ──
def fetch_fred_real_rate():
    if not FRED_KEY: return None, None
    try:
        r=requests.get("https://api.stlouisfed.org/fred/series/observations",
            params={"series_id":"DFII10","api_key":FRED_KEY,"file_type":"json",
                    "sort_order":"desc","limit":30},timeout=15)
        obs=r.json().get("observations",[])
        vals=[(o["date"],float(o["value"])) for o in obs if o["value"]!="."]
        if len(vals)<2: return None,None
        current=vals[0][1]
        month_ago=vals[min(20,len(vals)-1)][1]
        trend=current-month_ago   # baisse des taux réels = haussier or
        return current, trend
    except Exception: return None,None

print("📥 Chargement MÉTAUX & ÉNERGIE...")
real_rate_now, real_rate_trend = fetch_fred_real_rate()
if real_rate_now is not None:
    rr_dir = "BAISSE (haussier or)" if real_rate_trend<0 else "HAUSSE (baissier or)"
    print(f"  📊 Taux réels US 10a (FRED DFII10) : {real_rate_now:.2f}% | tendance 1m : {real_rate_trend:+.2f} → {rr_dir}")
else:
    print(f"  ⚠️ Taux réels FRED indisponibles — score or sans ce facteur")

# DXY pour corrélation
dxy_df,_ = get_data({"td":"DXY","yf":"DX-Y.NYB"})
dxy_trend20 = 0
if dxy_df is not None and len(dxy_df)>=20:
    dxy_trend20=float(dxy_df["close"].iloc[-1]/dxy_df["close"].iloc[-20]-1)*100
dxy_dir = "fort" if dxy_trend20>0.5 else ("faible" if dxy_trend20<-0.5 else "neutre")

comm_data={}
for key,meta in COMMODITIES.items():
    df,src=get_data(meta)
    if df is not None and len(df)>=50:
        comm_data[key]={"df":df,"src":src,"meta":meta}
        print(f"  ✅ {meta['label']:<12} {len(df)} barres ({src})")
    else:
        print(f"  ❌ {meta['label']:<12} indisponible")

# ── VIX indépendant + H4 commodities (yfinance batch) ──
try:
    import yfinance as _yf
    _vdf = _yf.download("^VIX", period="3mo", interval="1d", auto_adjust=True, progress=False)
    if isinstance(_vdf.columns, pd.MultiIndex): _vdf.columns = _vdf.columns.get_level_values(0)
    COMM_VIX = float(_vdf["Close"].dropna().iloc[-1])
except Exception:
    COMM_VIX = 18.0
h4_comm = {}
try:
    _h4raw = _yf.download([m["yf"] for m in COMMODITIES.values()], period="60d",
                          interval="4h", auto_adjust=True, progress=False, group_by="ticker")
    for _k, _m in COMMODITIES.items():
        try:
            if _m["yf"] in _h4raw.columns.get_level_values(0):
                h4_comm[_k] = _h4raw[_m["yf"]]["Close"].dropna()
        except Exception: pass
    print(f"   ✅ VIX indépendant : {COMM_VIX:.1f} | H4 chargé pour {len(h4_comm)} actifs")
except Exception: pass

def ema(s,p): return s.ewm(span=p,adjust=False).mean()
def rsi(s,p=14):
    d=s.diff(); g=d.clip(lower=0).rolling(p).mean(); l=(-d.clip(upper=0)).rolling(p).mean()
    return 100-100/(1+g/l.replace(0,np.nan))
def atr(h,l,c,p=14):
    pc=c.shift(1); tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return tr.rolling(p).mean()

def sup_res_levels(c, h, l, nd=2, n_levels=2):
    """Swing highs/lows significatifs sur 60 barres — même logique que forex/indices"""
    if len(c) < 20: return [], []
    hh = h.iloc[-60:].values if len(h)>=60 else h.values
    ll = l.iloc[-60:].values if len(l)>=60 else l.values
    cur = float(c.iloc[-1])
    res = sorted({round(float(hh[i]),nd) for i in range(2,len(hh)-2)
                  if hh[i]>hh[i-1] and hh[i]>hh[i+1] and hh[i]>hh[i-2] and hh[i]>hh[i+2]
                  and hh[i]>cur})[:n_levels]
    sup = sorted({round(float(ll[i]),nd) for i in range(2,len(ll)-2)
                  if ll[i]<ll[i-1] and ll[i]<ll[i+1] and ll[i]<ll[i-2] and ll[i]<ll[i+2]
                  and ll[i]<cur}, reverse=True)[:n_levels]
    return sup, res

# ── SCORE : momentum 40 + tendance 30 + corrél 20 + VIX 10 ────
def score_commodity(key,data):
    df=data["df"]; meta=data["meta"]
    c=df["close"]; h=df["high"]; l=df["low"]; cur=float(c.iloc[-1])
    e20=float(ema(c,20).iloc[-1]); e50=float(ema(c,50).iloc[-1])
    e200=float(ema(c,200).iloc[-1]) if len(c)>=200 else float(ema(c,min(len(c)-1,100)).iloc[-1])
    r=float(rsi(c).iloc[-1]); a=float(atr(h,l,c).iloc[-1]); atr_pct=a/cur*100
    roc60=float(c.iloc[-1]/c.iloc[-60]-1)*100 if len(c)>=60 else 0
    roc120=float(c.iloc[-1]/c.iloc[-120]-1)*100 if len(c)>=120 else roc60

    # 1. MOMENTUM (40%)
    mom=50.0+np.clip(roc60/12,-1,1)*30+np.clip(roc120/20,-1,1)*20
    mom=np.clip(mom,0,100)

    # 2. TENDANCE (30%)
    trend=50.0
    if cur>e200: trend+=18
    else: trend-=18
    if e20>e50: trend+=12
    else: trend-=12
    trend=np.clip(trend,0,100)

    # 3. CORRÉLATION INTER-MARCHÉ (20%)
    #    DXY inverse : DXY faible = haussier commodities
    #    + taux réels pour or/argent
    corr=50.0
    dxy_impact=-meta["dxy_sens"]*np.clip(dxy_trend20/2,-1,1)  # dxy faible & sens negatif -> positif
    corr+=dxy_impact*20
    real_rate_factor=""
    if meta.get("real_rate") and real_rate_now is not None:
        # taux réels en baisse = haussier or/argent
        if real_rate_trend<-0.05: corr+=15; real_rate_factor="taux réels en baisse (haussier)"
        elif real_rate_trend>0.05: corr-=15; real_rate_factor="taux réels en hausse (baissier)"
        else: real_rate_factor="taux réels stables"
    corr=np.clip(corr,0,100)

    # 4. VIX (10%) — or monte en risk-off, énergie baisse
    vix_val = COMM_VIX  # fetch indépendant (plus de couplage caché avec la section indices)
    if meta["fam"]=="Métal" and key in ["GOLD","SILVER"]:
        risk=65 if vix_val>22 else 50  # refuge
    else:
        risk=40 if vix_val>25 else 50  # énergie souffre en risk-off

    score=round(mom*0.40+trend*0.30+corr*0.20+risk*0.10,1)

    ema_trend=("BULLISH" if cur>e20>e50 else "BEARISH" if cur<e20<e50 else "MIXED")
    # BUY et SELL à égalité pour les commodities (vraies tendances 2 sens)
    if score>=65: direction="BUY"; conv=score
    elif score<=35: direction="SELL"; conv=100-score
    else: direction="NEUTRAL"; conv=abs(score-50)*2
    conv=round(min(conv,100),1)

    # Précision d'arrondi selon le prix
    nd = 2 if cur>10 else 4
    sup, res = sup_res_levels(c, h, l, nd=nd)
    dist_ema20_atr = (cur - e20) / a if a > 0 else 0
    entry_label = ("Extension" if abs(dist_ema20_atr) > 1.5
                   else ("Pullback" if abs(dist_ema20_atr) < 0.5 else "Neutre"))
    h4_dir, _h4s = h4_trend(h4_comm.get(key))
    if direction=="BUY":
        sl=round(cur-1.5*a,nd); tp1=round(cur+2*a,nd); tp2=round(cur+3.5*a,nd)
    elif direction=="SELL":
        sl=round(cur+1.5*a,nd); tp1=round(cur-2*a,nd); tp2=round(cur-3.5*a,nd)
    else:
        sl=round(cur-1.5*a,nd); tp1=round(cur+2*a,nd); tp2=round(cur+3.5*a,nd)

    # Explication
    if direction=="BUY":
        resume=f"📈 Signal ACHAT sur {meta['label']}. "
        rs=[]
        if roc60>0: rs.append(f"momentum haussier (+{roc60:.1f}% sur 60j)")
        if cur>e200: rs.append("au-dessus de la MM200")
        if dxy_dir=="faible": rs.append("dollar faible (favorable aux matières premières)")
        if real_rate_factor and "baisse" in real_rate_factor: rs.append(real_rate_factor)
        if rs: resume+="Pourquoi : "+", ".join(rs)+". "
    elif direction=="SELL":
        resume=f"📉 Signal VENTE sur {meta['label']}. "
        rs=[]
        if roc60<0: rs.append(f"momentum baissier ({roc60:.1f}% sur 60j)")
        if cur<e200: rs.append("sous la MM200")
        if dxy_dir=="fort": rs.append("dollar fort (défavorable aux matières premières)")
        if real_rate_factor and "hausse" in real_rate_factor: rs.append(real_rate_factor)
        if rs: resume+="Pourquoi : "+", ".join(rs)+". "
    else:
        resume=f"⏸ Pas de signal clair sur {meta['label']}. Tendance pas assez nette. "
    if r>70: resume+=f"⚠️ RSI {r:.0f} — surachat, prudence. "
    elif r<30: resume+=f"⚠️ RSI {r:.0f} — survente, possible rebond. "

    rr_txt = f" Taux réels US : {real_rate_factor}." if real_rate_factor else ""
    detail=(f"{'📈 BUY' if direction=='BUY' else '📉 SELL' if direction=='SELL' else '⏸ NO TRADE'} — "
            f"Score {score}/100, conviction {conv:.0f}%. "
            f"Momentum 60j {roc60:+.1f}%. Tendance {ema_trend}. "
            f"{'✅' if cur>e200 else '❌'} MM200. RSI {r:.0f}. "
            f"DXY {dxy_dir} ({dxy_trend20:+.1f}%/20j).{rr_txt} ATR {atr_pct:.2f}%.")

    return {"key":key,"label":meta["label"],"fam":meta["fam"],
            "direction":direction,"conviction":conv,"score":score,"price":round(cur,nd),
            "sl":sl,"tp1":tp1,"tp2":tp2,"ema_trend":ema_trend,"rsi":round(r,1),
            "roc60":round(roc60,1),"above_ma200":cur>e200,"atr_pct":round(atr_pct,2),
            "sup":sup,"res":res,
            "dist_ema20_atr":round(dist_ema20_atr,2),"entry_label":entry_label,"h4_dir":h4_dir,
            "atr":round(a,4),"ema20":round(e20,nd),"asset_class":"Métaux/Énergie","pair":key,
            "resume":resume,"detail":detail,"src":data["src"]}

print("\n📊 Calcul des signaux matières premières...")
comm_signals=[]
for key,data in comm_data.items():
    try:
        sig=score_commodity(key,data)
        _c = data["df"]["close"]; _h = data["df"]["high"]; _l = data["df"]["low"]
        ml, mc, mn = compute_maturity(sig, _c, _h, _l)
        sig["maturity"]=ml; sig["maturity_color"]=mc; sig["maturity_note"]=mn
        sig["plan_generic"] = generic_plan(sig)
        _av = sig.get("atr", 0)
        _ndz = 2 if sig["price"] > 10 else 4
        sig["fresh_flag"], sig["fresh_data"] = fresh_momentum(_c, _av)
        sig["sd_demand"], sig["sd_supply"] = detect_sd_zones(_c, _h, _l, _av)
        sig["exit_plan"] = exit_plan_2steps(sig, nd=_ndz)
        sig["timing"] = unified_timing(sig)
        sig["mom_h"] = mom_agreement(_c)
        sig["shock"] = shock_memory(_c, _av)
        sig["zone_ctx"] = zone_context(sig)
        comm_signals.append(sig)
        ic="↑" if sig["direction"]=="BUY" else ("↓" if sig["direction"]=="SELL" else "→")
        print(f"  {ic} {sig['label']:<12} {sig['direction']:<8} score:{sig['score']:.0f} conv:{sig['conviction']:.0f}%")
    except Exception as e:
        print(f"  ⚠️ {key} : {e}")

def card_comm(s):
    col="#22c55e" if s["direction"]=="BUY" else ("#ef4444" if s["direction"]=="SELL" else "#94a3b8")
    icon="↑" if s["direction"]=="BUY" else ("↓" if s["direction"]=="SELL" else "→")
    fam_c="#f59e0b" if s["fam"]=="Métal" else "#10b981"
    return f"""
    <div style="background:#111827;border:1px solid #1e293b;border-radius:12px;padding:16px;margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="background:{col};color:#fff;font-size:12px;font-weight:700;padding:3px 10px;border-radius:6px">{icon} {s['direction']}</span>
          <span style="font-size:17px;font-weight:600;color:#e2e8f0">{s['label']}</span>
          <span style="font-size:10px;color:{fam_c};background:#1f2937;padding:1px 7px;border-radius:4px">{s['fam']}</span>
          <span style="font-size:9px;color:#475569">{s['src']}</span>
        </div>
        <div style="text-align:right">
          <div style="font-size:24px;font-weight:700;color:{col};font-family:monospace">{s['conviction']:.0f}</div>
          <div style="font-size:10px;color:#64748b">conviction</div>
        </div>
      </div>
      {timing_banner_html(s)}
      {shock_html(s, nd=2)}
      {yield_banner_html(s)}
      {cot_chip_html(s)}
      {zone_visual_html(s, nd=2)}
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
        <div style="flex:1;height:4px;background:#1e293b;border-radius:2px">
          <div style="width:{s['score']}%;height:100%;background:{col};border-radius:2px"></div></div>
        <span style="font-size:11px;color:#64748b;font-family:monospace">Score {s['score']:.0f}/100</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:10px">
        <div style="background:#1f2937;border-radius:7px;padding:7px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase">PRIX</div>
          <div style="font-family:monospace;font-size:12px;color:#e2e8f0">{s['price']}</div></div>
        <div style="background:#1f2937;border:1px solid rgba(239,68,68,.3);border-radius:7px;padding:7px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase">STOP</div>
          <div style="font-family:monospace;font-size:12px;color:#fca5a5">{s['sl']}</div></div>
        <div style="background:#1f2937;border:1px solid rgba(34,197,94,.25);border-radius:7px;padding:7px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase">TP1</div>
          <div style="font-family:monospace;font-size:12px;color:#86efac">{s['tp1']}</div></div>
        <div style="background:#1f2937;border:1px solid rgba(34,197,94,.15);border-radius:7px;padding:7px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase">TP2</div>
          <div style="font-family:monospace;font-size:12px;color:#86efac">{s['tp2']}</div></div>
      </div>
      <div style="display:flex;gap:5px;flex-wrap:wrap;margin-bottom:8px">
        <span style="font-size:10px;padding:2px 8px;border-radius:20px;background:#1f2937;border:1px solid #1e293b;color:{'#fca5a5' if s['rsi']>70 or s['rsi']<30 else '#94a3b8'}">RSI {s['rsi']:.0f}</span>
        <span style="font-size:10px;padding:2px 8px;border-radius:20px;background:#1f2937;border:1px solid #1e293b">EMA {s['ema_trend']}</span>
        <span style="font-size:10px;padding:2px 8px;border-radius:20px;background:#1f2937;border:1px solid {'#22c55e' if s['above_ma200'] else '#ef4444'};color:{'#86efac' if s['above_ma200'] else '#fca5a5'}">{'✅ &gt; MM200' if s['above_ma200'] else '❌ &lt; MM200'}</span>
        <span style="font-size:10px;padding:2px 8px;border-radius:20px;background:#1f2937;border:1px solid #1e293b;color:{'#86efac' if s['roc60']>0 else '#fca5a5'}">Mom60 {s['roc60']:+.1f}%</span>
        <span style="font-size:10px;padding:2px 8px;border-radius:20px;background:#1f2937;border:1px solid {'#ef4444' if s.get('entry_label')=='Extension' else '#22c55e' if s.get('entry_label')=='Pullback' else '#64748b'};color:{'#fca5a5' if s.get('entry_label')=='Extension' else '#86efac' if s.get('entry_label')=='Pullback' else '#94a3b8'}">📏 {s.get('entry_label','?')} {s.get('dist_ema20_atr',0):+.1f}</span>
        <span style="font-size:10px;padding:2px 8px;border-radius:20px;background:#1f2937;border:1px solid #1e293b">H4 {s.get('h4_dir','—')}</span>
        {mom_pill_html(s)}
      </div>
      {plan_generic_html(s)}
      {details_wrap("🗺️ Zones &amp; niveaux", sd_zones_inner(s, nd=2))}
      {f'<div style="display:flex;gap:5px;flex-wrap:wrap;margin-bottom:8px">' + ''.join(f'<span style="font-size:10px;padding:2px 8px;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.3);border-radius:4px;font-family:monospace;color:#fca5a5">R {r_}</span>' for r_ in s.get('res',[])) + ''.join(f'<span style="font-size:10px;padding:2px 8px;background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.3);border-radius:4px;font-family:monospace;color:#86efac">S {sp}</span>' for sp in s.get('sup',[])) + '</div>' if (s.get('sup') or s.get('res')) else ''}
      <div style="background:#0a0e1a;border-radius:8px;padding:12px">
        <div style="font-size:13px;color:#e2e8f0;line-height:1.75;margin-bottom:8px">{s['resume']}</div>
        <div style="font-size:11px;color:#94a3b8;line-height:1.7;padding-top:8px;border-top:1px solid #1e293b">
          <span style="color:#64748b;text-transform:uppercase;font-size:9px">Détail technique</span><br>{s['detail']}</div>
      </div>
    </div>"""

metaux=[s for s in comm_signals if s["fam"]=="Métal"]
energie=[s for s in comm_signals if s["fam"]=="Énergie"]
buys=[s for s in comm_signals if s["direction"]=="BUY"]
sells=[s for s in comm_signals if s["direction"]=="SELL"]
now=datetime.now().strftime("%d/%m/%Y %H:%M")
rr_display=f"{real_rate_now:.2f}%" if real_rate_now is not None else "N/A"
rr_c="#22c55e" if (real_rate_trend is not None and real_rate_trend<0) else ("#ef4444" if real_rate_trend is not None else "#64748b")

metaux_html="".join(card_comm(s) for s in sorted(metaux,key=lambda x:x["score"],reverse=True))
energie_html="".join(card_comm(s) for s in sorted(energie,key=lambda x:x["score"],reverse=True))

html_comm=f"""
<style>
.cm-tab{{padding:9px 16px;font-size:13px;font-weight:500;cursor:pointer;border-bottom:2px solid transparent;color:#64748b;display:inline-block}}
.cm-tab.act{{color:#e2e8f0;border-bottom-color:#f59e0b}}
.cm-tc{{display:none;padding:16px}}.cm-tc.act{{display:block}}
</style>
<div style="font-family:'Space Grotesk',sans-serif;background:#0a0e1a;color:#e2e8f0;border-radius:14px;overflow:hidden">
  <div style="background:#111827;border-bottom:1px solid #1e293b;padding:14px 18px;display:flex;justify-content:space-between;align-items:center">
    <div><span style="font-size:17px;font-weight:700">🪙 <span style="color:#f59e0b">Métaux &amp; Énergie</span></span>
    <span style="font-size:12px;color:#64748b;margin-left:10px">Momentum + macro</span></div>
    <div style="font-size:11px;color:#64748b;font-family:monospace">{now}</div>
  </div>
  <div style="background:linear-gradient(135deg,#111827,#1f2937);padding:12px 18px;border-bottom:1px solid #1e293b;display:flex;gap:24px;align-items:center;flex-wrap:wrap">
    <div><div style="font-size:10px;color:#64748b;text-transform:uppercase">Taux réels US 10a (FRED)</div>
    <div style="font-size:15px;font-weight:700;color:{rr_c};font-family:monospace">{rr_display}</div></div>
    <div><div style="font-size:10px;color:#64748b;text-transform:uppercase">Dollar (DXY)</div>
    <div style="font-size:15px;font-weight:700;font-family:monospace">{dxy_dir} ({dxy_trend20:+.1f}%)</div></div>
    <div style="display:flex;gap:14px;margin-left:auto">
      <div style="text-align:center"><div style="font-size:20px;font-weight:700;color:#22c55e;font-family:monospace">{len(buys)}</div><div style="font-size:10px;color:#64748b">↑ BUY</div></div>
      <div style="text-align:center"><div style="font-size:20px;font-weight:700;color:#ef4444;font-family:monospace">{len(sells)}</div><div style="font-size:10px;color:#64748b">↓ SELL</div></div>
    </div>
  </div>
  <div style="background:#111827;border-bottom:1px solid #1e293b;padding:0 18px">
    <span class="cm-tab act" onclick="cmTab('metaux',this)">🥇 Métaux ({len(metaux)})</span>
    <span class="cm-tab" onclick="cmTab('energie',this)">🛢️ Énergie ({len(energie)})</span>
  </div>
  <div id="cm-metaux" class="cm-tc act">
    <div style="font-size:12px;color:#94a3b8;margin-bottom:12px;line-height:1.6;background:#1f2937;border-radius:8px;padding:10px">
      💡 <strong>Edge or :</strong> les taux réels US sont le driver n°1 de l'or. Taux réels en baisse = or haussier. Donnée FRED (DFII10) intégrée au score.
    </div>
    {metaux_html if metaux_html else '<div style="color:#64748b;padding:16px;text-align:center">Aucune donnée métaux</div>'}
  </div>
  <div id="cm-energie" class="cm-tc">
    {energie_html if energie_html else '<div style="color:#64748b;padding:16px;text-align:center">Aucune donnée énergie</div>'}
  </div>
</div>
<script>
function cmTab(name,el){{
  document.querySelectorAll('.cm-tc').forEach(t=>t.classList.remove('act'));
  document.querySelectorAll('.cm-tab').forEach(t=>t.classList.remove('act'));
  document.getElementById('cm-'+name).classList.add('act'); el.classList.add('act');
}}
</script>"""

FRAGMENTS["metals"] = html_comm
print(f"\n🪙 Métaux/Énergie : {len(buys)} BUY · {len(sells)} SELL")
if real_rate_now is not None:
    print(f"   Taux réels US : {real_rate_now:.2f}% (driver clé de l'or)")
try:
    TD_REPORT = f"TD {TD_OK}/{TD_OK+TD_FAILS if (TD_OK+TD_FAILS)>0 else 13}" + (" · coupé après 3 échecs" if TD_FAILS >= 3 else "")
except NameError:
    TD_REPORT = "TD désactivé"
print(f"   📡 Sources indices/métaux : {TD_REPORT} — reste via yfinance")
RESULTS["indices_signals"] = indices_signals
RESULTS["comm_signals"] = comm_signals
print("✅ Multi-actifs calculés : DXY + " + str(len(indices_signals)) + " indices + " + str(len(comm_signals)) + " commodities")

# ╔══════════════════════════════════════════════════════════╗
# ║  Cellule 4/5 : SYNTHÈSE & PAGE UNIQUE — V7               ║
# ║  Lecture pro : régime×Top3 · doublons · checklist ·      ║
# ║  page 🏦 Taux · tableau COT · mode weekend               ║
# ║  Edge Filter · Vue d'ensemble · Top 3 · Risque · Journal ║
# ║  → Génère LA page HTML navigable + fichier téléchargeable║
# ╚══════════════════════════════════════════════════════════╝
# ═══════ EDGE FILTER PRO (logique C12 inchangée) ═══════

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings; warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# 1. SAISONNALITÉ — patterns historiques G10 (10 ans de data)
# ─────────────────────────────────────────────────────────────

print("📥 Chargement données historiques pour saisonnalité (10 ans)...")

SEASONAL_TICKERS = {
    "EURUSD":"EURUSD=X", "USDJPY":"JPY=X",  "GBPUSD":"GBPUSD=X",
    "AUDUSD":"AUDUSD=X", "USDCAD":"CAD=X",  "DXY":"DX-Y.NYB",
    "GOLD":"GC=F",       "SPX":"^GSPC",      "OIL":"CL=F",
}

hist_data = {}
for name, ticker in SEASONAL_TICKERS.items():
    try:
        df = yf.download(ticker, period="10y", interval="1d",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if len(df) > 200:
            hist_data[name] = df["Close"].dropna()
    except:
        pass

print(f"✅ {len(hist_data)} séries chargées")

def monthly_seasonality(series, name):
    """
    Retourne le retour moyen par mois sur l'historique complet.
    Positif = mois historiquement haussier pour cet actif.
    """
    df = series.copy().to_frame("price")
    df["month"] = df.index.month
    df["year"]  = df.index.year
    df["ret"]   = df["price"].pct_change()
    monthly = df.groupby(["year","month"])["ret"].sum().reset_index()
    avg = monthly.groupby("month")["ret"].agg(["mean","std","count"]).reset_index()
    avg.columns = ["month","avg_ret","std_ret","n_years"]
    avg["avg_ret_pct"] = (avg["avg_ret"]*100).round(3)
    avg["consistency"] = (avg["avg_ret"] / avg["std_ret"].replace(0,np.nan)).fillna(0).round(2)
    return avg

def weekly_seasonality(series):
    """Retour moyen par jour de la semaine (0=Lundi, 4=Vendredi)"""
    df = series.copy().to_frame("price")
    df["dow"] = df.index.dayofweek
    df["ret"] = df["price"].pct_change()
    avg = df.groupby("dow")["ret"].mean() * 100
    return avg.round(4)

# Calcul saisonnalité pour les paires clés
print("📊 Calcul saisonnalité mensuelle...")
seasonal_results = {}
for name, series in hist_data.items():
    seasonal_results[name] = monthly_seasonality(series, name)

# Mois actuel
now        = datetime.now()
cur_month  = now.month
cur_dow    = now.weekday()  # 0=Lundi
cur_week   = now.isocalendar()[1]
MONTH_NAMES = {1:"Janvier",2:"Février",3:"Mars",4:"Avril",5:"Mai",6:"Juin",
               7:"Juillet",8:"Août",9:"Septembre",10:"Octobre",11:"Novembre",12:"Décembre"}
DOW_NAMES   = {0:"Lundi",1:"Mardi",2:"Mercredi",3:"Jeudi",4:"Vendredi"}

# Patterns saisonniers connus (recherche empirique sur 20 ans)
KNOWN_PATTERNS = {
    "Jan_W1": {
        "desc": "Effet Janvier — repositionnement institutionnel",
        "usd_bias": +1,
        "note": "Le dollar est souvent fort les 2 premières semaines. Les fonds réallouent après les fêtes.",
        "fiable": "🔥 Très fiable (>65% des années)"
    },
    "Apr_May": {
        "desc": "Sell in May — flight to safety",
        "usd_bias": +1,
        "note": "Les indices baissent souvent en Avril-Mai → USD et JPY s'apprécient.",
        "fiable": "💪 Fiable (>58% des années)"
    },
    "Jul_Aug": {
        "desc": "Été — volume bas, faux breakouts",
        "usd_bias": 0,
        "note": "Juillet-Août : liquidité réduite, stop hunts fréquents. Réduire la taille de 50%.",
        "fiable": "⚠️ Dangereux pour trend following"
    },
    "Sep_Oct": {
        "desc": "Rentrée — retour de la volatilité",
        "usd_bias": 0,
        "note": "Septembre est souvent le mois le plus volatile. Les grandes moves de l'année démarrent ici.",
        "fiable": "🔥 Volatilité élevée — opportunités max"
    },
    "Dec_W3": {
        "desc": "Window dressing — liquidité nulle",
        "usd_bias": 0,
        "note": "Les banques ferment leurs books après le 15/12. Spreads larges, moves irrationnels.",
        "fiable": "⛔ Éviter les nouvelles positions"
    },
}

def get_seasonal_bias(month, week_of_month):
    """Retourne le biais saisonnier actuel"""
    biases = []
    if month == 1 and week_of_month <= 2:
        biases.append(KNOWN_PATTERNS["Jan_W1"])
    if month in [4, 5]:
        biases.append(KNOWN_PATTERNS["Apr_May"])
    if month in [7, 8]:
        biases.append(KNOWN_PATTERNS["Jul_Aug"])
    if month in [9, 10]:
        biases.append(KNOWN_PATTERNS["Sep_Oct"])
    if month == 12 and week_of_month >= 3:
        biases.append(KNOWN_PATTERNS["Dec_W3"])
    return biases

# Semaine du mois (1-4)
week_of_month = (now.day - 1) // 7 + 1
seasonal_biases = get_seasonal_bias(cur_month, week_of_month)

# Retour historique du mois actuel pour chaque actif
seasonal_now = {}
for name, df in seasonal_results.items():
    row = df[df["month"] == cur_month]
    if len(row) > 0:
        seasonal_now[name] = {
            "avg_ret": float(row["avg_ret_pct"].iloc[0]),
            "consistency": float(row["consistency"].iloc[0]),
            "n_years": int(row["n_years"].iloc[0])
        }

print(f"✅ Mois actuel : {MONTH_NAMES[cur_month]} (semaine {week_of_month}/4)")

# ─────────────────────────────────────────────────────────────
# 2. CALENDRIER ÉCONOMIQUE — événements High Impact
# ─────────────────────────────────────────────────────────────

print("📅 Calendrier économique...")

# Jours fixes récurrents (approximations)
def get_upcoming_events(days_ahead=7):
    """
    Retourne les événements macro majeurs des N prochains jours.
    Source : patterns récurrents connus.
    Idéalement remplacer par une API (Forex Factory, Investing.com).
    """
    events = []
    today = datetime.now().date()

    for i in range(days_ahead + 1):
        d = today + timedelta(days=i)
        month, day, dow = d.month, d.day, d.weekday()

        # NFP = premier vendredi du mois
        if dow == 4:  # Vendredi
            first_friday = d - timedelta(weeks=(day-1)//7)
            if d == first_friday:
                events.append({
                    "date": str(d), "event": "NFP — Non-Farm Payrolls",
                    "impact": "🚨 HIGH", "currency": "USD",
                    "rule": "PAS de position 24h avant, 2h après",
                    "days_away": i
                })

        # CPI US = ~13 du mois (approximation)
        if 11 <= day <= 15 and dow in [1,2,3]:  # Mar-Jeu
            events.append({
                "date": str(d), "event": "CPI US (estimé)",
                "impact": "🚨 HIGH", "currency": "USD",
                "rule": "Fermer les positions USD avant 14h30 UTC",
                "days_away": i
            })

        # FOMC = ~7ème et 20ème du mois alternés (6-7 fois/an)
        if day in [26, 27, 28] and dow in [2, 3] and month in [1,3,5,6,7,9,11,12]:
            events.append({
                "date": str(d), "event": "FOMC Meeting (estimé)",
                "impact": "🚨 HIGH", "currency": "USD",
                "rule": "Réduire l'exposition USD de 70% le jour J",
                "days_away": i
            })

        # ECB = ~7ème jeudi du mois (6 fois/an)
        if dow == 3 and 6 <= day <= 12 and month in [1,3,4,6,7,9,10,12]:
            events.append({
                "date": str(d), "event": "ECB Meeting (estimé)",
                "impact": "⚠️ HIGH", "currency": "EUR",
                "rule": "Attention EUR/USD — volatilité intraday forte",
                "days_away": i
            })

        # BoJ = irrégulier mais souvent fin de mois
        if dow == 4 and 25 <= day <= 31 and month in [1,3,4,6,7,9,10,12]:
            events.append({
                "date": str(d), "event": "BoJ Meeting (estimé)",
                "impact": "⚠️ MEDIUM", "currency": "JPY",
                "rule": "Surveiller USD/JPY — risk de gap",
                "days_away": i
            })

    # Trier par date
    return sorted(events, key=lambda x: x["days_away"])

upcoming_events = get_upcoming_events(7)

# Filtre trade : événement dans les 24h ?
events_24h = [e for e in upcoming_events if e["days_away"] <= 1]
events_48h = [e for e in upcoming_events if e["days_away"] <= 2]
news_filter = "BLOCK"  if len(events_24h) > 0 else               "CAUTION" if len(events_48h) > 0 else "CLEAR"

print(f"✅ {len(upcoming_events)} événements détectés sur 7 jours")
print(f"   Filtre news : {news_filter}")

# ─────────────────────────────────────────────────────────────
# 3. SESSIONS DE TRADING — timing optimal
# ─────────────────────────────────────────────────────────────

def get_session_status():
    """
    Sessions forex en UTC :
    Tokyo    : 00:00 – 09:00 UTC
    Londres  : 07:00 – 16:00 UTC
    New York : 12:00 – 21:00 UTC
    Overlap  : 12:00 – 16:00 UTC (volume max)
    """
    utc_now = datetime.utcnow()
    hour    = utc_now.hour
    dow     = utc_now.weekday()

    # Weekend
    if dow >= 5:
        return {"status":"FERMÉ","sessions":[],"quality":"⛔ AUCUNE",
                "advice":"Marché fermé. Pas de trade.", "score":0,
                "utc_hour":hour, "overlap":False, "is_friday":False}

    sessions = []
    if 0  <= hour < 9:  sessions.append("Tokyo")
    if 7  <= hour < 16: sessions.append("Londres")
    if 12 <= hour < 21: sessions.append("New York")

    overlap   = "Londres" in sessions and "New York" in sessions
    is_friday = dow == 4
    after_ny  = hour >= 20

    if overlap:
        quality = "🔥 OPTIMAL"
        advice  = "Overlap Londres/NY — 70% du volume journalier. Conditions idéales pour entrer."
        score   = 100
    elif "Londres" in sessions:
        quality = "💪 TRÈS BON"
        advice  = "Session Londres active — bonne liquidité sur EUR, GBP, CHF."
        score   = 80
    elif "New York" in sessions:
        quality = "✅ BON"
        advice  = "Session New York — bonne liquidité USD. Attention aux moves post-13h."
        score   = 70
    elif "Tokyo" in sessions:
        quality = "⚠️ LIMITÉ"
        advice  = "Session Tokyo — privilégier AUD/JPY, USD/JPY, NZD/USD uniquement."
        score   = 40
    else:
        quality = "❌ FAIBLE"
        advice  = "Transition entre sessions — liquidité très faible. Attendre l'ouverture Londres."
        score   = 10

    if is_friday and hour >= 18:
        quality = "⛔ DANGEREUX"
        advice  = "Vendredi soir — stop hunts fréquents avant le weekend. Fermer les positions ou réduire."
        score   = 5

    return {
        "status":  " + ".join(sessions) if sessions else "INTER-SESSION",
        "sessions": sessions, "overlap": overlap,
        "quality":  quality,  "advice": advice,
        "score":    score,    "utc_hour": hour,
        "is_friday": is_friday,
    }

session_status = get_session_status()

# Meilleurs jours de la semaine par paire (empirique)
BEST_DAYS = {
    "EURUSD": [1,2,3],   # Mar-Jeu
    "GBPUSD": [1,2,3],
    "USDJPY": [1,2,3],
    "AUDUSD": [1,2,3],
    "USDCAD": [1,2,3],
    "USDCHF": [1,2,3],
    "NZDUSD": [2,3],
    "USDNOK": [1,2,3],
}
is_good_day = cur_dow in [1,2,3]  # Mar-Jeu = meilleurs jours global

print(f"✅ Session actuelle : {session_status['status']} | {session_status['quality']}")

# ─────────────────────────────────────────────────────────────
# 4. CORRÉLATIONS INTER-MARCHÉS
# ─────────────────────────────────────────────────────────────

print("📊 Calcul corrélations inter-marchés (60 jours)...")

def compute_correlations(hist_data, lookback=60):
    """
    Corrélations connues à surveiller :
    DXY ↔ GOLD    : ~-0.80 (inverse)
    DXY ↔ EURUSD  : ~-0.95 (très forte inverse)
    SPX ↔ AUDJPY  : ~+0.75 (risk-on)
    OIL ↔ USDCAD  : ~-0.80 (inverse)
    DXY ↔ USDJPY  : ~+0.70
    """
    results = {}
    pairs_to_check = [
        ("DXY",    "GOLD",   -0.80, "DXY ↔ Gold",    "Si les deux montent → anomalie, signal d'alarme"),
        ("DXY",    "EURUSD", -0.95, "DXY ↔ EUR/USD", "Corrélation inverse la plus forte du FX"),
        ("SPX",    "AUDUSD", +0.75, "SPX ↔ AUD/USD", "Risk-on/off — indices = proxy appétit risque"),
        ("OIL",    "USDCAD", -0.80, "Oil ↔ USD/CAD", "Pétrole fort → CAD fort → USD/CAD baisse"),
        ("DXY",    "USDJPY", +0.70, "DXY ↔ USD/JPY", "USD bull = USD/JPY monte généralement"),
        ("GOLD",   "AUDUSD", +0.65, "Gold ↔ AUD/USD","Australie = gros producteur or"),
    ]

    for a1, a2, expected, label, note in pairs_to_check:
        if a1 not in hist_data or a2 not in hist_data:
            continue
        s1 = hist_data[a1].tail(lookback)
        s2 = hist_data[a2].tail(lookback)
        idx = s1.index.intersection(s2.index)
        if len(idx) < 20:
            continue
        r1 = s1.loc[idx].pct_change().dropna()
        r2 = s2.loc[idx].pct_change().dropna()
        corr = round(float(r1.corr(r2)), 3)
        # Divergence = corrélation actuelle très différente du normal
        diverging = abs(corr - expected) > 0.30
        results[label] = {
            "corr": corr, "expected": expected, "label": label,
            "note": note, "diverging": diverging,
            "status": "⚡ DIVERGENCE" if diverging else "✅ Normal",
        }

    return results

corr_results = compute_correlations(hist_data)
divergences  = [v for v in corr_results.values() if v["diverging"]]
print(f"✅ {len(corr_results)} corrélations calculées")
if divergences:
    print(f"   ⚡ {len(divergences)} divergence(s) détectée(s) — opportunités potentielles")

# ─────────────────────────────────────────────────────────────
# 5. SCORE DE CONFLUENCE FINALE
# ─────────────────────────────────────────────────────────────

def compute_edge_score(pair, signal_direction, dxy_score_val=None):
    """
    Score de confluence 0-6 avant exécution.
    Règle pro : minimum 4/6 pour entrer.

    Facteurs :
    1. Signal technique (score conviction du dashboard)
    2. Session favorable
    3. Pas de news dans 24h
    4. Saisonnalité neutre ou favorable
    5. Corrélation inter-marché confirme
    6. Bon jour de la semaine
    """
    score = 0
    details = []

    # 1. Session
    if session_status["score"] >= 70:
        score += 1
        details.append(("✅", "Session", session_status["quality"]))
    elif session_status["score"] >= 40:
        details.append(("⚠️", "Session", session_status["quality"] + " — qualité réduite"))
    else:
        details.append(("❌", "Session", session_status["quality"]))

    # 2. News filter
    if news_filter == "CLEAR":
        score += 1
        details.append(("✅", "News", "Aucun événement High Impact dans 24h"))
    elif news_filter == "CAUTION":
        details.append(("⚠️", "News", f"Événement dans 48h — réduire la taille"))
    else:
        details.append(("❌", "News", f"Événement High Impact dans 24h — NE PAS ENTRER"))

    # 3. Saisonnalité
    summer_months = [7, 8]
    bad_months    = [12] if week_of_month >= 3 else []
    if cur_month in summer_months:
        details.append(("⚠️", "Saisonnalité", "Été — volume bas, réduire taille 50%"))
    elif cur_month in bad_months:
        details.append(("❌", "Saisonnalité", "Décembre fin de mois — window dressing"))
    else:
        score += 1
        details.append(("✅", "Saisonnalité", f"{MONTH_NAMES[cur_month]} — pas de filtre saisonnier"))

    # 4. Jour de la semaine
    if cur_dow in [1,2,3]:
        score += 1
        details.append(("✅", "Jour", f"{DOW_NAMES.get(cur_dow,'?')} — optimal (Mar-Jeu)"))
    elif cur_dow == 0:
        details.append(("⚠️", "Jour", "Lundi — range souvent imprévisible en ouverture"))
    else:
        details.append(("❌", "Jour", "Vendredi — stop hunts, pas de nouvelles positions"))

    # 5. Corrélation inter-marché
    corr_ok = True
    corr_note = "Corrélations normales"
    if pair in ["EURUSD","GBPUSD","AUDUSD","NZDUSD"]:
        # Si DXY et Gold montent ensemble → anomalie → pas de signal SELL clair
        dxy_gold = corr_results.get("DXY ↔ Gold")
        if dxy_gold and dxy_gold["diverging"]:
            corr_ok = False
            corr_note = "⚡ DXY/Gold divergent — marché incohérent, signal moins fiable"
    if "JPY" in pair:
        spx_aud = corr_results.get("SPX ↔ AUD/USD")
        if spx_aud and spx_aud["diverging"]:
            corr_note = "⚡ Risk-on/off divergent sur SPX/AUD"
    if corr_ok:
        score += 1
        details.append(("✅", "Corrélations", corr_note))
    else:
        details.append(("⚠️", "Corrélations", corr_note))

    # 6. DXY alignment
    if dxy_score_val is not None:
        usd_base  = ["USDJPY","USDCAD","USDCHF","USDNOK"]
        usd_quote = ["EURUSD","GBPUSD","AUDUSD","NZDUSD"]
        dxy_bull  = dxy_score_val >= 60
        dxy_bear  = dxy_score_val <= 40
        aligned   = False
        if pair in usd_base  and signal_direction=="BUY"  and dxy_bull: aligned=True
        if pair in usd_base  and signal_direction=="SELL" and dxy_bear: aligned=True
        if pair in usd_quote and signal_direction=="SELL" and dxy_bull: aligned=True
        if pair in usd_quote and signal_direction=="BUY"  and dxy_bear: aligned=True
        if aligned:
            score += 1
            details.append(("✅", "DXY alignment", f"DXY ({dxy_score_val:.0f}/100) confirme le {signal_direction}"))
        else:
            details.append(("⚠️", "DXY alignment", f"DXY ({dxy_score_val:.0f}/100) neutre ou contre le signal"))

    verdict = ("🚀 ENTRER" if score >= 5 else
               "✅ OK"     if score >= 4 else
               "⚠️ ATTENDRE" if score >= 3 else
               "⛔ PASSER")
    verdict_col = ("#22c55e" if score>=5 else
                   "#86efac" if score>=4 else
                   "#f59e0b" if score>=3 else "#ef4444")

    return {"score":score,"max":6,"details":details,
            "verdict":verdict,"verdict_col":verdict_col}

# ─────────────────────────────────────────────────────────────
# 6. DASHBOARD HTML
# ─────────────────────────────────────────────────────────────

now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

# Seasonal table — retour moyen par mois pour DXY
seasonal_rows = ""
if "DXY" in seasonal_results:
    df_s = seasonal_results["DXY"]
    for _, row in df_s.iterrows():
        m = int(row["month"])
        avg = float(row["avg_ret_pct"])
        cons = float(row["consistency"])
        col = "#22c55e" if avg > 0.3 else ("#ef4444" if avg < -0.3 else "#94a3b8")
        cur_mark = "◀ ACTUEL" if m == cur_month else ""
        bar_w = min(abs(avg)*20, 100)
        bar_c = "#22c55e" if avg>0 else "#ef4444"
        seasonal_rows += f"""<tr style="{'background:rgba(59,130,246,.08)' if m==cur_month else ''}">
          <td style="font-weight:500">{MONTH_NAMES[m]} {cur_mark}</td>
          <td style="font-family:monospace;color:{col};text-align:right">{avg:+.2f}%</td>
          <td><div style="width:{bar_w}px;height:6px;background:{bar_c};border-radius:3px"></div></td>
          <td style="color:#64748b;text-align:right">{cons:+.2f}</td>
          <td style="color:#64748b;text-align:right">{int(row["n_years"])} ans</td>
        </tr>"""

# Events HTML
events_html = ""
for e in upcoming_events[:6]:
    imp_c = "#ef4444" if "HIGH" in e["impact"] else "#f59e0b"
    days  = e["days_away"]
    dist  = "Aujourd'hui" if days==0 else (f"Demain" if days==1 else f"Dans {days}j")
    events_html += f"""<div style="display:flex;justify-content:space-between;align-items:start;
        padding:8px 10px;background:#1f2937;border-radius:7px;margin-bottom:5px">
        <div>
          <div style="font-size:12px;font-weight:600;color:#e2e8f0">{e['event']}</div>
          <div style="font-size:11px;color:#64748b;margin-top:2px">{e['rule']}</div>
        </div>
        <div style="text-align:right;min-width:90px">
          <div style="font-size:11px;color:{imp_c}">{e['impact']}</div>
          <div style="font-size:11px;color:#64748b">{dist} · {e['date']}</div>
        </div>
      </div>"""
if not events_html:
    events_html = '<div style="color:#64748b;text-align:center;padding:12px">✅ Aucun événement majeur cette semaine</div>'

# Corrélations HTML
corr_html = ""
for label, data in corr_results.items():
    exp_c = "#22c55e" if not data["diverging"] else "#ef4444"
    diff  = round(data["corr"]-data["expected"],3)
    corr_html += f"""<div style="padding:8px 10px;background:#1f2937;border-radius:7px;
        margin-bottom:5px;border-left:3px solid {exp_c}">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px">
          <span style="font-size:12px;font-weight:600">{label}</span>
          <span style="font-size:11px;color:{exp_c}">{data['status']}</span>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:11px;color:#64748b">
          <span>Actuel: <span style="color:#e2e8f0;font-family:monospace">{data['corr']}</span></span>
          <span>Attendu: <span style="font-family:monospace">{data['expected']}</span></span>
          <span>Δ: <span style="color:{'#ef4444' if abs(diff)>0.2 else '#94a3b8'};font-family:monospace">{diff:+.3f}</span></span>
        </div>
        <div style="font-size:10px;color:#64748b;margin-top:3px;font-style:italic">{data['note']}</div>
      </div>"""

# Edge score pour top paires
# Essayer de récupérer dxy_score depuis la cellule précédente
try:
    dxy_score_for_edge = dxy_score
except:
    dxy_score_for_edge = 50

TOP_PAIRS_TO_CHECK = [
    ("EURUSD","SELL"), ("USDJPY","BUY"), ("GBPUSD","SELL"),
    ("AUDUSD","SELL"), ("USDCAD","BUY"), ("EURUSD","BUY"),
]
edge_cards = ""
for pair, direction in TOP_PAIRS_TO_CHECK:
    edge = compute_edge_score(pair, direction, dxy_score_for_edge)
    details_html = "".join(
        f'<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:11px;border-bottom:1px solid #1e293b"><span style="width:16px;text-align:center">{ico}</span><span style="width:90px;color:#64748b">{cat}</span><span style="color:#94a3b8">{note}</span></div>'
        for ico,cat,note in edge["details"]
    )
    dir_c = "#22c55e" if direction=="BUY" else "#ef4444"
    edge_cards += f"""<div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:14px;margin-bottom:8px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
          <div>
            <span style="font-family:monospace;font-size:15px;font-weight:600">{pair}</span>
            <span style="color:{dir_c};font-size:12px;font-weight:700;margin-left:8px">{direction}</span>
          </div>
          <div style="text-align:right">
            <div style="font-size:20px;font-weight:700;font-family:monospace;color:{edge['verdict_col']}">{edge['score']}/6</div>
            <div style="font-size:11px;color:{edge['verdict_col']};font-weight:600">{edge['verdict']}</div>
          </div>
        </div>
        <div style="height:4px;background:#1e293b;border-radius:2px;margin-bottom:10px">
          <div style="width:{edge['score']/6*100:.0f}%;height:100%;background:{edge['verdict_col']};border-radius:2px"></div>
        </div>
        {details_html}
      </div>"""

# Seasonal biases actuels
bias_html = ""
for b in seasonal_biases:
    bias_c = "#22c55e" if b["usd_bias"]>0 else ("#ef4444" if b["usd_bias"]<0 else "#f59e0b")
    bias_html += f"""<div style="background:#1f2937;border-radius:8px;padding:10px;margin-bottom:6px;
        border-left:3px solid {bias_c}">
        <div style="font-size:12px;font-weight:600;margin-bottom:3px">{b['desc']}</div>
        <div style="font-size:11px;color:#94a3b8;margin-bottom:4px">{b['note']}</div>
        <div style="font-size:10px;color:#64748b">{b['fiable']}</div>
      </div>"""
if not bias_html:
    bias_html = f'<div style="background:#1f2937;border-radius:8px;padding:10px;color:#86efac;font-size:12px">✅ {MONTH_NAMES[cur_month]} — Pas de filtre saisonnier majeur actif</div>'

# News filter badge
nf_c   = {"CLEAR":"#22c55e","CAUTION":"#f59e0b","BLOCK":"#ef4444"}[news_filter]
nf_txt = {"CLEAR":"✅ Aucun événement 24h","CAUTION":"⚠️ Événement dans 48h","BLOCK":"⛔ News High Impact < 24h"}[news_filter]

html_edge = f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
  .ef-wrap {{ font-family:'Space Grotesk',sans-serif; background:#0a0e1a; color:#e2e8f0; border-radius:14px; overflow:hidden; }}
  .ef-tab {{ padding:9px 16px;font-size:13px;font-weight:500;cursor:pointer;border-bottom:2px solid transparent;color:#64748b;display:inline-block; }}
  .ef-tab.act {{ color:#e2e8f0; border-bottom-color:#8b5cf6; }}
  .ef-tc {{ display:none; padding:16px; }}
  .ef-tc.act {{ display:block; }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  th {{ background:#1f2937;padding:6px 8px;text-align:left;font-size:10px;text-transform:uppercase;color:#64748b;border-bottom:1px solid #1e293b; }}
  td {{ padding:5px 8px; border-bottom:1px solid #111827; }}
</style>

<div class="ef-wrap">
  <!-- Header -->
  <div style="background:#111827;border-bottom:1px solid #1e293b;padding:14px 18px;display:flex;justify-content:space-between;align-items:center">
    <div>
      <span style="font-size:17px;font-weight:700">Edge <span style="color:#8b5cf6">Filter</span> Pro</span>
      <span style="font-size:12px;color:#64748b;margin-left:10px">Saisonnalité · News · Sessions · Corrélations</span>
    </div>
    <div style="font-size:11px;color:#64748b;font-family:monospace">{now_str}</div>
  </div>

  <!-- Status bar -->
  <div style="background:#111827;border-bottom:1px solid #1e293b;padding:10px 18px;display:flex;gap:20px;flex-wrap:wrap;align-items:center">
    <div>
      <div style="font-size:10px;color:#64748b;text-transform:uppercase">Session</div>
      <div style="font-size:13px;font-weight:600;color:{'#22c55e' if session_status['score']>=70 else '#f59e0b' if session_status['score']>=40 else '#ef4444'}">{session_status['quality']}</div>
    </div>
    <div>
      <div style="font-size:10px;color:#64748b;text-transform:uppercase">Sessions actives</div>
      <div style="font-size:13px;font-weight:600">{session_status['status']} <span style="font-size:10px;color:#64748b">{session_status['utc_hour']}h UTC</span></div>
    </div>
    <div>
      <div style="font-size:10px;color:#64748b;text-transform:uppercase">News filter</div>
      <div style="font-size:13px;font-weight:600;color:{nf_c}">{nf_txt}</div>
    </div>
    <div>
      <div style="font-size:10px;color:#64748b;text-transform:uppercase">Jour</div>
      <div style="font-size:13px;font-weight:600;color:{'#22c55e' if is_good_day else '#f59e0b'}">{DOW_NAMES.get(cur_dow,'?')} {'✅' if is_good_day else '⚠️'}</div>
    </div>
    <div>
      <div style="font-size:10px;color:#64748b;text-transform:uppercase">Mois</div>
      <div style="font-size:13px;font-weight:600">{MONTH_NAMES[cur_month]} S{week_of_month}</div>
    </div>
    <div style="margin-left:auto">
      <div style="font-size:10px;color:#64748b;text-transform:uppercase">Divergences</div>
      <div style="font-size:13px;font-weight:600;color:{'#ef4444' if divergences else '#22c55e'}">{len(divergences)} {'⚡' if divergences else '✅'}</div>
    </div>
  </div>

  <!-- Tabs -->
  <div style="background:#111827;border-bottom:1px solid #1e293b;padding:0 18px">
    <span class="ef-tab act" onclick="efTab('edge',this)">🎯 Confluence Score</span>
    <span class="ef-tab" onclick="efTab('seasonal',this)">📅 Saisonnalité</span>
    <span class="ef-tab" onclick="efTab('news',this)">📰 Calendrier</span>
    <span class="ef-tab" onclick="efTab('session',this)">🕐 Sessions</span>
    <span class="ef-tab" onclick="efTab('corr',this)">🔗 Corrélations</span>
  </div>

  <!-- Edge Score -->
  <div id="ef-edge" class="ef-tc act">
    <div style="font-size:13px;color:#94a3b8;margin-bottom:14px;line-height:1.6">
      Score de confluence avant exécution — règle pro : <strong style="color:#e2e8f0">minimum 4/6 pour entrer</strong>.
      En dessous de 4, le trade peut être techniquement parfait mais le contexte n'est pas favorable.
    </div>
    {edge_cards}
  </div>

  <!-- Saisonnalité -->
  <div id="ef-seasonal" class="ef-tc">
    <div style="margin-bottom:16px">
      <div style="font-size:13px;font-weight:600;margin-bottom:8px">Patterns actifs — {MONTH_NAMES[cur_month]}</div>
      {bias_html}
    </div>
    <div style="font-size:13px;font-weight:600;margin-bottom:8px">Retour historique DXY par mois (10 ans)</div>
    <div style="overflow-x:auto">
    <table>
      <thead><tr><th>Mois</th><th style="text-align:right">Retour moy.</th><th>Biais visuel</th><th style="text-align:right">Consistance</th><th style="text-align:right">Historique</th></tr></thead>
      <tbody>{seasonal_rows}</tbody>
    </table>
    </div>
    <div style="font-size:11px;color:#64748b;margin-top:8px;font-style:italic">
      Consistance = retour moyen / écart-type. >0.3 = signal fort. Source : 10 ans de données daily.
    </div>
  </div>

  <!-- Calendrier -->
  <div id="ef-news" class="ef-tc">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
      <div style="font-size:13px;font-weight:600">Événements macro — 7 prochains jours</div>
      <div style="font-size:12px;padding:4px 12px;background:rgba(0,0,0,.3);border:1px solid {nf_c};border-radius:6px;color:{nf_c};font-weight:600">{nf_txt}</div>
    </div>
    {events_html}
    <div style="margin-top:14px;background:#1f2937;border-radius:8px;padding:10px;font-size:11px;color:#94a3b8;line-height:1.7">
      <strong style="color:#e2e8f0">Règles du trader pro :</strong><br>
      🚨 NFP / CPI / FOMC : pas de nouvelle position 24h avant, attendre 2h après<br>
      ⚠️ ECB / BoJ / BoE : réduire taille de 50% le jour J<br>
      💡 Le premier move post-news est souvent un faux signal — attendre la clôture de la 2ème bougie
    </div>
  </div>

  <!-- Sessions -->
  <div id="ef-session" class="ef-tc">
    <div style="background:#1f2937;border-radius:10px;padding:14px;margin-bottom:14px">
      <div style="font-size:14px;font-weight:600;margin-bottom:6px">{session_status['quality']} — {session_status['status']}</div>
      <div style="font-size:13px;color:#94a3b8;line-height:1.6">{session_status['advice']}</div>
    </div>
    <div style="font-size:13px;font-weight:600;margin-bottom:10px">Fenêtres de trading (UTC)</div>
    {"".join(f'<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 10px;background:#1f2937;border-radius:7px;margin-bottom:5px"><div><span style="font-size:13px;font-weight:600">{name}</span><span style="font-size:11px;color:#64748b;margin-left:8px">{hours}</span></div><div><span style="font-size:11px;color:#94a3b8">{pairs}</span></div></div>'
      for name,hours,pairs in [
        ("Tokyo",   "00:00 – 09:00 UTC", "AUD/JPY · USD/JPY · NZD/USD"),
        ("Londres", "07:00 – 16:00 UTC", "EUR/USD · GBP/USD · EUR/GBP · EUR/CHF"),
        ("🔥 Overlap","12:00 – 16:00 UTC","Volume max — toutes paires G10"),
        ("New York","12:00 – 21:00 UTC", "USD/CAD · USD/CHF · USD/JPY"),
      ])}
    <div style="margin-top:14px;background:#1f2937;border-radius:8px;padding:10px;font-size:11px;color:#94a3b8;line-height:1.7">
      <strong style="color:#e2e8f0">Règles sessions :</strong><br>
      🔥 Entrer uniquement pendant Overlap (12h-16h UTC) ou Londres (08h-12h UTC)<br>
      ⚠️ Lundi matin : attendre 1h après l'ouverture Londres avant d'entrer<br>
      ⛔ Vendredi après 17h UTC : fermer ou trailing stop serré — pas de nouvelles positions
    </div>
  </div>

  <!-- Corrélations -->
  <div id="ef-corr" class="ef-tc">
    <div style="font-size:13px;color:#94a3b8;margin-bottom:14px;line-height:1.6">
      Corrélations sur 60 jours glissants. Une <span style="color:#ef4444">divergence</span> (Δ > 0.30)
      signale une anomalie de marché — souvent un signal contrarian fort ou une alerte de risque.
    </div>
    {corr_html}
    {f'<div style="background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);border-radius:8px;padding:12px;margin-top:10px"><div style="font-size:13px;font-weight:600;color:#fca5a5;margin-bottom:6px">⚡ {len(divergences)} Divergence(s) active(s)</div>{"".join(f'<div style="font-size:12px;color:#94a3b8;margin-bottom:3px">• {d["label"]} : corrélation actuelle {d["corr"]} vs attendu {d["expected"]}</div>' for d in divergences)}</div>' if divergences else ''}
  </div>
</div>

<script>
function efTab(name, el) {{
  document.querySelectorAll(".ef-tc").forEach(t=>t.classList.remove("act"));
  document.querySelectorAll(".ef-tab").forEach(t=>t.classList.remove("act"));
  document.getElementById("ef-"+name).classList.add("act");
  el.classList.add("act");
}}
</script>
"""

FRAGMENTS["edge"] = html_edge

# Résumé console
print(f"\n{'='*55}")
print(f"  EDGE FILTER PRO — {now_str}")
print(f"  Session  : {session_status['quality']}")
print(f"  News     : {nf_txt}")
print(f"  Jour     : {DOW_NAMES.get(cur_dow,'?')} {'✅' if is_good_day else '⚠️'}")
print(f"  Mois     : {MONTH_NAMES[cur_month]} — {'✅ OK' if cur_month not in [7,8] else '⚠️ Volume réduit'}")
if divergences:
    print(f"  ⚡ Divergences : {', '.join(d['label'] for d in divergences)}")
print(f"{'='*55}")
print(f"  Règle : score >= 4/6 avant d'entrer en position")

# ═══════ VUE D'ENSEMBLE (logique C13 inchangée) ═══════
# Cette cellule utilise la liste `signals` déjà calculée en Cellule 7.
# Lance d'abord les cellules 6 et 7 avant celle-ci.

from datetime import datetime
import numpy as np

# ─────────────────────────────────────────────────────────────
# 1. MATRICE DE FORCE DES DEVISES
#    Décompose chaque paire en force de devise individuelle.
#    Logique : une paire = ratio de 2 forces. On agrège.
# ─────────────────────────────────────────────────────────────

def compute_currency_strength(signals):
    """
    Pour chaque devise, agrège sa force à travers toutes les paires.
    Si EUR/USD a un score BUY élevé → EUR fort, USD faible.
    Score paire > 50 = base forte ; < 50 = quote forte.
    """
    strength = {}   # {devise: [liste de contributions]}
    for s in signals:
        pair = s["pair"]
        meta = FX_PAIRS.get(pair, {})
        base, quote = meta.get("currencies", (None, None))
        if not base or not quote:
            continue
        # score > 50 favorise la base, < 50 favorise la quote
        score = s["score"]
        base_contrib  = score - 50      # +25 si score 75 (base forte)
        quote_contrib = 50 - score      # -25 si score 75 (quote faible)
        strength.setdefault(base,  []).append(base_contrib)
        strength.setdefault(quote, []).append(quote_contrib)

    # Moyenne par devise, normalisée sur [-100, +100]
    result = {}
    for ccy, contribs in strength.items():
        avg = np.mean(contribs) if contribs else 0
        result[ccy] = round(avg * 2, 1)   # *2 pour étaler l'échelle
    return dict(sorted(result.items(), key=lambda x: x[1], reverse=True))

currency_strength = compute_currency_strength(signals)

# ─────────────────────────────────────────────────────────────
# 2. GARDE-FOU QUALITÉ : combien de setups VRAIMENT bons
# ─────────────────────────────────────────────────────────────

def quality_assessment(signals):
    """
    Classe les signaux par niveau de qualité réel.
    Institutionnel = score extrême + EMA aligné + pas de RSI extrême + H4 confirme.
    """
    institutional, decent, weak, noise = [], [], [], []
    for s in signals:
        if s["direction"] == "NEUTRAL":
            noise.append(s); continue
        # Critères de qualité
        score_ok = s["score"] >= 70 or s["score"] <= 30
        ema_ok   = (s["direction"]=="BUY" and s["ema_trend"]=="BULLISH") or \
                   (s["direction"]=="SELL" and s["ema_trend"]=="BEARISH")
        rsi_ok   = 25 < s["rsi"] < 75
        h4_ok    = (s["direction"]=="BUY" and s["h4_dir"]=="BULLISH") or \
                   (s["direction"]=="SELL" and s["h4_dir"]=="BEARISH")
        not_blocked = not s.get("em_blocked", False)
        quality = sum([score_ok, ema_ok, rsi_ok, h4_ok, not_blocked])
        if quality >= 5:   institutional.append(s)
        elif quality == 4: decent.append(s)
        elif quality == 3: weak.append(s)
        else:              noise.append(s)
    return institutional, decent, weak, noise

institutional, decent, weak, noise = quality_assessment(signals)

# ─────────────────────────────────────────────────────────────
# 3. GARDE-FOU CORRÉLATION : détecter les trades redondants
# ─────────────────────────────────────────────────────────────

def correlation_warning(signals):
    """
    Détecte si plusieurs signaux actifs sont en réalité le même pari.
    Ex : EUR/USD SELL + GBP/USD SELL + AUD/USD SELL = 1 seul pari USD long.
    """
    usd_long  = []   # paires où on est implicitement long USD
    usd_short = []
    jpy_long  = []
    jpy_short = []
    for s in signals:
        if s["direction"] == "NEUTRAL": continue
        meta = FX_PAIRS.get(s["pair"], {})
        base, quote = meta.get("currencies",(None,None))
        d = s["direction"]
        # Long USD si : SELL une paire XXX/USD, ou BUY une paire USD/XXX
        if quote=="USD" and d=="SELL": usd_long.append(s["label"])
        if base=="USD"  and d=="BUY":  usd_long.append(s["label"])
        if quote=="USD" and d=="BUY":  usd_short.append(s["label"])
        if base=="USD"  and d=="SELL": usd_short.append(s["label"])
        if quote=="JPY" and d=="SELL": jpy_long.append(s["label"])
        if base=="JPY"  and d=="BUY":  jpy_long.append(s["label"])
        if quote=="JPY" and d=="BUY":  jpy_short.append(s["label"])
        if base=="JPY"  and d=="SELL": jpy_short.append(s["label"])

    warnings = []
    for label, group in [("Long USD",usd_long),("Short USD",usd_short),
                          ("Long JPY",jpy_long),("Short JPY",jpy_short)]:
        if len(group) >= 3:
            warnings.append({"theme":label,"pairs":group,"level":"fort"})
        elif len(group) == 2:
            warnings.append({"theme":label,"pairs":group,"level":"modéré"})
    return warnings

corr_warnings = correlation_warning(signals)

# ─────────────────────────────────────────────────────────────
# 4. RANKING COMPLET (toutes les paires, rien ne disparaît)
# ─────────────────────────────────────────────────────────────
ranked = sorted(signals, key=lambda x: x["score"], reverse=True)

# ─────────────────────────────────────────────────────────────
# 5. HTML
# ─────────────────────────────────────────────────────────────
now = datetime.now().strftime("%d/%m/%Y %H:%M")

# --- Currency strength bars ---
cs_html = ""
max_abs = max((abs(v) for v in currency_strength.values()), default=1)
for ccy, val in currency_strength.items():
    pct = abs(val)/max(max_abs,1)*100
    col = "#22c55e" if val > 10 else ("#ef4444" if val < -10 else "#94a3b8")
    bar_dir = "right" if val >= 0 else "left"
    side = "left:50%" if val>=0 else f"right:50%"
    cs_html += f'''<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="width:46px;font-family:monospace;font-size:13px;font-weight:600;color:{col}">{ccy}</span>
        <div style="flex:1;height:22px;background:#1f2937;border-radius:5px;position:relative">
          <div style="position:absolute;top:0;width:1px;height:100%;background:#374151;left:50%"></div>
          <div style="position:absolute;top:2px;height:18px;{side};width:{pct/2}%;background:{col};border-radius:3px"></div>
        </div>
        <span style="width:48px;text-align:right;font-family:monospace;font-size:12px;color:{col}">{val:+.0f}</span>
      </div>'''

strongest = list(currency_strength.keys())[0] if currency_strength else "?"
weakest   = list(currency_strength.keys())[-1] if currency_strength else "?"
best_pair_hint = f"{strongest}/{weakest}" if strongest != weakest else "?"

# --- Heatmap paires × facteurs ---
def cell_color(score):
    if score >= 70:   return "#0f6e56","#86efac"
    if score >= 60:   return "#1d9e75","#ffffff"
    if score >= 55:   return "#2a4a42","#9fe1cb"
    if score >= 45:   return "#1f2937","#94a3b8"
    if score >= 40:   return "#4a2a2a","#f0a0a0"
    if score >= 30:   return "#a32d2d","#ffffff"
    return "#791f1f","#fca5a5"

heatmap_rows = ""
for s in ranked:
    factors = [
        ("Score", s["score"]),
        ("Carry", s["s_carry"]),
        ("Mom.",  s["s_mom"]),
        ("PPP",   s["s_ppp"]),
        ("DXY",   s["s_dxy"]),
    ]
    cells = ""
    for fname, fval in factors:
        bg, fg = cell_color(fval)
        cells += f'<td style="background:{bg};color:{fg};text-align:center;font-family:monospace;font-size:11px;padding:5px 6px;border-radius:3px">{fval:.0f}</td>'
    # RSI et EMA en colonnes info
    rsi_c = "#fca5a5" if s["rsi"]>70 or s["rsi"]<30 else "#94a3b8"
    ema_icon = "↑" if s["ema_trend"]=="BULLISH" else ("↓" if s["ema_trend"]=="BEARISH" else "~")
    ema_c = "#86efac" if s["ema_trend"]=="BULLISH" else ("#fca5a5" if s["ema_trend"]=="BEARISH" else "#64748b")
    dir_badge = ""
    if s["direction"]=="BUY":  dir_badge = '<span style="color:#22c55e;font-weight:700">BUY</span>'
    elif s["direction"]=="SELL": dir_badge = '<span style="color:#ef4444;font-weight:700">SELL</span>'
    else: dir_badge = '<span style="color:#64748b">—</span>'
    em_tag = ' <span style="font-size:8px;color:#f59e0b">EM</span>' if s["em"] else ""

    heatmap_rows += f'''<tr>
        <td style="font-family:monospace;font-size:12px;font-weight:600;color:#e2e8f0;padding:5px 8px">{s["label"]}{em_tag}</td>
        <td style="text-align:center;padding:5px 6px">{dir_badge}</td>
        {cells}
        <td style="text-align:center;color:{rsi_c};font-family:monospace;font-size:11px;padding:5px 6px">{s["rsi"]:.0f}</td>
        <td style="text-align:center;color:{ema_c};font-size:13px;padding:5px 6px">{ema_icon}</td>
      </tr>'''

# --- Quality assessment ---
def quality_list(lst):
    if not lst: return '<span style="color:#64748b;font-size:12px">aucune</span>'
    return " · ".join(f'<span style="font-family:monospace">{s["label"]}'
                      f'<span style="color:{"#22c55e" if s["direction"]=="BUY" else "#ef4444"};font-size:10px"> {s["direction"]}</span></span>'
                      for s in lst)

# --- Correlation warnings ---
corr_html = ""
if corr_warnings:
    for w in corr_warnings:
        col = "#ef4444" if w["level"]=="fort" else "#f59e0b"
        corr_html += f'''<div style="background:rgba(239,68,68,.08);border-left:3px solid {col};border-radius:0 7px 7px 0;padding:8px 12px;margin-bottom:6px">
            <div style="font-size:12px;color:#e2e8f0;margin-bottom:3px"><strong style="color:{col}">⚠️ {w["theme"]}</strong> — {len(w["pairs"])} positions = 1 seul pari</div>
            <div style="font-size:11px;color:#94a3b8">{", ".join(w["pairs"])}</div>
            <div style="font-size:10px;color:#64748b;margin-top:3px;font-style:italic">Si tu prends ces {len(w["pairs"])} trades, tu ne diversifies pas — tu concentres ton risque sur {w["theme"].split()[1]}.</div>
          </div>'''
else:
    corr_html = '<div style="color:#86efac;font-size:12px;padding:8px">✅ Aucune concentration de risque détectée parmi les signaux actifs.</div>'

html_overview = f'''
<style>
  @import url(\'https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap\');
  .ov-wrap {{ font-family:\'Space Grotesk\',sans-serif; background:#0a0e1a; color:#e2e8f0; border-radius:14px; overflow:hidden; }}
  .ov-tab {{ padding:9px 16px;font-size:13px;font-weight:500;cursor:pointer;border-bottom:2px solid transparent;color:#64748b;display:inline-block; }}
  .ov-tab.act {{ color:#e2e8f0; border-bottom-color:#06b6d4; }}
  .ov-tc {{ display:none; padding:16px; }}
  .ov-tc.act {{ display:block; }}
  .ov-wrap table {{ width:100%; border-collapse:collapse; }}
  .ov-wrap th {{ background:#1f2937;padding:6px;text-align:center;font-size:9px;text-transform:uppercase;color:#64748b;letter-spacing:.03em; }}
  .ov-wrap th:first-child {{ text-align:left; padding-left:8px; }}
''' + '''
</style>

<div class="ov-wrap">
  <div style="background:#111827;border-bottom:1px solid #1e293b;padding:14px 18px;display:flex;justify-content:space-between;align-items:center">
    <div>
      <span style="font-size:17px;font-weight:700">Vue <span style="color:#06b6d4">d\'ensemble</span></span>
      <span style="font-size:12px;color:#64748b;margin-left:10px">24 paires · pensée portefeuille</span>
    </div>
    <div style="font-size:11px;color:#64748b;font-family:monospace">''' + now + '''</div>
  </div>

  <!-- Bandeau qualité (garde-fou) -->
  <div style="background:linear-gradient(135deg,#111827,#1f2937);padding:14px 18px;border-bottom:1px solid #1e293b;display:flex;gap:20px;align-items:center;flex-wrap:wrap">
    <div style="text-align:center">
      <div style="font-size:26px;font-weight:700;font-family:monospace;color:#22c55e">''' + str(len(institutional)) + '''</div>
      <div style="font-size:10px;color:#64748b;text-transform:uppercase">Qualité haute</div>
    </div>
    <div style="text-align:center">
      <div style="font-size:26px;font-weight:700;font-family:monospace;color:#f59e0b">''' + str(len(decent)) + '''</div>
      <div style="font-size:10px;color:#64748b;text-transform:uppercase">Corrects</div>
    </div>
    <div style="text-align:center">
      <div style="font-size:26px;font-weight:700;font-family:monospace;color:#64748b">''' + str(len(weak)+len(noise)) + '''</div>
      <div style="font-size:10px;color:#64748b;text-transform:uppercase">À ignorer</div>
    </div>
    <div style="flex:1;min-width:200px;background:rgba(6,182,212,.08);border-radius:8px;padding:10px 14px">
      <div style="font-size:12px;color:#e2e8f0;line-height:1.5">
        <strong style="color:#06b6d4">Rappel pro :</strong> regarder les 24 paires sert à mieux <strong>sélectionner</strong>, pas à trader plus. Les meilleurs font 5 trades par mois, pas 50.
      </div>
    </div>
  </div>

  <!-- Tabs -->
  <div style="background:#111827;border-bottom:1px solid #1e293b;padding:0 18px">
    <span class="ov-tab act" onclick="ovTab(\'strength\',this)">💪 Force des devises</span>
    <span class="ov-tab" onclick="ovTab(\'heatmap\',this)">🔥 Heatmap facteurs</span>
    <span class="ov-tab" onclick="ovTab(\'quality\',this)">🎯 Qualité des setups</span>
    <span class="ov-tab" onclick="ovTab(\'risk\',this)">⚠️ Risque corrélation</span>
  </div>

  <!-- Force des devises -->
  <div id="ov-strength" class="ov-tc act">
    <div style="font-size:13px;color:#94a3b8;margin-bottom:14px;line-height:1.6">
      Chaque paire est décomposée en force de devise individuelle. Une devise verte est recherchée par le marché, une rouge est délaissée. <strong style="color:#e2e8f0">La meilleure paire théorique = devise la plus forte contre la plus faible.</strong>
    </div>
    ''' + cs_html + '''
    <div style="margin-top:14px;background:#1f2937;border-radius:8px;padding:12px;font-size:13px;color:#e2e8f0">
      💡 Paire la plus déséquilibrée actuellement : <strong style="color:#06b6d4;font-family:monospace">''' + best_pair_hint + '''</strong>
      <span style="color:#64748b;font-size:11px">(''' + strongest + ''' le plus fort vs ''' + weakest + ''' le plus faible)</span>
    </div>
  </div>

  <!-- Heatmap -->
  <div id="ov-heatmap" class="ov-tc">
    <div style="font-size:13px;color:#94a3b8;margin-bottom:12px;line-height:1.6">
      Toutes les paires classées par score. Vert = signal d\'achat, rouge = vente. Chaque colonne est un facteur. <strong style="color:#e2e8f0">Cherche les lignes où tous les facteurs sont de la même couleur</strong> — c\'est là que la conviction est réelle.
    </div>
    <div style="overflow-x:auto">
      <table>
        <thead><tr>
          <th>Paire</th><th>Dir</th><th>Score</th><th>Carry</th><th>Mom.</th><th>PPP</th><th>DXY</th><th>RSI</th><th>EMA</th>
        </tr></thead>
        <tbody>''' + heatmap_rows + '''</tbody>
      </table>
    </div>
    <div style="margin-top:10px;font-size:10px;color:#64748b">
      Échelle : vert foncé ≥70 (fort BUY) · gris ~50 (neutre) · rouge ≥70 SELL. RSI rouge = zone extrême. EMA ↑ haussier ↓ baissier.
    </div>
  </div>

  <!-- Qualité -->
  <div id="ov-quality" class="ov-tc">
    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#22c55e;margin-bottom:6px">🎯 Qualité institutionnelle (''' + str(len(institutional)) + ''')</div>
      <div style="font-size:12px;color:#94a3b8;line-height:1.7;background:#1f2937;border-radius:7px;padding:10px">''' + quality_list(institutional) + '''</div>
      <div style="font-size:10px;color:#64748b;margin-top:4px;font-style:italic">Score extrême + EMA aligné + RSI sain + H4 confirme. Ce sont tes seuls vrais candidats.</div>
    </div>
    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#f59e0b;margin-bottom:6px">Corrects mais imparfaits (''' + str(len(decent)) + ''')</div>
      <div style="font-size:12px;color:#94a3b8;line-height:1.7;background:#1f2937;border-radius:7px;padding:10px">''' + quality_list(decent) + '''</div>
      <div style="font-size:10px;color:#64748b;margin-top:4px;font-style:italic">Un critère manque. À surveiller, pas à exécuter aveuglément.</div>
    </div>
    <div>
      <div style="font-size:13px;font-weight:600;color:#64748b;margin-bottom:6px">Faibles / à ignorer (''' + str(len(weak)+len(noise)) + ''')</div>
      <div style="font-size:11px;color:#64748b;line-height:1.6">''' + quality_list(weak) + '''</div>
    </div>
  </div>

  <!-- Risque corrélation -->
  <div id="ov-risk" class="ov-tc">
    <div style="font-size:13px;color:#94a3b8;margin-bottom:14px;line-height:1.6">
      Plusieurs paires peuvent cacher <strong style="color:#e2e8f0">un seul et même pari</strong>. Vendre EUR/USD, GBP/USD et AUD/USD en même temps, ce n\'est pas 3 trades diversifiés — c\'est 3× le même pari "USD fort". Si l\'USD reverse, tu perds sur les 3.
    </div>
    ''' + corr_html + '''
  </div>
</div>

<script>
function ovTab(name, el) {
  document.querySelectorAll(".ov-tc").forEach(t=>t.classList.remove("act"));
  document.querySelectorAll(".ov-tab").forEach(t=>t.classList.remove("act"));
  document.getElementById("ov-"+name).classList.add("act");
  el.classList.add("act");
}
</script>
'''

FRAGMENTS["overview"] = html_overview

# Résumé console
print("="*55)
print("  VUE D\'ENSEMBLE")
print(f"  Devise la plus forte : {strongest} ({currency_strength.get(strongest,0):+.0f})")
print(f"  Devise la plus faible: {weakest} ({currency_strength.get(weakest,0):+.0f})")
print(f"  Paire la plus déséquilibrée : {best_pair_hint}")
print(f"  Setups qualité haute : {len(institutional)}")
print(f"  À ignorer            : {len(weak)+len(noise)}")
if corr_warnings:
    print(f"  ⚠️ {len(corr_warnings)} concentration(s) de risque détectée(s)")
print("="*55)

# ═══════════════ TOP 3 DU JOUR (cross-asset) ═══════════════

def _mat_rank(s):
    m = s.get("maturity", "—")
    if m.startswith("🟢"): return 0
    if m.startswith("🟡"): return 1
    if m.startswith("🔴"): return 2
    return 3

all_active = ([s for s in signals if s["direction"] != "NEUTRAL"]
              + [s for s in indices_signals if s["direction"] != "NEUTRAL"]
              + [s for s in comm_signals if s["direction"] != "NEUTRAL"])
all_active.sort(key=lambda s: (_mat_rank(s), -s["conviction"]))
top3 = all_active[:3]
n_green = sum(1 for s in all_active if _mat_rank(s) == 0)

def _top_card(s, rank, meta=None):
    col = "#22c55e" if s["direction"] == "BUY" else "#ef4444"
    icon = "↑" if s["direction"] == "BUY" else "↓"
    label = s.get("label", s.get("pair", "?"))
    price_fmt = f"{s['price']:.5f}" if s.get("asset_class") == "Forex" else f"{s['price']}"
    return f"""
    <div style="background:linear-gradient(135deg,#111827,#1a2332);border:1px solid {col}44;border-radius:14px;padding:18px;position:relative">
      <div style="position:absolute;top:-10px;left:14px;background:{col};color:#fff;font-size:11px;font-weight:700;padding:2px 10px;border-radius:10px">#{rank}</div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;margin-top:4px">
        <div>
          <span style="font-size:18px;font-weight:700;font-family:monospace;color:#e2e8f0">{label}</span>
          <span style="font-size:10px;color:#64748b;background:#1f2937;padding:1px 7px;border-radius:4px;margin-left:6px">{s.get('asset_class','')}</span>
        </div>
        <span style="background:{col};color:#fff;font-size:13px;font-weight:700;padding:4px 12px;border-radius:7px">{icon} {s['direction']}</span>
      </div>
      <div style="display:flex;gap:14px;font-size:12px;color:#94a3b8;margin-bottom:8px;flex-wrap:wrap">
        <span>Conviction <strong style="color:{col};font-family:monospace">{s['conviction']:.0f}%</strong></span>
        <span>Prix <span style="font-family:monospace;color:#e2e8f0">{price_fmt}</span></span>
        <span style="color:{s.get('maturity_color','#64748b')};font-weight:600">{s.get('maturity','—')}</span>
      </div>
      <div style="font-size:11px;color:#94a3b8;line-height:1.6">{s.get('maturity_note','')}</div>
      {_dup_line(meta)}
      {_checklist_html(s, meta or {{}})}
      <div style="font-size:11px;color:#64748b;margin-top:8px">→ Carte complète dans la section {s.get('asset_class','')} · le chart a le dernier mot.</div>
    </div>"""

def _dup_line(meta):
    if not meta or not meta.get("dup_of"): return ""
    return (f'<div style="font-size:11px;color:#fcd34d;background:rgba(245,158,11,.07);border-radius:7px;'
            f'padding:6px 10px;margin-top:8px">⚠️ Même thème que le #{meta["dup_of"]} ({meta.get("label","")}) — '
            f'un seul trade par thème : si tu prends celui-là, pas l’autre.</div>')

# ── V5 : bandeau compact des mouvements frais (chocs macro) ──
_fresh_assets = [s for s in signals + indices_signals + comm_signals if s.get("fresh_flag")]
_fresh_banner = ""
if _fresh_assets:
    _chips = " ".join(
        f'<span style="font-size:11px;background:#1f2937;border:1px solid rgba(249,115,22,.4);border-radius:20px;'
        f'padding:3px 10px;font-family:monospace;color:#fdba74">{s.get("label", s.get("pair","?"))} '
        f'{s.get("fresh_data",{}).get("m1_atr",0):+.1f}ATR</span>'
        for s in _fresh_assets)
    _fresh_banner = f"""
<div style="background:rgba(249,115,22,.06);border:1px solid rgba(249,115,22,.25);border-radius:10px;padding:10px 14px;margin-bottom:14px">
  <div style="font-size:12px;color:#fdba74;margin-bottom:6px">🔥 <strong>Impulsions anormales détectées</strong>
  <span style="color:#94a3b8">— chocs macro probables. Ne chasse pas : le bon trade est le retracement.</span></div>
  <div style="display:flex;gap:6px;flex-wrap:wrap">{_chips}</div>
</div>"""



# ═══════════════ V6 : LECTURE PRO AUTOMATISÉE (paquet A) ═══════════════

def trade_theme(s):
    """Thème de risque réel d'un setup — pour croisement régime et déduplication."""
    d = s.get("direction")
    if d == "NEUTRAL": return None, None
    ac = s.get("asset_class", "")
    if ac == "Forex":
        base, quote = FX_PAIRS.get(s.get("pair", ""), {}).get("currencies", (None, None))
        if quote == "JPY":
            return ("risk-on", f"short JPY (carry)") if d == "BUY" else ("risk-off", "long JPY (refuge)")
        if base == "USD" or quote == "USD":
            usd_long = (base == "USD" and d == "BUY") or (quote == "USD" and d == "SELL")
            return ("long USD", "long USD") if usd_long else ("short USD", "short USD")
        return None, None
    if ac == "Indices":
        return ("risk-on", "long indices") if d == "BUY" else ("risk-off", "short indices")
    if s.get("pair") in ("GOLD", "SILVER"):
        return ("risk-off", "long refuge") if d == "BUY" else ("risk-on", "refuge vendu")
    return None, None

def regime_vs_theme(theme):
    """Le setup rame-t-il contre le régime VIX ? (régime calculé section indices : vix_regime)"""
    try: reg = vix_regime  # "RISK-OFF" / "RISK-ON" / "NEUTRE" selon la cellule indices
    except NameError: return None
    if theme == "risk-on" and "OFF" in str(reg): return "contre"
    if theme == "risk-off" and "ON" in str(reg): return "contre"
    if theme in ("risk-on", "risk-off"): return "aligné"
    return None

# ── A1 + A2 : analyse du Top 3 (régime + doublons + alternative) ──
_top3_meta = []
_seen_themes = {}
for _i, _s in enumerate(top3):
    _th, _lbl = trade_theme(_s)
    _dup_of = _seen_themes.get(_th) if _th else None
    if _th and _th not in _seen_themes: _seen_themes[_th] = _i + 1
    _top3_meta.append({"theme": _th, "label": _lbl, "vs_regime": regime_vs_theme(_th), "dup_of": _dup_of})

_warn_a1 = ""
_n_contre = sum(1 for m in _top3_meta if m["vs_regime"] == "contre")
if _n_contre:
    try: _reg_txt = vix_regime
    except NameError: _reg_txt = "?"
    _warn_a1 = (f'<div style="background:rgba(239,68,68,.07);border-left:3px solid #ef4444;border-radius:0 10px 10px 0;'
                f'padding:11px 14px;margin-bottom:14px;font-size:12px;color:#fca5a5;line-height:1.7">'
                f'⚠️ <strong>{_n_contre} setup(s) du Top 3 rame(nt) contre le régime actuel ({_reg_txt})</strong>. '
                f'Le score (carry/momentum) est un signal LENT ; le régime VIX est un signal RAPIDE — quand ils divergent, '
                f'c\'est dans ces configurations que les trades encombrés se font massacrer. Réduis, conditionne, ou passe.</div>')

_alt_html = ""
_top3_themes = {m["theme"] for m in _top3_meta if m["theme"]}
_alt = next((s for s in all_active[3:] if trade_theme(s)[0] not in _top3_themes and trade_theme(s)[0] is not None), None)
if _alt and any(m["dup_of"] for m in _top3_meta):
    _alt_html = (f'<div style="font-size:11px;color:#94a3b8;margin-top:10px">💡 Alternative décorrélée du Top 3 : '
                 f'<strong style="color:#e2e8f0;font-family:monospace">{_alt.get("label","?")} {_alt["direction"]}</strong> '
                 f'(conviction {_alt["conviction"]:.0f}, {_alt.get("maturity","—")}) — thème {trade_theme(_alt)[1]} '
                 f'→ carte complète dans sa section.</div>')

# ── A3 + A4 : checklist pré-trade + reco d'exécution par setup du Top 3 ──
def _checklist_html(s, meta):
    if s.get("direction") == "NEUTRAL": return ""
    items = []
    vs = meta.get("vs_regime")
    items.append(("✅" if vs != "contre" else "❌", f"Régime compatible ({meta.get('label') or 'thème neutre'})"))
    items.append(("✅" if not meta.get("dup_of") else "❌",
                  "Pas de doublon thématique" if not meta.get("dup_of") else f"Même pari que le #{meta['dup_of']} — n'en prendre qu'un"))
    items.append(("✅" if s.get("rr1", 0) >= 1.3 else "⚠️", f"RR TP1 = {s.get('rr1','?')} (seuil 1.3)"))
    items.append(("✅" if str(s.get("maturity","")).startswith("🟢") else "⚠️", f"Verdict {s.get('maturity','—')}"))
    cot_ext = ""
    if s.get("asset_class") == "Forex":
        cur = FX_PAIRS.get(s.get("pair",""), {}).get("currencies", ())
        for c in cur:
            d = COT_DATA.get(c)
            if d and d.get("extreme"): cot_ext = f"{c} extrême {d['extreme'].lower()} ({d['index']}/100)"
    elif COT_DATA.get(s.get("pair")):
        d = COT_DATA[s["pair"]]
        if d.get("extreme"): cot_ext = f"extrême {d['extreme'].lower()} ({d['index']}/100)"
    items.append(("⚠️" if cot_ext else "✅", f"Positionnement COT : {cot_ext or 'pas d’extrême'}"))
    items.append(("👁️", "News de la semaine sur l'actif — à vérifier (ForexFactory)"))
    items.append(("👁️", "Structure sur le chart (dernier creux/sommet significatif) — ton dernier mot"))
    # A4 : reco exécution
    el = s.get("entry_label", "?")
    if el == "Pullback":
        execu = "⚡ Prix déjà en zone fraîche → <strong>entrée directe OK</strong> si les 👁️ valident."
    else:
        e20 = s.get("ema20", "")
        execu = (f"🎯 Prix a couru ({el}) → <strong>ordre limite vers {e20}</strong> (zone EMA20/demande) — "
                 f"laisse le marché venir à toi ; pas servi = pas de trade, rien perdu.")
    rows = "".join(f'<div style="display:flex;gap:8px;font-size:11px;color:#cbd5e1;line-height:1.7">'
                   f'<span style="width:18px">{ic}</span><span>{txt}</span></div>' for ic, txt in items)
    return (f'<div style="background:#0a0e1a;border:1px solid #1e293b;border-radius:10px;padding:11px 13px;margin-top:10px">'
            f'<div style="font-size:9px;color:#64748b;text-transform:uppercase;margin-bottom:6px">✈️ Checklist pré-trade</div>'
            f'{rows}<div style="font-size:11px;color:#93c5fd;margin-top:7px;line-height:1.6">{execu}</div></div>')

# ── A5 : mode préparation weekend ──
_weekend_html = ""
if datetime.now().weekday() >= 5:
    _weekend_html = ('<div style="background:rgba(139,92,246,.08);border:1px solid rgba(139,92,246,.3);border-radius:10px;'
                     'padding:11px 14px;margin-bottom:14px;font-size:12px;color:#c4b5fd;line-height:1.7">'
                     '🛋️ <strong>Mode préparation (marché fermé)</strong> — pas d\'exécution aujourd\'hui : '
                     'note tes niveaux, pose tes alertes de prix, vérifie le calendrier de la semaine (FOMC/BCE/BoJ/CPI ?), '
                     'et relance le script lundi après quelques heures de cotation pour confirmer que les verdicts tiennent.</div>')

# ── B1 : scan impulsions visible même quand RAS ──
_scan_html = ""
if not _fresh_assets:
    _n_tot_scan = len(signals) + len(indices_signals) + len(comm_signals)
    _scan_html = (f'<div style="font-size:11px;color:#64748b;margin-bottom:14px">'
                  f'🔥 Scan impulsions : RAS — {_n_tot_scan}/{_n_tot_scan} actifs calmes '
                  f'(aucun mouvement &gt;1.5 ATR/1j ni &gt;2.5 ATR/3j). Le détecteur veille ; il n\'apparaît que les jours de choc.</div>')

# ═══════════════ V6 : PAGE TAUX DIRECTEURS (🏦) ═══════════════

def _sparkline_svg(pts, w=130, h=30):
    if not pts or len(pts) < 5: return '<span style="color:#475569;font-size:9px">historique indisponible</span>'
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    step = max(1, len(vals) // 60)
    sampled = vals[::step][-60:]
    n = len(sampled)
    xs = [i * (w - 4) / max(1, n - 1) + 2 for i in range(n)]
    ys = [h - 3 - (v - lo) / rng * (h - 6) for v in sampled]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    col = "#fca5a5" if sampled[-1] > sampled[0] else ("#86efac" if sampled[-1] < sampled[0] else "#94a3b8")
    return (f'<svg width="{w}" height="{h}" style="display:block">'
            f'<polyline points="{path}" fill="none" stroke="{col}" stroke-width="1.5"/></svg>')

def build_rates_fragment():
    rows = ""
    order = sorted(CURRENT_RATES.keys(), key=lambda c: -CURRENT_RATES[c])
    for ccy in order:
        rate = CURRENT_RATES[ccy]
        cyc, cyc_col = rate_cycle(ccy)
        spark = _sparkline_svg(RATES_HISTORY.get(ccy, []))
        src = "BIS" if ccy in RATES_HISTORY and RATES_HISTORY[ccy] else ("manuel (SORA approx.)" if ccy == "SGD" else "table locale")
        rows += (f'<div style="display:grid;grid-template-columns:70px 90px 110px 150px 1fr;gap:12px;align-items:center;'
                 f'padding:8px 4px;border-bottom:1px solid #1e293b">'
                 f'<span style="font-family:monospace;font-size:14px;font-weight:600;color:#e2e8f0">{ccy}</span>'
                 f'<span style="font-family:monospace;font-size:16px;color:#e2e8f0">{rate:.2f}%</span>'
                 f'<span style="font-size:11px;color:{cyc_col};font-weight:600">{cyc}</span>'
                 f'<span>{spark}</span>'
                 f'<span style="font-size:10px;color:#64748b">{src}</span></div>')
    return (f'<div style="font-size:12px;color:#94a3b8;margin-bottom:12px;line-height:1.7">'
            f'Le carry statique est une photo ; la <strong style="color:#e2e8f0">trajectoire</strong> est le film. '
            f'Une banque qui coupe pendant que l\'autre monte = un carry qui se vide de trimestre en trimestre — '
            f'exactement ce que le score seul ne montre pas. Sparklines : 2 ans d\'historique (source BIS).</div>'
            f'<div style="background:#111827;border:1px solid #1e293b;border-radius:12px;padding:8px 14px">'
            f'<div style="display:grid;grid-template-columns:70px 90px 110px 150px 1fr;gap:12px;font-size:9px;color:#64748b;'
            f'text-transform:uppercase;padding:6px 4px;border-bottom:1px solid #1e293b">'
            f'<span>Devise</span><span>Taux</span><span>Cycle (~3-6 mois)</span><span>Historique 2 ans</span><span>Source</span></div>'
            f'{rows}</div>'
            f'<div style="font-size:10px;color:#64748b;margin-top:10px">Source : {RATES_META["source"]} · '
            f'dernière observation {RATES_META["obs"]} · SGD = approximation SORA (la MAS pilote le change, pas les taux). '
            f'⚠️ La BIS peut avoir quelques jours de latence après une décision — vérifie après un FOMC/BCE/BoJ.</div>')

FRAGMENTS["rates"] = build_rates_fragment()
FRAGMENTS["dxy"] = FRAGMENTS.get("dxy", "") + yield_block_html() + cot_table_html()
print("   ✅ V6 : lecture pro (A1-A5) + scan B1 + page Taux + tableau COT")

_top_cards = "".join(_top_card(s, i + 1, _top3_meta[i] if i < len(_top3_meta) else None) for i, s in enumerate(top3)) if top3 else \
    '<div style="color:#64748b;text-align:center;padding:24px;background:#111827;border-radius:12px">Aucun signal directionnel aujourd\'hui — et c\'est une information en soi. Pas de trade forcé.</div>'

_honesty = ""
if top3 and n_green == 0:
    _honesty = ('<div style="background:rgba(245,158,11,.08);border-left:3px solid #f59e0b;border-radius:0 8px 8px 0;'
                'padding:10px 14px;margin-top:12px;font-size:12px;color:#fcd34d;line-height:1.6">'
                '⚠️ <strong>Aucun setup vert aujourd\'hui.</strong> Les meilleurs signaux du jour ne sont pas mûrs — '
                'biais présent mais timing non aligné. Les regarder, préparer les plans, mais ne pas forcer l\'entrée. '
                'Ne rien faire est une position.</div>')

FRAGMENTS["top3"] = f"""
{_weekend_html}
{_fresh_banner}
{_scan_html}
{_warn_a1}
<div style="font-size:13px;color:#94a3b8;margin-bottom:16px;line-height:1.7">
  Les 3 meilleurs setups du jour, toutes classes confondues ({len(signals)} paires + {len(indices_signals)} indices + {len(comm_signals)} commodities analysés),
  classés par <strong style="color:#e2e8f0">maturité d'abord, conviction ensuite</strong>.
  Le Top 3 oriente — il ne restreint pas : toutes les cartes complètes sont dans leurs sections.
</div>
<div style="display:flex;flex-direction:column;gap:16px">{_top_cards}</div>
{_alt_html}
{_honesty}
<div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:12px;margin-top:16px;font-size:12px;color:#64748b;line-height:1.7">
  📌 Rappel du workflow : ce dashboard trie l'univers → tu ouvres 3-5 charts max sur TradingView →
  ta lecture de structure (HH/HL, dernier creux significatif, clôtures pas mèches) décide → 0-2 trades.
  Les meilleurs font 5 trades par mois, pas 50.
</div>"""

# ═══════════════ RISQUE AGRÉGÉ INTER-CLASSES ═══════════════

usd_long, usd_short, jpy_long, jpy_short, risk_on, risk_off = [], [], [], [], [], []
for s in signals:
    if s["direction"] == "NEUTRAL": continue
    base, quote = FX_PAIRS.get(s["pair"], {}).get("currencies", (None, None))
    d = s["direction"]; lbl = s["label"]
    if quote == "USD" and d == "SELL": usd_long.append(lbl)
    if base == "USD" and d == "BUY":  usd_long.append(lbl)
    if quote == "USD" and d == "BUY":  usd_short.append(lbl)
    if base == "USD" and d == "SELL": usd_short.append(lbl)
    if quote == "JPY" and d == "SELL": jpy_long.append(lbl)
    if quote == "JPY" and d == "BUY":  jpy_short.append(lbl); risk_on.append(lbl + " (carry JPY)")
for s in indices_signals:
    if s["direction"] == "BUY":  risk_on.append(s["label"] + " (indice)")
    if s["direction"] == "SELL": risk_off.append(s["label"] + " (indice)")
for s in comm_signals:
    if s["pair"] in ("GOLD", "SILVER"):
        if s["direction"] == "BUY":  risk_off.append(s["label"] + " (refuge)")
        if s["direction"] == "SELL": risk_on.append(s["label"] + " (refuge vendu)")

_risk_blocks = ""
for theme, group, note in [
    ("Long USD", usd_long, "Ces positions gagnent/perdent ensemble si le dollar bouge."),
    ("Short USD", usd_short, "Même pari dollar faible répété."),
    ("Long JPY", jpy_long, "Pari yen fort répété."),
    ("Risk-ON", risk_on, "Indices longs + carry JPY + refuges vendus = un seul pari sur l'appétit au risque. Si le VIX explose, tout perd en même temps."),
    ("Risk-OFF", risk_off, "Pari peur du marché répété sur plusieurs classes."),
]:
    if len(group) >= 2:
        sev = "#ef4444" if len(group) >= 3 else "#f59e0b"
        _risk_blocks += f"""<div style="background:rgba(239,68,68,.06);border-left:3px solid {sev};border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:8px">
          <div style="font-size:13px;color:#e2e8f0;margin-bottom:3px"><strong style="color:{sev}">⚠️ {theme}</strong> — {len(group)} signaux = 1 seul pari</div>
          <div style="font-size:11px;color:#94a3b8;margin-bottom:3px">{', '.join(group)}</div>
          <div style="font-size:10px;color:#64748b;font-style:italic">{note}</div>
        </div>"""
if not _risk_blocks:
    _risk_blocks = '<div style="color:#86efac;font-size:13px;padding:14px;background:#111827;border-radius:10px">✅ Aucune concentration de risque inter-classes détectée parmi les signaux actifs.</div>'

FRAGMENTS["risk"] = f"""
<div style="font-size:13px;color:#94a3b8;margin-bottom:14px;line-height:1.7">
  Le piège invisible du multi-actifs : être long Nasdaq + long AUD/JPY + short Or, ce n'est pas 3 trades diversifiés —
  c'est <strong style="color:#e2e8f0">3 fois le même pari risk-on</strong>. Cette section agrège tous les signaux actifs par thème de risque réel.
</div>
{_risk_blocks}"""

# ═══════════════ JOURNAL & STATS ═══════════════
try:
    _dfj = load_journal()
    _perf = perf_stats(_dfj)
except Exception:
    _dfj = pd.DataFrame(); _perf = {}

if _perf:
    _dd_c = "#22c55e" if _perf["max_dd"] > -5 else ("#f59e0b" if _perf["max_dd"] > -10 else "#ef4444")
    _stats_html = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:16px">' + "".join(
        f'<div style="background:#111827;border:1px solid #1e293b;border-radius:9px;padding:12px;text-align:center">'
        f'<div style="font-size:20px;font-weight:700;font-family:monospace;color:{c}">{v}</div>'
        f'<div style="font-size:10px;color:#64748b;text-transform:uppercase;margin-top:3px">{lbl}</div></div>'
        for lbl, v, c in [
            ("Win Rate", f"{_perf['win_rate']}%", "#22c55e" if _perf["win_rate"] >= 50 else "#ef4444"),
            ("Profit Factor", str(_perf["profit_factor"]), "#22c55e" if _perf["profit_factor"] >= 1.5 else "#f59e0b"),
            ("Sharpe", str(_perf["sharpe"]), "#22c55e" if _perf["sharpe"] >= 1 else "#f59e0b"),
            ("Max DD", f"{_perf['max_dd']}%", _dd_c),
            (f"P&L ({_perf['wins']}W/{_perf['losses']}L)", f"${_perf['total_pnl']:+,.0f}", "#22c55e" if _perf["total_pnl"] > 0 else "#ef4444"),
            ("Expectancy", f"${_perf['expectancy']}", "#22c55e" if _perf["expectancy"] > 0 else "#ef4444"),
        ]) + '</div>'
else:
    _stats_html = '<div style="color:#64748b;text-align:center;padding:16px;background:#111827;border-radius:10px;margin-bottom:16px">Aucun trade clôturé pour l\'instant — les stats apparaîtront ici.</div>'

_rows = ""
if len(_dfj) > 0:
    for _, row in _dfj.tail(20).iloc[::-1].iterrows():
        res = row.get("Resultat", "")
        c_row = "color:#86efac" if res == "WIN" else ("color:#fca5a5" if res == "LOSS" else "")
        pnl = f"${row.get('PnL_USD','')}" if str(row.get('PnL_USD','')) not in ('', 'nan') else "—"
        _rows += (f'<tr style="{c_row}"><td>{row.get("Date_Signal","")}</td>'
                  f'<td style="font-family:monospace">{row.get("Paire","")}</td>'
                  f'<td>{row.get("Direction","")}</td>'
                  f'<td style="font-family:monospace">{row.get("Prix_Entree","")}</td>'
                  f'<td>{row.get("Score","")}</td>'
                  f'<td>{row.get("Date_Sortie","") or "—"}</td><td>{pnl}</td><td>{res or "—"}</td></tr>')
_table = (f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:11px">'
          f'<thead><tr>' + "".join(f'<th style="background:#1f2937;padding:6px 8px;text-align:left;font-size:10px;text-transform:uppercase;color:#64748b">{h}</th>'
                                    for h in ["Date","Paire","Dir","Entrée","Score","Sortie","P&L","Résultat"])
          + f'</tr></thead><tbody>{_rows or "<tr><td colspan=8 style=padding:14px;text-align:center;color:#64748b>Journal vide</td></tr>"}</tbody></table></div>')

FRAGMENTS["journal"] = (f'<div style="font-size:12px;color:#64748b;margin-bottom:12px">Fichier : {JOURNAL_FILE} — '
                        f'pour enregistrer ou fermer un trade, utilise la Cellule 5.</div>' + _stats_html + _table)
print("📊 [6/6] Synthèse : Top 3 + risque agrégé + journal — OK")


# ═══════════════ ASSEMBLAGE DE LA PAGE UNIQUE ═══════════════

_now = datetime.now()
_date_str = _now.strftime("%d/%m/%Y %H:%M")
_file_date = _now.strftime("%Y-%m-%d")

# Compteurs globaux pour le header
_n_buy  = len([s for s in signals + indices_signals + comm_signals if s["direction"] == "BUY"])
_n_sell = len([s for s in signals + indices_signals + comm_signals if s["direction"] == "SELL"])
_n_tot  = len(signals) + len(indices_signals) + len(comm_signals)
_n_green_global = sum(1 for s in signals + indices_signals + comm_signals
                      if str(s.get("maturity","")).startswith("🟢"))

# Bannière calendrier estimé (honnêteté sur l'Edge Filter)
_edge_banner = ('<div style="background:rgba(245,158,11,.08);border-left:3px solid #f59e0b;border-radius:0 8px 8px 0;'
                'padding:8px 12px;margin-bottom:12px;font-size:11px;color:#fcd34d;line-height:1.6">'
                '📅 Les dates d\'événements (FOMC, CPI, ECB...) sont <strong>estimées par règles récurrentes</strong> — '
                'toujours vérifier sur ForexFactory ou Investing.com avant de trader autour d\'une news.</div>')

SECTIONS = [
    ("top3",     "🏠 Top 3",         FRAGMENTS.get("top3", "")),
    ("dxy",      "💵 Contexte DXY",  FRAGMENTS.get("dxy", "")),
    ("rates",    "🏦 Taux directeurs", FRAGMENTS.get("rates", "")),
    ("forex",    "💱 Forex",         FRAGMENTS.get("forex", "")),
    ("indices",  "📊 Indices",       FRAGMENTS.get("indices", "")),
    ("metals",   "🪙 Métaux & Énergie", FRAGMENTS.get("metals", "")),
    ("edge",     "🎯 Edge Filter",   _edge_banner + FRAGMENTS.get("edge", "")),
    ("overview", "🌐 Vue d'ensemble", FRAGMENTS.get("overview", "")),
    ("risk",     "⚠️ Risque",        FRAGMENTS.get("risk", "")),
    ("journal",  "📋 Journal",       FRAGMENTS.get("journal", "")),
]

_nav = "".join(
    f'<span class="main-tab{" act" if i == 0 else ""}" onclick="showSec(\'{sid}\', this)">{label}</span>'
    for i, (sid, label, _) in enumerate(SECTIONS))

_secs = "".join(
    f'<div id="sec-{sid}" class="main-sec{" act" if i == 0 else ""}"><div style="padding:18px">{frag}</div></div>'
    for i, (sid, label, frag) in enumerate(SECTIONS))

PAGE = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FXmetrics PRO — {_file_date}</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:'Space Grotesk',sans-serif; background:#0a0e1a; color:#e2e8f0; min-height:100vh; }}
  .main-tab {{ padding:10px 14px; font-size:13px; font-weight:500; cursor:pointer;
               border-bottom:2px solid transparent; color:#64748b; display:inline-block; white-space:nowrap; }}
  .main-tab.act {{ color:#e2e8f0; border-bottom-color:#3b82f6; }}
  .main-tab:hover {{ color:#cbd5e1; }}
  .main-sec {{ display:none; }} .main-sec.act {{ display:block; }}
  .sub-tab {{ padding:8px 14px; font-size:12px; font-weight:500; cursor:pointer;
              border-bottom:2px solid transparent; color:#64748b; display:inline-block; }}
  .sub-tab.act {{ color:#e2e8f0; border-bottom-color:#8b5cf6; }}
  .sub-tc {{ display:none; }} .sub-tc.act {{ display:block; }}
</style>
</head>
<body>
<!-- HEADER GLOBAL -->
<div style="background:#111827;border-bottom:1px solid #1e293b;padding:14px 20px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
  <div>
    <span style="font-size:19px;font-weight:700">FX<span style="color:#3b82f6">metrics</span> <span style="color:#a78bfa">V7</span></span>
    <span style="font-size:11px;color:#64748b;margin-left:8px">mémoire des chocs · zones visibles · vent macro</span>
  </div>
  <div style="display:flex;gap:18px;align-items:center;flex-wrap:wrap">
    <span style="font-size:11px;color:#64748b">{_n_tot} actifs analysés</span>
    <span style="font-size:10px;color:#64748b">🏦 {RATES_META["source"]} · obs. {RATES_META["obs"]}</span>
    <span style="font-size:10px;color:#64748b">📡 {globals().get("TD_REPORT","TD ?")}</span>
    <span style="font-size:10px;color:#64748b">⚡ {sum(1 for _s in signals+indices_signals+comm_signals if _s.get("shock"))} chocs récents</span>
    <span style="font-size:12px"><span style="color:#22c55e;font-weight:700;font-family:monospace">{_n_buy}</span> <span style="color:#64748b">BUY</span></span>
    <span style="font-size:12px"><span style="color:#ef4444;font-weight:700;font-family:monospace">{_n_sell}</span> <span style="color:#64748b">SELL</span></span>
    <span style="font-size:12px"><span style="color:#22c55e;font-weight:700;font-family:monospace">{_n_green_global}</span> <span style="color:#64748b">🟢 mûrs</span></span>
    <span style="font-size:11px;color:#64748b;font-family:monospace">{_date_str}</span>
  </div>
</div>
<!-- NAV PRINCIPALE -->
<div style="background:#111827;border-bottom:1px solid #1e293b;padding:0 12px;position:sticky;top:0;z-index:100;overflow-x:auto;white-space:nowrap">
  {_nav}
</div>
<!-- SECTIONS -->
{_secs}
<div style="padding:14px 20px;border-top:1px solid #1e293b;font-size:10px;color:#475569;text-align:center">
  FXmetrics PRO v4.0 · Capital {CAPITAL:,}$ · Risque/trade {RISK_PER_TRADE*100:.1f}% ·
  Le script donne le biais et les faits — la lecture de structure et la décision finale t'appartiennent.
</div>
<script>
function showSec(name, el) {{
  document.querySelectorAll('.main-sec').forEach(s => s.classList.remove('act'));
  document.querySelectorAll('.main-tab').forEach(t => t.classList.remove('act'));
  document.getElementById('sec-' + name).classList.add('act');
  el.classList.add('act');
  window.scrollTo(0, 0);
}}
function subTab(prefix, name, el) {{
  document.querySelectorAll('[id^="' + prefix + '-"]').forEach(t => {{ if (t.classList.contains('sub-tc')) t.classList.remove('act'); }});
  el.parentElement.querySelectorAll('.sub-tab').forEach(t => t.classList.remove('act'));
  document.getElementById(prefix + '-' + name).classList.add('act');
  el.classList.add('act');
}}
</script>
</body>
</html>"""

# ── Publication : docs/index.html (source GitHub Pages) + copie archivée datée ──
_out_path = DOCS_DIR / "index.html"
with open(_out_path, "w", encoding="utf-8") as _f:
    _f.write(PAGE)

_archive_dir = DOCS_DIR / "archive"
_archive_dir.mkdir(parents=True, exist_ok=True)
with open(_archive_dir / f"FXmetrics_{_file_date}.html", "w", encoding="utf-8") as _f:
    _f.write(PAGE)


print("\n" + "═" * 60)
print(f"  ✅ DASHBOARD COMPLET GÉNÉRÉ — {_date_str}")
print(f"  📄 Fichier : {_out_path}  ({len(PAGE)//1024} KB)")
print(f"  💡 Pour navigation plein écran : Cellule 5 → télécharger le fichier")
print(f"  📊 {_n_tot} actifs · {_n_buy} BUY · {_n_sell} SELL · {_n_green_global} setups 🟢 mûrs")
if top3:
    print(f"  🏆 Top 3 : " + " | ".join(f"{s.get('label','?')} {s['direction']} ({s.get('maturity','—')[:2]})" for s in top3))
print("═" * 60)


# ╔══════════════════════════════════════════════════════════╗
# ║  AUTO-LOG — sauvegarde automatique des signaux du jour   ║
# ║  Remplace l'ancienne cellule manuelle (saisie de la paire)║
# ║  puisque le script tourne sans interaction (GitHub Action)║
# ╚══════════════════════════════════════════════════════════╝
# Chaque run ajoute une ligne au journal (data/signals_log.csv) pour
# CHAQUE signal actionnable (BUY/SELL) du jour, sur les 3 classes d'actifs.
# Ce n'est pas un suivi de trade réel (pas de confirmation d'exécution) —
# c'est un historique des signaux suggérés : date, prix d'entrée, SL, TP1/TP2, etc.
# Tu peux toujours utiliser add_trade()/close_trade() à la main (en local)
# si tu veux un jour suivre un trade réellement pris jusqu'à sa clôture.

_all_signals = (
    [dict(s, asset_class="Forex") for s in signals]
    + list(indices_signals)
    + list(comm_signals)
)
_n_logged = 0
for _sig in _all_signals:
    if _sig.get("direction") in ("BUY", "SELL"):
        add_trade(_sig, notes="auto-log")
        _n_logged += 1

print(f"\n💾 {_n_logged} signal(s) actionnable(s) ajouté(s) au journal ({JOURNAL_FILE})")
print("📌 Run terminé. Page publiée dans docs/index.html, historique dans data/signals_log.csv.")
