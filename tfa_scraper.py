#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time

BASE = "https://www.tabroom.com"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) Python scraper (respectful)"
})

def get_soup(url: str) -> BeautifulSoup:
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def extract_result_ids_from_index(tourn_id: str) -> list[int]:
    """Pull all result_ids linked on the tournament results index."""
    url = f"{BASE}/index/tourn/results/index.mhtml?tourn_id={tourn_id}"
    soup = get_soup(url)
    ids = set()
    for a in soup.select("a[href*='event_results.mhtml']"):
        href = a.get("href") or ""
        m = re.search(r"result_id=(\d+)", href)
        if m:
            ids.add(int(m.group(1)))
    ids = sorted(ids)
    print(f"Found {len(ids)} candidate result_ids on index.")
    if ids:
        print(f"  sample: {ids[:5]} ... {ids[-5:]}")
    return ids

def find_tfa_table(soup: BeautifulSoup):
    """Locate the TFA Qualification table."""
    heading = soup.find(["h3", "h4"], string=lambda x: x and ("TFA" in x or "Qualification" in x))
    if heading:
        tbl = heading.find_next("table")
        if tbl:
            return tbl
    # fallback scan
    for tbl in soup.find_all("table"):
        header_cells = tbl.find("tr")
        if not header_cells:
            continue
        texts = [c.get_text(" ", strip=True).lower() for c in header_cells.find_all(["th","td"])]
        header_str = " ".join(texts)
        if ("point" in header_str) and ("place" in header_str or "placed" in header_str):
            return tbl
        if len(texts) >= 3 and ("point" in header_str or "tfa" in header_str):
            return tbl
    return None

def parse_tfa_rows(table, event_name: str) -> list[dict]:
    """Parse rows in the TFA table into points, entry, school, qualifying event, event name."""
    out = []
    rows = table.find_all("tr")
    if not rows:
        return out
    start_idx = 1 if rows and rows[0].find_all(["th","td"]) else 0
    for tr in rows[start_idx:]:
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        try:
            pts_str = tds[0].get_text(" ", strip=True)
            pts_match = re.search(r"[-+]?\d*\.?\d+", pts_str.replace(",", ""))
            if not pts_match:
                continue
            points = float(pts_match.group(0))
        except Exception:
            continue
        entry = tds[2].get_text(" ", strip=True) if len(tds) >= 3 else ""
        school = tds[3].get_text(" ", strip=True) if len(tds) >= 4 else ""
        qualifying_event = tds[4].get_text(" ", strip=True) if len(tds) >= 5 else ""
        out.append({
            "points": points,
            "entry": entry,
            "school": school,
            "qualifying_event": qualifying_event,
            "event": event_name
        })
    return out

def get_event_name(soup: BeautifulSoup) -> str:
    h2 = soup.find("h2")
    if h2:
        name = h2.get_text(" ", strip=True)
        if name:
            return name
    if soup.title and soup.title.text:
        return soup.title.text.split("|")[0].strip()
    return "Unknown Event"

def page_has_tfa_points(tourn_id: str, result_id: int) -> tuple[list[dict], str]:
    """Fetch a page and return (rows, event_name) if it contains TFA table."""
    url = f"{BASE}/index/tourn/results/event_results.mhtml?tourn_id={tourn_id}&result_id={result_id}"
    try:
        soup = get_soup(url)
    except requests.HTTPError:
        return [], "Unknown Event"
    event_name = get_event_name(soup)
    tbl = find_tfa_table(soup)
    if not tbl:
        return [], event_name
    rows = parse_tfa_rows(tbl, event_name)
    return rows, event_name

def find_true_starting_result_id(tourn_id: str, candidates: list[int]) -> int | None:
    for rid in sorted(candidates):
        rows, ev = page_has_tfa_points(tourn_id, rid)
        if rows:
            print(f"First TFA page found at result_id={rid} ({ev})")
            return rid
        time.sleep(0.5)
    return None

def scrape_tfa_tournament(tourn_id: str, empty_streak_limit: int = 12) -> list[dict]:
    print(f"Starting scrape for tourn_id={tourn_id}")
    candidates = extract_result_ids_from_index(tourn_id)
    if not candidates:
        print("No candidate result_ids found.")
        return []
    start_id = find_true_starting_result_id(tourn_id, candidates)
    if start_id is None:
        print("No TFA tables found; starting from min candidate.")
        start_id = min(candidates)
    all_rows = []
    rid = start_id
    empty_streak = 0
    print(f"Scanning upward from result_id={rid} ...")
    while empty_streak < empty_streak_limit:
        rows, ev = page_has_tfa_points(tourn_id, rid)
        if rows:
            print(f"→ {len(rows):>3} rows @ result_id={rid} [{ev}]")
            all_rows.extend(rows)
            empty_streak = 0
        else:
            print(f"   (no points) result_id={rid}")
            empty_streak += 1
        rid += 1
        time.sleep(0.6)
    print(f"Stopped after {empty_streak_limit} consecutive empties. Last tried result_id={rid-1}.")
    return all_rows

if __name__ == "__main__":
    tourn_id = input("Enter TFA tournament ID: ").strip()
    data = scrape_tfa_tournament(tourn_id)
    if data:
        df = pd.DataFrame(data)[["points", "entry", "school", "qualifying_event", "event"]]
        out = f"tfa_points_{tourn_id}.csv"
        df.to_csv(out, index=False)
        print(f"\n✅ Saved {len(df)} rows to {out}")
    else:
        print("\n⚠️ No TFA Qualification data found.")
