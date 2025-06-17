import requests
import pandas as pd
import json
import time
from pathlib import Path
from typing import Iterable

HEADERS = {"User-Agent": "my research script (myemail@example.com)"}

# read S&P 500 tickers from Wikipedia
def load_sp500_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    table = pd.read_html(url, header=0)[0]
    return [t.strip().lower() for t in table["Symbol"].tolist()]

# map ticker to CIK using SEC's ticker.txt list
def load_cik_mapping():
    resp = requests.get("https://www.sec.gov/include/ticker.txt", headers=HEADERS)
    resp.raise_for_status()
    mapping = {}
    for line in resp.text.strip().splitlines():
        ticker, cik = line.split()
        mapping[ticker.lower()] = cik
    return mapping

# fetch companyfacts JSON for a given CIK
def fetch_company_facts(cik: str) -> dict | None:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    print(f"Failed to load CIK {cik}: {resp.status_code}")
    return None

# flatten all us-gaap items into a DataFrame
def flatten_facts(facts: dict, forms=("10-Q", "10-K")) -> pd.DataFrame:
    rows = []
    us_gaap = facts.get("us-gaap", {})
    for tag, info in us_gaap.items():
        for uom, records in info.get("units", {}).items():
            for rec in records:
                if rec.get("form") not in forms:
                    continue
                rows.append({
                    "tag": tag,
                    "uom": uom,
                    "value": rec.get("val"),
                    "end": rec.get("end"),
                    "fy": rec.get("fy"),
                    "fp": rec.get("fp"),
                    "form": rec.get("form"),
                    "filed": rec.get("filed"),
                    "frame": rec.get("frame"),
                })
    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values(["end", "tag"], inplace=True)
    return df


def pivot_quarterly(df: pd.DataFrame, items: Iterable[str] | None = None) -> pd.DataFrame:
    """Return a pivoted table (tag x quarter) sorted oldest to newest."""
    qdf = df[(df["form"] == "10-Q") & (df["uom"] == "USD")].copy()
    if items is not None:
        qdf = qdf[qdf["tag"].isin(items)]

    qdf["quarter_num"] = qdf["fp"].str.extract(r"Q(\d)").astype(float)
    qdf = qdf.dropna(subset=["quarter_num", "fy"])
    qdf["quarter_num"] = qdf["quarter_num"].astype(int)
    qdf["year"] = qdf["fy"].astype(int)
    qdf["quarter"] = qdf["quarter_num"].astype(str) + "Q" + qdf["year"].astype(str)

    # Determine chronological order of quarters
    order = (
        qdf[["year", "quarter_num", "quarter"]]
        .drop_duplicates()
        .sort_values(["year", "quarter_num"])
    )
    ordered_quarters = order["quarter"].tolist()

    pivot = qdf.pivot_table(index="tag", columns="quarter", values="value", aggfunc="first")
    pivot = pivot.reindex(columns=ordered_quarters)
    return pivot


def main():
    tickers = load_sp500_tickers()
    ticker_to_cik = load_cik_mapping()

    output = Path("statement_data")
    output.mkdir(exist_ok=True)

    for ticker in tickers:
        cik = ticker_to_cik.get(ticker)
        if not cik:
            print(f"CIK not found for {ticker}")
            continue
        facts = fetch_company_facts(cik)
        if not facts or "facts" not in facts:
            continue
        df = flatten_facts(facts["facts"])
        if df.empty:
            continue
        pivot = pivot_quarterly(df)
        if pivot.empty:
            continue
        pivot.to_excel(output / f"{ticker.upper()}.xlsx")

        df.to_csv(output / f"{ticker.upper()}.csv", index=False)
        print(f"Saved {ticker.upper()} ({cik})")
        time.sleep(0.2)  # be gentle with SEC servers

if __name__ == "__main__":
    main()
