# aaaaa

This repository contains a helper script for downloading SEC EDGAR company facts
for the S&P 500 constituents. The script `download_sp500_companyfacts.py` pulls
the full set of US GAAP facts for each company and stores a quarterly pivot
table as an Excel workbook under the `statement_data` directory.

## Usage

```bash
pip install -r requirements.txt
python download_sp500_companyfacts.py
```

The script may take a long time to complete because it fetches data for every
company. Files are stored as `<TICKER>.xlsx` in `statement_data/`.
