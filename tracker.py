# tracker.py — Railway worker (x-axis labels forced visible)
# Keeps: multi-webhook, dark theme, red Cylon, one combined PNG, replace-on-edit
# Extra: rotate labels, larger font, added bottom margin, bbox_inches='tight' with facecolor preserved.

import os, io, time, json, hashlib
from datetime import datetime
from typing import List, Tuple, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter, AutoDateLocator
import requests
import pandas as pd
from bs4 import BeautifulSoup

DEFAULT_URL = "https://bsgo.fun/Services/Identity/Account/EU"

def _load_webhooks() -> list[dict]:
    raw = os.environ.get("WEBHOOK_URLS", "").strip()
    if not raw:
        raise SystemExit("WEBHOOK_URLS env var is required (comma-separated URLs or JSON list).")
    try:
        arr = json.loads(raw)
        if isinstance(arr, list):
            out = []
            for it in arr:
                if isinstance(it, dict) and "url" in it:
                    out.append({
                        "url": it["url"],
                        "bsgo_url": it.get("bsgo_url") or os.environ.get("BSGO_URL", DEFAULT_URL),
                        "label": it.get("label") or ""
                    })
            if out:
                return out
    except Exception:
        pass
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    return [{"url": u, "bsgo_url": os.environ.get("BSGO_URL", DEFAULT_URL), "label": ""} for u in urls]

UPDATE_MINUTES = int(os.environ.get("UPDATE_MINUTES", "15"))
RAW_DATA_CSV = "players.csv"
AVG_DATA_CSV = "averages.csv"
LEVEL_RANGES: List[Tuple[int, int]] = [(0,15),(16,25),(26,45),(46,80),(81,139),(140,200),(201,255)]

def fetch_data(url: str) -> pd.DataFrame:
    r = requests.get(url, timeout=30); r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    rows = soup.select("table tbody tr") or soup.select("tr")
    data = []
    for row in rows:
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) >= 4 and cols[3].isdigit():
            faction, pid, name, level = cols[:4]
            data.append({"timestamp": datetime.utcnow(),"faction": faction,"player_id": pid,"name": name,"level": int(level)})
    return pd.DataFrame(data)

def append_to_csv(df: pd.DataFrame, path: str): 
    if df.empty: return
    df.to_csv(path, mode="a", header=not os.path.isfile(path), index=False)

def update_average_csv(colonial: int, cylon: int):
    ts = datetime.utcnow()
    row = pd.DataFrame([{"timestamp": ts, "colonial": colonial, "cylon": cylon}])
    row.to_csv(AVG_DATA_CSV, mode="a", header=not os.path.isfile(AVG_DATA_CSV), index=False)

# ---------- Plot helpers ----------
def _apply_dark(ax):
    ax.set_facecolor("#0e1116")
    if ax.figure: ax.figure.set_facecolor("#0e1116")
    ax.grid(True, color="#3a3f44", alpha=0.5, linestyle="--", linewidth=0.6)

def _autolabel(ax, rects):
    for r in rects:
        h = r.get_height() or 0
        ax.annotate(f"{int(h)}", xy=(r.get_x()+r.get_width()/2, h), xytext=(0,4),
                    textcoords="offset points", ha="center", va="bottom", fontsize=10, color="white")

def _pct_leader_text(df_avg: pd.DataFrame) -> str:
    if df_avg.empty: return "No history yet."
    comp = df_avg.dropna(subset=["colonial","cylon"])
    non_ties = comp[comp["colonial"] != comp["cylon"]]
    if non_ties.empty: return "All samples tied."
    total = len(non_ties)
    col_pct = round((non_ties["colonial"] > non_ties["cylon"]).sum() * 100.0 / total, 1)
    cyl_pct = round((non_ties["cylon"] > non_ties["colonial"]).sum() * 100.0 / total, 1)
    return f"Colonial ahead: {col_pct}% | Cylon ahead: {cyl_pct}%"

