"""
rbi_wss_updater.py
==================
Scrapes RBI Weekly Statistical Supplement Extract.
Appends new Friday rows to data/rbi_weekly.csv in the repo.
Skips Fridays already present — safe to run multiple times.

RUN LOCALLY:
  python rbi_wss_updater.py

OUTPUT FILE: data/rbi_weekly.csv
  One row per Friday from 2026-01-01 onwards.
"""

import csv
import re
import datetime
import os
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

WSS_BASE_URL   = "https://www.rbi.org.in/Scripts/BS_viewWssExtract.aspx"
BACKFILL_START = datetime.date(2026, 1, 1)

OUTPUT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", "rbi_weekly.csv"
)

COLUMNS = [
    "Total Forex Reserves (USD Bn)",
    "Foreign Currency Assets (USD Bn)",
    "Gold Reserves (USD Bn)",
    "SDRs (USD Bn)",
    "IMF Reserve Position (USD Bn)",
    "Aggregate Deposits - SCB (INR Crore)",
    "Bank Credit - SCB (INR Crore)",
    "M3 Broad Money (INR Crore)",
    "Currency with Public (INR Crore)",
    "Time Deposits with Banks (INR Crore)",
]

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": WSS_BASE_URL,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def all_fridays_since(start: datetime.date) -> list:
    fridays = []
    days_until_friday = (4 - start.weekday()) % 7
    current = start + datetime.timedelta(days=days_until_friday)
    today = datetime.date.today()
    while current <= today:
        fridays.append(current)
        current += datetime.timedelta(weeks=1)
    return fridays


def load_existing_dates(filepath: str) -> set:
    if not os.path.exists(filepath):
        return set()
    existing = set()
    with open(filepath, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row.get("Date", "").strip()
            if d:
                existing.add(d)
    print(f"Existing CSV: {len(existing)} rows already present")
    return existing


def fetch_wss_text(date: datetime.date) -> Optional[str]:
    date_str = f"{date.month}/{date.day}/{date.year}"
    url = f"{WSS_BASE_URL}?SelectedDate={date_str}"
    try:
        session = requests.Session()
        session.headers.update(REQUEST_HEADERS)
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        session.close()
        soup = BeautifulSoup(resp.text, "lxml")
        for td in soup.find_all(["td", "div", "p"]):
            text = td.get_text(" ", strip=True)
            if "Foreign Exchange Reserves" in text and "Total Reserves" in text:
                return text
    except Exception as e:
        print(f"    Fetch error: {e}")
    return None


def extract_row(text: str, date: datetime.date) -> dict:
    result = {"Date": str(date)}

    def get(pattern, group=1, divisor=None) -> str:
        m = re.search(pattern, text)
        if m:
            raw = m.group(group).replace(",", "")
            if divisor:
                return f"{float(raw) / divisor:.3f}"
            return raw
        return ""

    result["Total Forex Reserves (USD Bn)"]        = get(r'1\s+Total Reserves\s+[\d,]+\s+([\d,]+)', divisor=1000)
    result["Foreign Currency Assets (USD Bn)"]     = get(r'1\.1\s+Foreign Currency Assets[^\d]*([\d,]+)\s+([\d,]+)', group=2, divisor=1000)
    result["Gold Reserves (USD Bn)"]               = get(r'1\.2\s+Gold\s+[\d,]+\s+([\d,]+)', divisor=1000)
    result["SDRs (USD Bn)"]                        = get(r'1\.3\s+SDRs\s+[\d,]+\s+([\d,]+)', divisor=1000)
    result["IMF Reserve Position (USD Bn)"]        = get(r'1\.4\s+Reserve Position in the IMF\s+[\d,]+\s+([\d,]+)', divisor=1000)
    result["Aggregate Deposits - SCB (INR Crore)"] = get(r'2\.1\s+Aggregate Deposits\s+([\d,]+)')
    result["Bank Credit - SCB (INR Crore)"]        = get(r'7\s+Bank Credit\s+([\d,]+)')
    result["M3 Broad Money (INR Crore)"]           = get(r'\bM3\b\s+[\d,]+\s+([\d,]+)')
    result["Currency with Public (INR Crore)"]     = get(r'1\.1\s+Currency with the Public\s+[\d,]+\s+([\d,]+)')
    result["Time Deposits with Banks (INR Crore)"] = get(r'1\.3\s+Time Deposits with Banks\s+[\d,]+\s+([\d,]+)')

    return result


def write_rows(filepath: str, new_rows: list):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    file_exists = os.path.exists(filepath)
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Date"] + COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(new_rows)


def main():
    print(f"Output file: {OUTPUT_FILE}")
    existing_dates = load_existing_dates(OUTPUT_FILE)
    fridays = all_fridays_since(BACKFILL_START)
    missing = [f for f in fridays if str(f) not in existing_dates]

    print(f"Fridays total: {len(fridays)} | In CSV: {len(existing_dates)} | To fetch: {len(missing)}\n")

    if not missing:
        print("CSV is already up to date.")
        return

    new_rows = []
    for i, friday in enumerate(missing, 1):
        print(f"[{i:2d}/{len(missing)}] {friday} ", end="", flush=True)
        text = fetch_wss_text(friday)
        if text:
            row = extract_row(text, friday)
            found = sum(1 for k, v in row.items() if k != "Date" and v)
            print(f"-> {found}/{len(COLUMNS)} values extracted")
            new_rows.append(row)
        else:
            row = {"Date": str(friday)}
            for col in COLUMNS:
                row[col] = ""
            new_rows.append(row)
            print("-> No data")
        if i < len(missing):
            time.sleep(2)

    write_rows(OUTPUT_FILE, new_rows)
    filled = sum(1 for r in new_rows for k, v in r.items() if k != "Date" and v)
    total  = len(new_rows) * len(COLUMNS)
    print(f"\nDone. Appended {len(new_rows)} rows. {filled}/{total} cells filled.")


if __name__ == "__main__":
    main()
