#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html as htmlmod
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup, Comment


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def reconstruct_real_fbref_html(raw_html: str) -> str:
    """
    Handles two cases:
      1) Normal saved FBref HTML (already parseable) -> return as-is.
      2) Firefox/Chromium 'view-source'-like saved HTML where the real page source is rendered
         as text with syntax-highlighting spans -> extract the rendered text and return it.
    """
    # Fast path: looks like already the real page
    if 'id="sched_all"' in raw_html and "<table" in raw_html:
        return raw_html

    soup = BeautifulSoup(raw_html, "html.parser")

    # If this is a view-source wrapper, the *visible text* contains the real HTML.
    # IMPORTANT: do NOT use get_text("\n") because it inserts newlines between text nodes and breaks tags.
    rendered = soup.get_text("")  # preserve tag integrity
    rendered = htmlmod.unescape(rendered)

    # Trim leading junk before the actual HTML document
    start = rendered.find("<!DOCTYPE html>")
    if start == -1:
        start = rendered.find("<html")
    if start == -1:
        # As a fallback, just return the rendered blob
        return rendered

    return rendered[start:]


def find_table_html(real_html: str, table_id: str) -> str:
    """
    FBref sometimes wraps tables inside HTML comments. We:
      1) look for <table id=...> directly
      2) look inside HTML comments for the table
    Returns the table HTML string.
    """
    soup = BeautifulSoup(real_html, "html.parser")

    table = soup.find("table", id=table_id)
    if table is not None:
        return str(table)

    # Search inside comment-wrapped blocks
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        if table_id in c:
            csoup = BeautifulSoup(c, "html.parser")
            ctable = csoup.find("table", id=table_id)
            if ctable is not None:
                return str(ctable)

    raise RuntimeError(f"Could not find <table id='{table_id}'> in the reconstructed HTML.")


def txt(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def parse_sched_xg(table_html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(table_html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError("Internal error: table_html did not contain a <table>.")

    tbody = table.find("tbody")
    if tbody is None:
        raise RuntimeError("Schedule table has no <tbody>.")

    rows: List[Dict[str, str]] = []

    for tr in tbody.find_all("tr"):
        # Match rows have these
        home_td = tr.find("td", attrs={"data-stat": "home_team"})
        away_td = tr.find("td", attrs={"data-stat": "away_team"})
        if not home_td or not away_td:
            continue

        date_td = tr.find("td", attrs={"data-stat": "date"})
        time_td = tr.find("td", attrs={"data-stat": "start_time"}) or tr.find("td", attrs={"data-stat": "time"})
        score_td = tr.find("td", attrs={"data-stat": "score"})

        home_xg_td = tr.find("td", attrs={"data-stat": "home_xg"})
        away_xg_td = tr.find("td", attrs={"data-stat": "away_xg"})

        # Optional match report link
        report_td = tr.find("td", attrs={"data-stat": "match_report"})
        report_a = report_td.find("a") if report_td else None
        report_href = report_a.get("href", "") if report_a else ""

        def norm_xg(s: str) -> str:
            s = s.strip()
            if s in ("", "—", "-", "N/A"):
                return ""
            try:
                return str(float(s))
            except ValueError:
                return ""

        row = {
            "date": txt(date_td),
            "time": txt(time_td),
            "home": txt(home_td),
            "away": txt(away_td),
            "score": txt(score_td),
            "home_xg": norm_xg(txt(home_xg_td)),
            "away_xg": norm_xg(txt(away_xg_td)),
            "match_report_href": report_href,
        }
        rows.append(row)

    if not rows:
        raise RuntimeError("Parsed 0 match rows from the schedule table.")

    return rows


def write_csv(rows: List[Dict[str, str]], out_path: Path) -> None:
    fieldnames = ["date", "time", "home", "away", "score", "home_xg", "away_xg", "match_report_href"]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract xG per match from a locally saved FBref schedule HTML file.")
    ap.add_argument("--html", required=True, help="Path to the saved .html file")
    ap.add_argument("--out", default="xg.csv", help="Output CSV path")
    ap.add_argument("--table-id", default="sched_all", help="FBref schedule table id (default: sched_all)")
    args = ap.parse_args()

    raw = read_text(Path(args.html))
    real_html = reconstruct_real_fbref_html(raw)
    table_html = find_table_html(real_html, args.table_id)
    rows = parse_sched_xg(table_html)
    write_csv(rows, Path(args.out))

    non_empty_xg = sum(1 for r in rows if (r["home_xg"] or r["away_xg"]))
    print(f"Wrote {len(rows)} matches to {args.out} (rows with xG present: {non_empty_xg}).")


if __name__ == "__main__":
    main()
