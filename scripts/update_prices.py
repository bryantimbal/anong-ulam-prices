#!/usr/bin/env python3
"""Builds prices.json for the Anong Ulam? app from official government price data.

Source: Department of Agriculture (DA) Daily Price Index, NCR wet markets
(https://www.da.gov.ph/price-monitoring/). Prices there are per kg (eggs per piece,
oil per liter); they are converted to the app's units (pc, bundle, g, ml) below.

Safety rules:
  * Only items found in the latest DA report are written. Every other item keeps
    the app's bundled estimate (the app merges the feed over its own prices).
  * A converted price must stay within 0.35x-3x of the bundled estimate, and may not
    move more than 40% from the previous feed in one run. Otherwise the previous
    value is kept.
  * If DA can't be downloaded or parsed, the last DA prices are kept.
  * manual-prices.json lets the owner change any non-DA price without an app update.
"""
from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "prices.json"
ESTIMATES = ROOT / "estimates.json"
MANUAL = ROOT / "manual-prices.json"
DA_INDEX = "https://www.da.gov.ph/price-monitoring/"
UA = "AnongUlamPriceFeed/1.0"
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}

# app id -> (DA section, commodity starts with, spec contains or None, factor, rounding)
# price_in_app_unit = DA price per kg (or per pc / per liter) * factor
MAP: dict[str, tuple[str, str, str | None, float, float]] = {
    # meat (per kg)
    "chicken":          ("CHICKEN", "Whole Chicken, Unbranded", None, 1, 1),
    "chicken_breast":   ("CHICKEN", "Breast (Pecho), Unbranded", None, 1, 1),
    "chicken_wings":    ("CHICKEN", "Wings (Pakpak), Unbranded", None, 1, 1),
    "chicken_liver":    ("CHICKEN OFFALS", "Liver (Atay), Local", None, 1, 1),
    "pork_kasim":       ("PORK", "Picnic Shoulder (Kasim), Local", None, 1, 1),
    "pork_liempo":      ("PORK", "Belly (Liempo), Local", None, 1, 1),
    "lechon_belly":     ("PORK", "Belly (Liempo), Local", None, 1, 1),
    "pork_ribs":        ("PORK", "Spare Ribs, Local", None, 1, 1),
    "pork_chop":        ("PORK", "Chop, Local", None, 1, 1),
    "pork_pata":        ("PORK", "Hind Shank (Pata Hulihan), Local", None, 1, 1),
    "pork_liver":       ("PORK OFFALS", "Liver (Atay), Local", None, 1, 1),
    "pork_maskara":     ("PORK OFFALS", "Head Mask, Local", None, 1, 1),
    "pork_innards":     ("PORK OFFALS", "Small Intestine, Local", None, 1, 1),
    "beef_sirloin":     ("BEEF", "Sirloin (Lomo), Local", None, 1, 1),
    "beef_brisket":     ("BEEF", "Brisket (Punta y Pecho), Local", None, 1, 1),
    "beef_ribs":        ("BEEF", "Short Ribs, Local", None, 1, 1),
    "beef_tripe":       ("BEEF OFFALS", "Honeycomb Tripe (Reticulum)/Tuwalya, Local", None, 1, 1),
    # seafood (per kg)
    "galunggong":       ("FISHERIES AND SEAFOOD", "Roundscad (Galunggong), Local", None, 1, 1),
    "bangus":           ("FISHERIES AND SEAFOOD", "Milkfish (Bangus)", "Medium", 1, 1),
    "tilapia":          ("FISHERIES AND SEAFOOD", "Tilapia", None, 1, 1),
    "tuna":             ("FISHERIES AND SEAFOOD", "Yellow-Fin Tuna (Tambakol), Local", None, 1, 1),
    "pusit":            ("FISHERIES AND SEAFOOD", "Squid (Pusit Bisaya), Local", None, 1, 1),
    "shrimp":           ("FISHERIES AND SEAFOOD", "Suahe (White Shrimp), Local", None, 1, 1),
    "tamban":           ("FISHERIES AND SEAFOOD", "Sardines (Tamban), Local", None, 1, 1),
    "cream_dory":       ("FISHERIES AND SEAFOOD", "Cream Dory (Pangasius) Fillet", None, 1, 1),
    # vegetables: per kg, or converted with an average weight per piece/bundle
    "squash":           ("LOWLAND VEGETABLES", "Squash", None, 1, 1),
    "ampalaya":         ("LOWLAND VEGETABLES", "Bitter Gourd (Ampalaya)", None, 1 / 4.5, 1),   # 4-5 pcs/kg
    "upo":              ("LOWLAND VEGETABLES", "Bottle Gourd (Upo)", None, 0.8, 1),          # ~800 g each
    "siling_haba":      ("LOWLAND VEGETABLES", "Chilli (Green), Local", None, 0.015, 0.5),   # ~15 g each
    "eggplant":         ("LOWLAND VEGETABLES", "Eggplant", None, 0.125, 1),                  # ~125 g each
    "pechay":           ("LOWLAND VEGETABLES", "Native Pechay", None, 1 / 3.5, 1),           # 3-4 bundles/kg
    "okra":             ("LOWLAND VEGETABLES", "Okra", None, 0.025, 0.5),                    # ~25 g each
    "sitaw":            ("LOWLAND VEGETABLES", "Pole Sitao", None, 1 / 3.5, 1),              # 3-4 bundles/kg
    "patola":           ("LOWLAND VEGETABLES", "Sponge Gourd (Patola)", None, 0.35, 1),      # ~350 g each
    "tomato":           ("LOWLAND VEGETABLES", "Tomato", None, 1 / 16.5, 0.5),               # 15-18 pcs/kg
    "cabbage":          ("HIGHLAND VEGETABLES", "Cabbage (Scorpio), Local", None, 1, 1),
    "carrot":           ("HIGHLAND VEGETABLES", "Carrots, Local", None, 1, 1),
    "broccoli":         ("HIGHLAND VEGETABLES", "Broccoli, Imported", None, 1, 1),
    "cauliflower":      ("HIGHLAND VEGETABLES", "Cauliflower, Local", None, 1, 1),
    "sayote":           ("HIGHLAND VEGETABLES", "Chayote, Local", None, 0.35, 1),            # 301-400 g each
    "cucumber":         ("HIGHLAND VEGETABLES", "Cucumber (Highland), Local", None, 0.25, 1),
    "baguio_beans":     ("HIGHLAND VEGETABLES", "Habichuelas/Baguio Beans, Local", None, 1, 1),
    "lettuce":          ("HIGHLAND VEGETABLES", "Lettuce (Romaine), Local", None, 0.25, 1),  # ~250 g bundle
    "radish":           ("HIGHLAND VEGETABLES", "Radish, Local", None, 0.25, 1),             # ~250 g each
    "potato":           ("HIGHLAND VEGETABLES", "White Potato, Local", None, 1, 1),
    "bell_pepper":      ("HIGHLAND VEGETABLES", "Bell Pepper (Green), Local", None, 0.2, 1),  # 151-250 g each
    # spices
    "garlic":           ("SPICES", "Garlic, Imported", None, 0.04, 0.5),                     # ~40 g head
    "ginger":           ("SPICES", "Ginger, Imported", None, 0.04, 0.5),                     # ~40 g knob
    "onion":            ("SPICES", "Red Onion, Local", "Medium", 1 / 14, 0.5),               # 13-15 pcs/kg
    # fruits / root crops
    "calamansi":        ("FRUITS", "Calamansi", None, 0.015, 0.25),                          # ~15 g each
    "saba":             ("FRUITS", "Banana (Saba)", None, 1 / 8.5, 0.5),                     # 7-10 pcs/kg
    "orange":           ("FRUITS", "Orange", None, 0.2, 1),
    "lemon":            ("FRUITS", "Lemon", None, 0.12, 1),
    "kamote":           ("ROOTCROPS", "Sweet Potato (Yellow)", None, 1, 1),
    # staples
    "rice":             ("LOCAL COMMERCIAL RICE", "Well Milled", None, 1, 1),
    "glutinous_rice":   ("LOCAL COMMERCIAL RICE", "Glutinous", None, 1, 1),
    "basmati":          ("IMPORTED COMMERCIAL RICE", "Basmati", None, 1, 1),
    "monggo":           ("LEGUMES", "Mungbean", None, 1, 1),
    "egg":              ("EGG", "Chicken Egg (White, Medium)", None, 1, 0.25),
    "sugar":            ("OTHER BASIC COMMODITIES", "Sugar (Refined)", None, 0.001, 0.001),  # per g
    "brown_sugar":      ("OTHER BASIC COMMODITIES", "Sugar (Brown)", None, 0.001, 0.001),
    "salt":             ("OTHER BASIC COMMODITIES", "Salt (Iodized)", None, 0.001, 0.001),
    "cooking_oil":      ("OTHER BASIC COMMODITIES", "Cooking Oil (Palm)", None, 0.001, 0.001),  # per ml
}



