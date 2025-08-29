# tracker.py
# Webhook-based BSGO tracker for Railway with **multiple webhooks** support.
#
# It scrapes, plots, and posts images & summary to one or more Discord Webhooks every N minutes.
#
# Env vars (Railway -> Variables):
#   WEBHOOK_URLS  -> required. Either:
#       - Comma-separated list of webhook URLs
#         e.g. "https://discord.com/api/webhooks/ID1/TOKEN1,https://discord.com/api/webhooks/ID2/TOKEN2"
#       - OR JSON list of objects for per-webhook config:
#         '[{"url":"https://...1","bsgo_url":"https://bsgo.fun/Services/Identity/Account/EU","label":"EU"},'
#          ' {"url":"https://...2","bsgo_url":"https://bsgo.fun/Services/Identity/Account/US","label":"US"}]'
#   BSGO_URL      -> optional default scrape endpoint if not specified per webhook (defaults to EU endpoint)
#   UPDATE_MINUTES-> optional (default 15)
#
# Files created during runtime (ephemeral between deploys):
#   players.csv, averages.csv, last_id_<hash>.txt (per-webhook last message id)
#
# Start with Procfile: worker: python tracker.py

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

def plot_distribution(df: pd.DataFrame, region_label: str = "") -> io.BytesIO:
    ts_str = df['timestamp'].iloc[0].strftime("%Y-%m-%d %H:%M:%S UTC")
    categories, counts_colonial, counts_cylon = [], [], []
    colonial_count = (df['faction'] == "Colonial").sum()
    cylon_count = (df['faction'] == "Cylon").sum()
    total_count = len(df)
    for low, high in LEVEL_RANGES:
        categories.append(f"{low}-{high}")
        counts_colonial.append(len(df[(df['faction'] == "Colonial") & (df['level'].between(low, high))]))
        counts_cylon.append(len(df[(df['faction'] == "Cylon") & (df['level'].between(low, high))]))
    fig, ax = plt.subplots(figsize=(8,5))
    x = range(len(categories))
    ax.bar([i - 0.2 for i in x], counts_colonial, width=0.4, label="Colonial")
    ax.bar([i + 0.2 for i in x], counts_cylon, width=0.4, label="Cylon")
    ax.set_xticks(list(x))
    ax.set_xticklabels(categories, fontsize=10)
    title_prefix = f"[{region_label}] " if region_label else ""
    ax.set_title(f"{title_prefix}Player Level Distribution by Faction\n({ts_str})", fontsize=14, weight="bold")
    ax.set_xlabel("Level Range", fontsize=12)
    ax.set_ylabel("Count", fontsize=12)
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.text(0.98, 0.95, f"Colonial: {colonial_count}\nCylon: {cylon_count}\nTotal: {total_count}",
            ha='right', va='top', transform=ax.transAxes, fontsize=10,
            bbox=dict(facecolor='white', alpha=0.6, edgecolor='none'))
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=300)
    plt.close(fig)
    buf.seek(0)
    return buf

def plot_average_players(region_label: str = "") -> Optional[io.BytesIO]:
    if not os.path.isfile(AVG_DATA_CSV):
        return None
    df = pd.read_csv(AVG_DATA_CSV, parse_dates=['timestamp'])
    fig, ax = plt.subplots(figsize=(10,5))
    ax.plot(df["timestamp"], df["colonial"], label="Colonial", linewidth=1.5)
    ax.plot(df["timestamp"], df["cylon"], label="Cylon", linewidth=1.5)
    title_prefix = f"[{region_label}] " if region_label else ""
    ax.set_title(f"{title_prefix}Players Online Over Time", fontsize=14, weight="bold")
    ax.set_xlabel("Timestamp (UTC)", fontsize=12)
    ax.set_ylabel("Players Online", fontsize=12)
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(AutoDateLocator())
    ax.xaxis.set_major_formatter(DateFormatter('%m-%d %H:%M'))
    fig.autofmt_xdate(rotation=45)
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=300)
    plt.close(fig)
    buf.seek(0)
    return buf

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

def send_to_discord(webhook_url: str, distribution_png: io.BytesIO, averages_png: Optional[io.BytesIO], summary_text: str) -> None:
    last_id = _read_last_msg_id(webhook_url)
    files = {}
    data = {"content": summary_text}
    distribution_png.seek(0)
    files["file1"] = ("distribution.png", distribution_png, "image/png")
    if averages_png is not None:
        averages_png.seek(0)
        files["file2"] = ("averages.png", averages_png, "image/png")
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
    dist_img = plot_distribution(df, region_label=label)
    avg_img = plot_average_players(region_label=label)
    send_to_discord(url, dist_img, avg_img, summary)

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