def plot_combined(df_current: pd.DataFrame, region_label: str = "") -> io.BytesIO:
    plt.style.use("dark_background")
    df_hist = pd.read_csv(AVG_DATA_CSV, parse_dates=["timestamp"]) if os.path.isfile(AVG_DATA_CSV) else pd.DataFrame()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 9.5), gridspec_kw={"height_ratios":[1,1.1]})

    # Top: Distribution
    _apply_dark(ax1)
    ts_str = df_current["timestamp"].iloc[0].strftime("%Y-%m-%d %H:%M:%S UTC")
    categories, c_col, c_cyl = [], [], []
    for lo, hi in LEVEL_RANGES:
        categories.append(f"{lo}-{hi}")
        c_col.append(len(df_current[(df_current["faction"]=="Colonial") & (df_current["level"].between(lo,hi))]))
        c_cyl.append(len(df_current[(df_current["faction"]=="Cylon")    & (df_current["level"].between(lo,hi))]))
    x = list(range(len(categories))); width = 0.45
    r1 = ax1.bar([i-width/2 for i in x], c_col, width=width, label="Colonial", color="#4f9dff", edgecolor="#cfe8ff", linewidth=0.5)
    r2 = ax1.bar([i+width/2 for i in x], c_cyl, width=width, label="Cylon",    color="#ff0000", edgecolor="#ffb3b3", linewidth=0.5)
    # Explicit x-axis labels (white, rotated, padded)
    ax1.set_xticks(x)
    ax1.set_xticklabels(categories, fontsize=12, rotation=25, ha="right")
    for tick in ax1.get_xticklabels(): tick.set_color("white")
    ax1.tick_params(axis="x", pad=10)
    title_prefix = f"[{region_label}] " if region_label else ""
    ax1.set_title(f"{title_prefix}Player Level Distribution by Faction ({ts_str})", fontsize=16, weight="bold")
    ax1.set_xlabel("Level Range", fontsize=13); ax1.set_ylabel("Count", fontsize=13)
    ax1.legend()
    _autolabel(ax1, r1); _autolabel(ax1, r2)
    ax1.text(0.98, 0.90, f"Colonial: {sum(c_col)}   Cylon: {sum(c_cyl)}   Total: {len(df_current)}",
             ha="right", va="top", transform=ax1.transAxes, fontsize=12, color="white",
             bbox=dict(facecolor="#1a1d22", alpha=0.65, edgecolor="#3a3f44", boxstyle="round,pad=0.35"))

    # Bottom: Time series
    _apply_dark(ax2)
    if not df_hist.empty:
        ax2.plot(df_hist["timestamp"], df_hist["colonial"], label="Colonial", linewidth=1.9, color="#4f9dff")
        ax2.plot(df_hist["timestamp"], df_hist["cylon"],    label="Cylon",    linewidth=1.9, color="#ff0000")
        ax2.set_title(f"{title_prefix}Players Online Over Time", fontsize=16, weight="bold")
        ax2.set_xlabel("Timestamp (UTC)", fontsize=13); ax2.set_ylabel("Players Online", fontsize=13)
        ax2.legend()
        ax2.xaxis.set_major_locator(AutoDateLocator()); ax2.xaxis.set_major_formatter(DateFormatter("%m-%d %H:%M"))
        fig.autofmt_xdate(rotation=45)
        ax2.text(0.99, 0.03, _pct_leader_text(df_hist), transform=ax2.transAxes, ha="right", va="bottom",
                 fontsize=12, color="white", bbox=dict(facecolor="#1a1d22", edgecolor="#3a3f44", alpha=0.75, boxstyle="round,pad=0.35"))
    else:
        ax2.text(0.5,0.5,"No history yet to plot.", transform=ax2.transAxes, ha="center", va="center", fontsize=13, color="white")
        ax2.set_axis_off()

    # Extra bottom margin + tight layout to prevent clipping in Discord preview
    fig.tight_layout(h_pad=2.2, rect=[0.04,0.06,0.995,0.995])
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=320, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig); buf.seek(0)
    return buf

# Webhook helpers
def _id_file_for_webhook(url: str) -> str:
    return f"last_id_{hashlib.md5(url.encode('utf-8')).hexdigest()[:10]}.txt"
def _read_last_msg_id(url: str) -> Optional[str]:
    p = _id_file_for_webhook(url)
    if os.path.exists(p):
        try:
            with open(p,"r") as f: return f.read().strip()
        except: return None
    return None
def _write_last_msg_id(url: str, mid: str):
    try:
        with open(_id_file_for_webhook(url),"w") as f: f.write(mid)
    except: pass

def send_to_discord(webhook_url: str, combined_png: io.BytesIO, summary_text: str):
    last_id = _read_last_msg_id(webhook_url)
    combined_png.seek(0)
    files = {"file1": ("bsgo_stats.png", combined_png, "image/png")}
    data = {"content": summary_text}
    if last_id:
        data["payload_json"] = json.dumps({"attachments": []})  # replace prior attachment
        url = webhook_url.rstrip("/") + f"/messages/{last_id}"
        r = requests.patch(url, data=data, files=files, timeout=60)
    else:
        r = requests.post(webhook_url, data=data, files=files, timeout=60)
    if r.ok:
        try:
            js = r.json()
            if "id" in js: _write_last_msg_id(webhook_url, js["id"])
        except: pass
    else:
        print("Webhook error:", r.status_code, r.text)

def run_once_for(cfg: dict):
    url = cfg["url"]; bsgo_url = cfg.get("bsgo_url") or DEFAULT_URL; label = cfg.get("label") or ""
    df = fetch_data(bsgo_url)
    if df.empty: print(f"[{label or url}] Warning: no data fetched."); return
    append_to_csv(df, RAW_DATA_CSV)
    colonials = (df["faction"]=="Colonial").sum(); cylons = (df["faction"]=="Cylon").sum()
    update_average_csv(colonials, cylons)
    summary = (f"[{label}] " if label else "") + f"Colonial Players: {colonials}\nCylon Players: {cylons}\nTotal Players: {len(df)}"
    combo = plot_combined(df, region_label=label)
    send_to_discord(url, combo, summary)

if __name__ == "__main__":
    hooks = _load_webhooks()
    print(f"Loaded {len(hooks)} webhook(s). Interval: {UPDATE_MINUTES} min.")
    while True:
        print(f"Running update at {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        try:
            for cfg in hooks: run_once_for(cfg)
        except Exception as e:
            print("Error during run:", e)
        print(f"Next update in {UPDATE_MINUTES} minutes..."); time.sleep(60*UPDATE_MINUTES)
