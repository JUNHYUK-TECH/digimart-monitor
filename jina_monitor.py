#!/usr/bin/env python3
"""Free hourly Digimart scan through the public Jina Reader endpoint.

Requires internet, Python stdlib, and the existing monitor.py filter module.
Does not run Playwright or change the previous seen IDs on failure.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from monitor import KEYWORDS, allowed

DATA = Path("data")
SEEN_FILE = DATA / "seen.json"
LATEST_FILE = DATA / "latest.json"
INITIALIZED_FILE = DATA / "jina_initialized.json"
PAGE_SIZE = 100

ID_PATTERN = re.compile(r"商品ID：\s*(DS\d{6,})")
PRODUCT_LINK = re.compile(
    r"^\[([^\n]+)\]\((https://www\.digimart\.net/(?:cat\d+/)?shop\d+/DS\d+/?)(?:\?[^)]*)?\)",
    re.MULTILINE,
)
YEN = re.compile(r"[¥￥]\s*([\d,]+)")
TAX_INCLUDED = re.compile(r"[¥￥]\s*([\d,]+)\s*税込")


def make_url():
    # Digimart supports AND/OR search operators. Bound by price server-side.
    terms = " OR ".join(KEYWORDS)
    source = (
        "https://www.digimart.net/search"
        f"?keywordAnd={quote_plus(terms)}"
        "&sortKey=INITIAL_PUBLIC_DATE_DESC"
        f"&readCount={PAGE_SIZE}&priceFrom=100001&priceTo=999999"
    )
    return "https://r.jina.ai/" + source


def fetch_text():
    url = make_url()
    request = Request(url, headers={
        "User-Agent": "Digimart-Monitor/1.0",
        "Accept": "text/plain",
        "X-No-Cache": "true",
    })
    try:
        with urlopen(request, timeout=100) as response:
            text = response.read(4_000_001).decode("utf-8", "replace")
            if len(text) > 4_000_000:
                raise RuntimeError("Reader response exceeded size limit")
    except (HTTPError, URLError, TimeoutError) as e:
        raise RuntimeError(f"Reader unavailable: {e}") from e

    # Fail closed if Reader returned a challenge/error instead of listings.
    if "商品ID：" not in text or "digimart.net" not in text:
        raise RuntimeError("Reader returned no Digimart listing IDs")
    return text


def extract_rows(text):
    """Return (rows, total ID markers); each card ends at the next marker."""
    markers = list(ID_PATTERN.finditer(text))
    rows = {}
    for i, marker in enumerate(markers):
        item_id = marker.group(1)
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        card = text[marker.end():end]
        match = PRODUCT_LINK.search(card)
        if match is None or item_id not in match.group(2):
            continue

        # The actual selling price precedes 税込; it may follow a
        # "通常:¥..." (original-price) value.
        prices = TAX_INCLUDED.findall(card)
        if not prices:
            prices = YEN.findall(card)
        if not prices:
            continue

        title = re.sub(r"\s+", " ", match.group(1)).strip()
        price = int(prices[-1].replace(",", ""))
        rows[item_id] = {
            "id": item_id, "title": title, "price": price, "url": match.group(2)
        }
    return list(rows.values()), len(markers)


def filter_rows(rows):
    matched = []
    for row in rows:
        for keyword in KEYWORDS:
            if allowed(keyword, row["title"], row["price"]):
                matched.append({**row, "keyword": keyword})
                break  # Deduplicate products matching multiple search terms.
    return matched


def run(diagnostic=False):
    text = fetch_text()
    rows, total = extract_rows(text)
    if total < 10 or len(rows) < total * 0.85:
        raise RuntimeError(
            f"Unexpected results: {total} product IDs, {len(rows)} parsed. "
            "No monitoring state changed."
        )
    matches = filter_rows(rows)
    now = datetime.now(timezone.utc).isoformat()
    if diagnostic:
        print(json.dumps({
            "diagnostic": True, "status": "ok",
            "total_product_ids": total, "parsed": len(rows),
            "qualifying": len(matches),
            "sample": matches[:5],
        }, ensure_ascii=False, indent=2))
        return

    DATA.mkdir(exist_ok=True)
    seen = set(json.loads(SEEN_FILE.read_text("utf-8"))) if SEEN_FILE.exists() else set()
    initialized = INITIALIZED_FILE.exists()
    new = [item for item in matches if item["id"] not in seen] if initialized else []

    # First successful cloud run is a no-alert baseline, even if older
    # Playwright state exists; never flood the user with old items.
    seen.update(item["id"] for item in matches)
    latest = {
        "status": "ok", "source": "jina_reader", "checked_at": now,
        "last_attempt_at": now, "last_success_at": now,
        "baseline": not initialized, "new": new, "errors": [],
        "counts": {"combined": {
            "product_ids": total, "parsed": len(rows), "qualifying": len(matches)
        }}, "collected": len(matches), "seen_count": len(seen),
    }
    SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2), encoding="utf-8")
    LATEST_FILE.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    if not initialized:
        INITIALIZED_FILE.write_text(
            json.dumps({"source": "jina_reader", "initialized_at": now}, indent=2),
            encoding="utf-8",
        )

    print("BASELINE_CREATED" if not initialized else f"NEW_COUNT={len(new)}")
    print(f"Product IDs: {total}; Parsed: {len(rows)}; Matched: {len(matches)}")
    for item in new:
        print(f'[{item["keyword"]}] {item["title"]} | ¥{item["price"]:,} | {item["url"]}')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    try:
        run(diagnostic=args.diagnostic)
    except Exception as exc:
        print(f"MONITOR_ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
