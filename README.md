# Anong Ulam? price feed

Daily market prices for the Anong Ulam? app, built from the Department of Agriculture's
[Daily Price Index](https://www.da.gov.ph/price-monitoring/) for NCR wet markets.

The app downloads:

```
https://raw.githubusercontent.com/bryantimbal/anong-ulam-prices/main/prices.json
```

## How it works

- `.github/workflows/update-prices.yml` runs twice a day and on demand (Actions tab → Update prices → Run workflow).
- `scripts/update_prices.py` finds the newest Daily Price Index PDF, reads the table, converts DA's per-kg prices to the units the app uses (per piece, bundle, gram or ml), and writes `prices.json`.
- Only items found in the DA report go into `prices.json`. The app keeps its own estimates for everything else (canned goods, sauces, spices and so on).
- Safety checks: a price must stay within 0.35x–3x of the app's estimate and can't move more than 40% in one run, or the previous value is kept. If DA's site or PDF can't be read, `prices.json` isn't changed.

## Files

| File | What it is |
|---|---|
| `prices.json` | The feed the app reads |
| `estimates.json` | The app's bundled estimates (used for units and sanity checks) |
| `scripts/update_prices.py` | Fetcher and parser. Edit `MAP` to add items or change conversions |

## Test locally

```bash
sudo apt-get install poppler-utils
python3 scripts/update_prices.py                      # downloads from DA
python3 scripts/update_prices.py Daily-Price-Index.pdf  # uses a PDF you already have
```

## DTI

DTI's website refuses automated downloads, so DTI's suggested retail prices
(canned goods, noodles, condiments) aren't fetched. Those items use the app's estimates.
