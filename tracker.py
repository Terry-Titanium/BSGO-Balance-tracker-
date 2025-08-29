# tracker.py
# Multi-webhook BSGO tracker for Railway.
# Updates:
# - Cylon bars are pure red (#ff0000)
# - Both charts are combined into ONE image (two subplots)
# - When editing an existing webhook message, the single PNG is REPLACED

import os
import io
import time
import json
import hashlib
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
    # Try JSON first
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
    # Fallback: comma-separated URLs
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    return [{"url": u, "bsgo_url": os.environ.get("BSGO_URL", DEFAULT_URL), "label": ""} for u in urls]

UPDATE_MINUTES = int(os.environ.get("UPDATE_MINUTES", "15"))

RAW_DATA_CSV = "players.csv"
AVG_DATA_CSV = "averages.csv"

LEVEL_RANGES: List[Tuple[int, int]] = [
    (0, 15), (16, 25), (26, 45), (46, 80), (81, 139), (140, 200), (201, 255)
]

def fetch_data(url: str) -> pd.DataFrame:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select("table tbody tr") or soup.select("tr")
    data = []
    for row in rows:
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) >= 4:
            faction, pid, name, level = cols[:4]
            if level.isdigit():
                data.append({
                    "timestamp": datetime.utcnow(),
                    "faction": faction,
                    "player_id": pid,
                    "name": name,
                    "level": int(level)
                })
    return pd.DataFrame(data)

def append_to_csv(df: pd.DataFrame, filepath: str) -> None:
    if df.empty:
        return
    header = not os.path.isfile(filepath)
    df.to_csv(filepath, mode='a', header=header, index=False)

def update_average_csv(colonial_count: int, cylon_count: int) -> None:
    ts = datetime.utcnow()
    header = not os.path.isfile(AVG_DATA_CSV)
    new_row = pd.DataFrame([{
        "timestamp": ts,
        "colonial": colonial_count,
        "cylon": cylon_count
    }])
    new_row.to_csv(AVG_DATA_CSV, mode='a', header=header, index=False)

# ---------- Chart helpers ----------
def _apply_dark(ax):
    ax.set_facecolor("#0e1116")
    if ax.figure:
        ax.figure.set_facecolor("#0e1116")
    ax.grid(True, color("#3a3f44"), alpha=0.5, linestyle="--", linewidth=0.6)

def _autolabel(ax, rects):
    for r in rects:
        height = r.get_height() or 0
        ax.annotate(f"{int(height)}",
                    xy=(r.get_x() + r.get_width() / 2, height),
                    xytext=(0, 4), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9, color="white")

def _pct_leader_text(df_avg: pd.DataFrame) -> str:
    if df_avg.empty:
        return "No history yet."
    comp = df_avg.dropna(subset=["colonial", "cylon"]).copy()
    if comp.empty:
        return "No history yet."
    non_ties = comp[comp["colonial"] != comp["cylon"]]
    if non_ties.empty:
        return "All samples tied."
    total = len(non_ties)
    col_ahead = (non_ties["colonial"] > non_ties["cylon"]).sum()
    cyl_ahead = (non_ties["cylon"] > non_ties["colonial"]).sum()
    col_pct = round(col_ahead * 100.0 / total, 1)
    cyl_pct = round(cyl_ahead * 100.0 / total, 1)
    return f"Colonial ahead: {col_pct}% | Cylon ahead: {cyl_pct}%"