def log(*a):
    print(*a, file=sys.stderr)


def get(url: str, timeout=60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def date_from_name(url: str) -> dt.date | None:
    name = url.rsplit("/", 1)[-1].lower()
    m = re.search(r"(" + "|".join(MONTHS) + r")-(\d{1,2})-(\d{4})", name)
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
    except ValueError:
        return None


def latest_da_reports(limit=5) -> list[tuple[dt.date, str]]:
    html = get(DA_INDEX).decode("utf-8", "replace")
    links = set(re.findall(r'https://www\.da\.gov\.ph/wp-content/uploads/[^"\'\s<>]+\.pdf', html))
    daily = []
    for u in links:
        n = u.lower()
        if ("daily-price-index" in n or "-dpi" in n) and "weekly" not in n:
            d = date_from_name(u)
            if d:
                daily.append((d, u))
    daily.sort(reverse=True)
    return daily[:limit]


def is_section(text: str) -> bool:
    t = text.strip()
    return bool(t) and not any(c.islower() for c in t) and not re.search(r"\d", t) and len(t) < 40


WORD_RE = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
PRICE_TOKEN = re.compile(r"^(\d{1,5}(?:\.\d+)?|n/a)$")


def _lines(words, tol=2.5):
    """Groups words (x, y, text) into lines by y."""
    out = []
    for x, y, t in sorted(words, key=lambda w: (w[1], w[0])):
        if out and abs(out[-1][0] - y) <= tol:
            out[-1][1].append((x, t))
        else:
            out.append([y, [(x, t)]])
    return [(y, " ".join(t for _, t in sorted(ws))) for y, ws in out]


def parse_dpi(bbox_html: str):
    """Parses `pdftotext -bbox` output of a DA Daily Price Index.

    Table cells wrap and are vertically centred, so every name/spec line is attached
    to the price row nearest to it on the page, never across a section header.
    Returns (report date text, {(section, commodity): [(spec, price), ...]}).
    """
    html = bbox_html
    all_text = " ".join(htmllib.unescape(m[4]) for m in WORD_RE.findall(html))
    m = re.search(r"\(\s*\w+day,\s*([A-Za-z]+ \d{1,2}, \d{4})\s*\)", all_text)
    when = m.group(1) if m else ""
    rows: dict[tuple[str, str], list] = {}
    section = ""
    for page in html.split("<page")[1:]:
        words = [(float(a), float(b), float(c), float(d), htmllib.unescape(t))
                 for a, b, c, d, t in WORD_RE.findall(page)]
        head = {t: (x0, y0) for x0, y0, _, _, t in words if t in ("COMMODITY", "SPECIFICATION", "PREVAILING")}
        if len(head) < 3:
            # pages without the table header (e.g. notes) end the table
            if any(t.startswith("Note(s)") for *_, t in words):
                break
            continue
        split_spec = (head["COMMODITY"][0] + head["SPECIFICATION"][0]) / 2
        split_price = head["PREVAILING"][0] - 15
        top = max(head[k][1] for k in head) + 12
        note_y = min([y0 for _, y0, _, _, t in words if t.startswith("Note(s)")] or [1e9])
        foot = min([y0 for _, y0, _, _, t in words if t == "Page"] or [1e9])
        bottom = min(note_y, foot)
        name_w, spec_w, prices = [], [], []
        for x0, y0, x1, y1, t in words:
            if y0 < top or y0 >= bottom:
                continue
            yc = (y0 + y1) / 2
            if x0 >= split_price:
                if PRICE_TOKEN.match(t):
                    prices.append((yc, None if t == "n/a" else float(t)))
            elif x0 < split_spec:
                name_w.append((x0, yc, t))
            else:
                spec_w.append((x0, yc, t))
        name_lines = _lines(name_w)
        spec_lines = _lines(spec_w)
        # section headers split the page into bands
        headers = [(y, t) for y, t in name_lines if is_section(t)]
        name_lines = [(y, t) for y, t in name_lines if not is_section(t)]
        marks = sorted(headers)
        # merge consecutive header lines ("IMPORTED COMMERCIAL" + "RICE")
        bands, merged = [], []
        for y, t in marks:
            if merged and y - merged[-1][0] < 20 and t in ("RICE", "PRODUCTS"):
                merged[-1] = (y, merged[-1][1] + " " + t)
            else:
                merged.append((y, t))
        def band_of(y):
            sec = section
            for hy, ht in merged:
                if hy <= y:
                    sec = ht
            return sec
        prices.sort()
        cells = {i: ([], []) for i in range(len(prices))}
        for kind, lines in ((0, name_lines), (1, spec_lines)):
            for y, t in lines:
                b = band_of(y)
                cand = [(abs(py - y), py > y, i) for i, (py, _) in enumerate(prices) if band_of(py) == b]
                if not cand:
                    continue
                dist, _, i = min(cand)
                if dist <= 30:
                    cells[i][kind].append((y, t))
        for i, (py, price) in enumerate(prices):
            names, specs = cells[i]
            name = " ".join(t for _, t in sorted(names)).strip()
            spec = " ".join(t for _, t in sorted(specs)).strip()
            if name:
                rows.setdefault((band_of(py), name), []).append((spec, price))
        if merged:
            section = merged[-1][1]
        if note_y < 1e9:
            break
    return when, rows


def find(rows, section, name, spec):
    for (sec, n), entries in rows.items():
        if sec != section or not n.startswith(name):
            continue
        for sp, price in entries:
            if price is not None and (spec is None or spec.lower() in sp.lower()):
                return price
    return None


def round_to(v: float, step: float) -> float:
    r = round(round(v / step) * step, 4)
    return int(r) if r == int(r) and step >= 1 else r


def load_manual(estimates: dict, notes: list, prev_manual: dict[str, float]) -> dict[str, float]:
    """Reads manual-prices.json: {"prices": {"soy_sauce": {"price": 0.10, ...}, ...}}.

    Only entries whose price differs from the app's bundled estimate are used.
    A bad entry keeps its last good manual price; a broken file keeps all of them.
    """
    if not MANUAL.exists():
        return {}
    try:
        data = json.loads(MANUAL.read_text())
    except Exception as e:
        notes.append(f"manual-prices.json is not valid JSON, kept the last manual prices: {e}")
        return dict(prev_manual)
    out = {}
    for app_id, entry in (data.get("prices") or {}).items():
        price = entry.get("price") if isinstance(entry, dict) else entry
        est = estimates.get(app_id)
        if est is None:
            notes.append(f"manual: unknown id {app_id!r}, skipped")
            continue
        if not isinstance(price, (int, float)) or isinstance(price, bool) or price < 0:
            notes.append(f"manual: {app_id} has an invalid price {price!r}, skipped")
            if app_id in prev_manual:
                out[app_id] = prev_manual[app_id]
            continue
        if app_id in MAP:
            notes.append(f"manual: {app_id} comes from DA, manual price ignored")
            continue
        base = est["price"]
        if base > 0 and not (0.2 * base <= price <= 5 * base):
            notes.append(f"manual: {app_id} = {price} is far from the estimate {base} "
                         f"(per {est['unit']}), skipped. Check the unit")
            if app_id in prev_manual:
                out[app_id] = prev_manual[app_id]
            continue
        if price != base:
            out[app_id] = price
    return out


def main() -> int:
    estimates = {i["id"]: i for i in json.loads(ESTIMATES.read_text())["items"]}
    previous, old = {}, {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text())
            previous = {i["id"]: i for i in old["items"]}
        except Exception as e:  # corrupt file: start over from estimates
            log("previous prices.json unreadable:", e)

    def row(app_id, price):
        est = estimates[app_id]
        return {k: est[k] for k in ("id", "name", "english", "section", "unit")} | {"price": price}

    notes: list[str] = []
    da_items, updated, report = None, old.get("updated", ""), old.get("report", "")

    local = sys.argv[1:]  # optional: test with local PDF files instead of downloading
    try:
        reports = [(dt.date.today(), p) for p in local] if local else latest_da_reports()
    except Exception as e:
        log("DA index unavailable:", e)
        reports = []

    when, rows, used = "", {}, None
    with tempfile.TemporaryDirectory() as tmp:
        for d, url in reports:
            try:
                pdf = Path(tmp, "dpi.pdf")
                pdf.write_bytes(Path(url).read_bytes() if local else get(url))
                txt = subprocess.run(["pdftotext", "-bbox", str(pdf), "-"],
                                     capture_output=True, text=True, check=True).stdout
                when, rows = parse_dpi(txt)
                if sum(1 for e in rows.values() for _, p in e if p) >= 50:
                    used = (d, url)
                    break
                log("too few prices in", url)
            except Exception as e:
                log("failed", url, e)

    if used:
        da_items = []
        for app_id, (section, name, spec, factor, step) in MAP.items():
            est = estimates.get(app_id)
            if not est:
                continue
            raw = find(rows, section, name, spec)
            prev = previous.get(app_id)
            value = None
            if raw is not None:
                value = round_to(raw * factor, step)
                base = est["price"]
                if not (0.35 * base <= value <= 3 * base):
                    notes.append(f"{app_id}: {value} outside range of estimate {base}, skipped")
                    value = None
                elif prev and abs(value - prev["price"]) > 0.4 * prev["price"]:
                    notes.append(f"{app_id}: jump {prev['price']} -> {value}, kept previous")
                    value = None
            else:
                notes.append(f"{app_id}: not in report")
            if value is None and prev:
                value = prev["price"]  # keep last good DA value
            if value is not None:
                da_items.append(row(app_id, value))
        try:  # prefer the date printed in the report itself
            report_date = dt.datetime.strptime(when, "%B %d, %Y").date()
        except ValueError:
            report_date = used[0]
        updated, report = report_date.strftime("%b %-d, %Y"), used[1]
    else:
        log("no usable DA report, keeping the last DA prices")
        da_items = [i for i in previous.values() if i["id"] in MAP]

    prev_manual = {k: previous[k]["price"] for k in old.get("manual", []) if k in previous}
    manual = load_manual(estimates, notes, prev_manual)
    items = da_items + [row(k, v) for k, v in manual.items()]
    for n in notes:
        # "::warning::" shows the message on the run's summary page in GitHub Actions
        log(("::warning::" if n.startswith("manual") else "") + n)
    if not items:
        log("nothing to publish")
        return 0

    feed = {
        "updated": updated or dt.date.today().strftime("%b %-d, %Y"),
        "source": "DA Price Monitoring (NCR)",
        "currency": "PHP",
        "report": report,
        "manual": sorted(manual),
        "items": items,
    }
    if old and {k: v for k, v in old.items()} == feed:
        log("no change since last run")
        return 0
    OUT.write_text(json.dumps(feed, ensure_ascii=False, indent=1) + "\n")
    log(f"wrote {len(da_items)} DA prices ({report or 'previous'}) and {len(manual)} manual prices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
