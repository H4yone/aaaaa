# aaaaa

This repository contains a helper script for downloading SEC EDGAR company facts
for the S&P 500 constituents. The script `download_sp500_companyfacts.py` pulls
the full set of US GAAP facts for each company and saves them as CSV files under
the `statement_data` directory.

## Usage

```bash
pip install -r requirements.txt  # install requests and pandas
python download_sp500_companyfacts.py
```

The script may take a long time to complete because it fetches data for every
company. Files are stored as `<TICKER>.csv` in `statement_data/`.
