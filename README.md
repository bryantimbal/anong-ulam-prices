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
- Only items found in the DA report go into `prices.json`, plus any prices you changed in `manual-prices.json`. The app keeps its own estimates for everything else.
- If DA's site or PDF can't be read, the last DA prices are kept.
- Safety checks: a price must stay within 0.35x–3x of the app's estimate and can't move more than 40% in one run, or the previous value is kept.

## Changing the other prices (manual-prices.json)

Canned goods, sauces, seasonings, noodles and other items DA doesn't track use the app's estimates.
To change one without releasing a new app version:

1. Open `manual-prices.json` on GitHub and click the pencil icon.
2. Change the `"price"` of the item. Prices are per the unit in `"per"`. For `g` and `ml`,
   divide the pack price by its size: a 1 L bottle of soy sauce for ₱95 is `0.095`.
3. Click **Commit changes**. The workflow runs right away and the app picks it up the next time it starts.

A price more than 5x or less than 0.2x of the app's estimate is treated as a typo and skipped.
If the file has a mistake, the last good prices are kept. Either way, a yellow warning appears
on the run in the Actions tab. To undo a change, set the price back to the original number.

## Files

| File | What it is |
|---|---|
| `prices.json` | The feed the app reads |
| `manual-prices.json` | Prices you set by hand for items DA doesn't cover |
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