def plot_combined(df_current: pd.DataFrame, region_label: str = "") -> io.BytesIO:
    """Create ONE PNG with two subplots: distribution (top) + time series (bottom)."""
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter, AutoDateLocator
    import pandas as pd
    plt.style.use("dark_background")

    # Load history for time-series (if present)
    df_hist = None
    if os.path.isfile(AVG_DATA_CSV):
        try:
            df_hist = pd.read_csv(AVG_DATA_CSV, parse_dates=['timestamp'])
        except Exception:
            df_hist = None

    # Build the figure
    fig, (ax1, ax2) = plt.subplots(nrows=2, ncols=1, figsize=(11, 9), gridspec_kw={'height_ratios':[1,1.1]})

    # ----- Top: Distribution -----
    _apply_dark(ax1)
    ts_str = df_current['timestamp'].iloc[0].strftime("%Y-%m-%d %H:%M:%S UTC")
    categories, counts_colonial, counts_cylon = [], [], []
    colonial_count = (df_current['faction'] == "Colonial").sum()
    cylon_count = (df_current['faction'] == "Cylon").sum()
    total_count = len(df_current)
    for low, high in LEVEL_RANGES:
        categories.append(f"{low}-{high}")
        counts_colonial.append(len(df_current[(df_current['faction'] == "Colonial") & (df_current['level'].between(low, high))]))
        counts_cylon.append(len(df_current[(df_current['faction'] == "Cylon") & (df_current['level'].between(low, high))]))
    x = range(len(categories))
    width = 0.45
    rects1 = ax1.bar([i - width/2 for i in x], counts_colonial, width=width, label="Colonial", color="#4f9dff", edgecolor="#cfe8ff", linewidth=0.5)
    rects2 = ax1.bar([i + width/2 for i in x], counts_cylon,    width=width, label="Cylon",    color="#ff0000", edgecolor="#ffb3b3", linewidth=0.5)
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(categories, fontsize=10)
    title_prefix = f"[{region_label}] " if region_label else ""
    ax1.set_title(f"{title_prefix}Player Level Distribution by Faction ({ts_str})", fontsize=14, weight="bold")
    ax1.set_xlabel("Level Range", fontsize=12)
    ax1.set_ylabel("Count", fontsize=12)
    ax1.legend()
    _autolabel(ax1, rects1)
    _autolabel(ax1, rects2)
    ax1.text(0.98, 0.92, f"Colonial: {colonial_count}   Cylon: {cylon_count}   Total: {total_count}",
             ha='right', va='top', transform=ax1.transAxes, fontsize=10, color='white',
             bbox=dict(facecolor='#1a1d22', alpha=0.65, edgecolor='#3a3f44', boxstyle='round,pad=0.35'))

    # ----- Bottom: Time series -----
    _apply_dark(ax2)
    if df_hist is not None and not df_hist.empty:
        ax2.plot(df_hist["timestamp"], df_hist["colonial"], label="Colonial", linewidth=1.8, color="#4f9dff")
        ax2.plot(df_hist["timestamp"], df_hist["cylon"],    label="Cylon",    linewidth=1.8, color="#ff0000")
        ax2.set_title(f"{title_prefix}Players Online Over Time", fontsize=14, weight="bold")
        ax2.set_xlabel("Timestamp (UTC)", fontsize=12)
        ax2.set_ylabel("Players Online", fontsize=12)
        ax2.legend()
        ax2.xaxis.set_major_locator(AutoDateLocator())
        ax2.xaxis.set_major_formatter(DateFormatter('%m-%d %H:%M'))
        fig.autofmt_xdate(rotation=45)
        # % leader box
        pct_text = _pct_leader_text(df_hist)
        ax2.text(0.99, 0.03, pct_text, transform=ax2.transAxes, ha="right", va="bottom",
                 fontsize=11, color="white",
                 bbox=dict(facecolor="#1a1d22", edgecolor="#3a3f44", alpha=0.75, boxstyle="round,pad=0.35"))
    else:
        ax2.text(0.5, 0.5, "No history yet to plot.", transform=ax2.transAxes, ha="center", va="center", fontsize=12, color="white")
        ax2.set_axis_off()

    plt.tight_layout(h_pad=2)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=300)
    plt.close(fig)
    buf.seek(0)
    return buf

# ---------- Webhook helpers ----------
def _id_file_for_webhook(url: str) -> str:
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
    return f"last_id_{h}.txt"

def _read_last_msg_id(url: str) -> Optional[str]:
    path = _id_file_for_webhook(url)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except Exception:
            return None
    return None

def _write_last_msg_id(url: str, mid: str) -> None:
    path = _id_file_for_webhook(url)
    try:
        with open(path, "w") as f:
            f.write(mid)
    except Exception:
        pass

def send_to_discord(webhook_url: str, combined_png: io.BytesIO, summary_text: str) -> None:
    """Send ONE image and replace the prior one if editing the last message."""
    last_id = _read_last_msg_id(webhook_url)
    combined_png.seek(0)
    files = {
        "file1": ("bsgo_stats.png", combined_png, "image/png")
    }
    # payload_json allows us to control attachments (empty array removes old ones)
    payload = {"attachments": []} if last_id else None
    data = {"content": summary_text}
    if payload is not None:
        data["payload_json"] = json.dumps(payload)
    try:
        if last_id:
            edit_url = webhook_url.rstrip("/") + f"/messages/{last_id}"
            r = requests.patch(edit_url, data=data, files=files, timeout=60)
        else:
            r = requests.post(webhook_url, data=data, files=files, timeout=60)
        if not r.ok:
            print("Webhook error:", r.status_code, r.text)
        else:
            try:
                js = r.json()
                if "id" in js:
                    _write_last_msg_id(webhook_url, js["id"])
            except Exception:
                pass
    except Exception as e:
        print("Webhook request failed:", e)

# ---------- Main run ----------
def run_once_for(webhook_cfg: dict) -> None:
    url = webhook_cfg["url"]
    bsgo_url = webhook_cfg.get("bsgo_url") or DEFAULT_URL
    label = webhook_cfg.get("label") or ""
    df = fetch_data(bsgo_url)
    if df.empty:
        print(f"[{label or url}] Warning: no data fetched.")
        return
    append_to_csv(df, RAW_DATA_CSV)
    colonial_count = (df['faction'] == "Colonial").sum()
    cylon_count = (df['faction'] == "Cylon").sum()
    total_count = len(df)
    update_average_csv(colonial_count, cylon_count)
    summary = (
        (f"[{label}] " if label else "") +
        f"Colonial Players: {colonial_count}\n"
        f"Cylon Players: {cylon_count}\n"
        f"Total Players: {total_count}"
    )
    combined = plot_combined(df_current=df, region_label=label)
    send_to_discord(url, combined, summary)

if __name__ == "__main__":
    webhooks = _load_webhooks()
    print(f"Loaded {len(webhooks)} webhook(s). Interval: {UPDATE_MINUTES} min.")
    while True:
        print(f"Running update at {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        try:
            for cfg in webhooks:
                run_once_for(cfg)
        except Exception as e:
            print("Error during run:", e)
        print(f"Next update in {UPDATE_MINUTES} minutes...")
        time.sleep(60 * UPDATE_MINUTES)
