import json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright

KEYWORDS=["Tyler","Gibson","PRS","Fender","Nord","Helix","Quad Cortex","Fractal"]
MIN_PRICE=100000
MAX_PRICE=1000000
STATE=Path("data/seen.json")
RESULT=Path("data/latest.json")
ARAI=("arai kazuki","kazuki arai","新井和輝","アライ カズキ")
ACCESSORIES=("case","bag","gig bag","hard case","soft case","cover","stand","cable","strap","ケース","バッグ","ギグバッグ","カバー","スタンド","ケーブル","ストラップ")

def norm(s): return re.sub(r"\s+"," ",s or "").strip()

def allowed(keyword,title,price):
    t=title.lower()
    if price is None or not (MIN_PRICE < price < MAX_PRICE): return False
    if any((x in t if not x.isascii() else re.search(r"\b"+re.escape(x)+r"\b", t)) for x in ACCESSORIES): return False
    if keyword=="Fender":
        if any(x in t for x in ARAI): return True
        usa=("fender usa","american ","american professional","american vintage","american original","american standard","custom shop","corona")
        bad=("made in japan","japan","mexico","player","player ii")
        return any(x in t for x in usa) and not any(x in t for x in bad)
    if keyword=="Gibson":
        return "gibson" in t and "epiphone" not in t and "orville" not in t
    return True

def scrape(page,keyword):
    url=f"https://www.digimart.net/search?keywordAnd={quote_plus(keyword)}&sortKey=INITIAL_PUBLIC_DATE_DESC&readCount=50"
    response=page.goto(url,wait_until="domcontentloaded",timeout=60000)
    if response and response.status >= 400:
        raise RuntimeError(f"HTTP {response.status}: {page.url}")
    page.wait_for_timeout(5000)
    # Current /catXX/shopNN/DS.../ and legacy detail URLs both contain a DS ID.
    rows=page.evaluate(r"""() => {
      const idOf = a => (a.getAttribute('href') || '').match(/\/(DS\d+)(?:\/|[?#]|$)/)?.[1];
      const groups = new Map();
      for (const a of document.querySelectorAll('a[href*="DS"]')) {
        const id = idOf(a);
        if (!id || !a.getClientRects().length) continue;
        if (!groups.has(id)) groups.set(id, []);
        groups.get(id).push(a);
      }
      const result = [];
      for (const [id, anchors] of groups) {
        const a = anchors.find(a => a.innerText.trim().length >= 4) || anchors[0];
        let box = a.parentElement, card = null;
        while (box && box !== document.body) {
          const ids = new Set([...box.querySelectorAll('a[href*="DS"]')].map(idOf).filter(Boolean));
          if (ids.size > 1) break;
          const text = box.innerText || '';
          if (/[¥￥]\s*[\d,]+|[\d,]+\s*円/.test(text)) { card = box; break; }
          box = box.parentElement;
        }
        const title = a.innerText.trim() || a.getAttribute('title') ||
          anchors.map(a => a.querySelector('img')?.getAttribute('alt')).find(Boolean) || '';
        result.push({id, title, url:a.href, text:card ? card.innerText : ''});
      }
      return result;
    }""")
    if not rows:
        sample=norm(page.locator("body").inner_text())[:500]
        raise RuntimeError(f"No product links found; title={page.title()!r}; page={sample}")
    out=[]; parsed=0
    for row in rows:
        text=norm(row["text"])
        pm=re.search(r"[¥￥]\s*([\d,]+)|([\d,]+)\s*円",text)
        if not pm: continue
        price=int((pm.group(1) or pm.group(2)).replace(",",""))
        title=norm(row["title"])
        if not title: continue
        parsed+=1
        if allowed(keyword,title,price):
            out.append({"id":row["id"],"keyword":keyword,"title":title,"price":price,"url":row["url"]})
    if not parsed:
        raise RuntimeError(f"Found {len(rows)} products but could not parse any title/price")
    stats={"links":len(rows),"parsed":parsed,"qualifying":len(out)}
    print(f"{keyword}: {json.dumps(stats)}",flush=True)
    return out,stats

def main():
    STATE.parent.mkdir(exist_ok=True)
    seen=set(json.loads(STATE.read_text("utf-8"))) if STATE.exists() else set()
    baseline=(not STATE.exists()) or len(seen)==0
    items=[]; errors=[]; counts={}
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True,args=["--no-sandbox"])
        page=b.new_page(locale="ja-JP")
        for k in KEYWORDS:
            try:
                found,counts[k]=scrape(page,k)
                items+=found
            except Exception as e: errors.append(f"{k}: {e}")
        b.close()
    uniq={x["id"]:x for x in items}
    if baseline and not uniq and not errors:
        errors.append("Initial scan found no qualifying products; baseline was not created")
    if errors:
        RESULT.write_text(json.dumps({"status":"failed","checked_at":datetime.now(timezone.utc).isoformat(),"baseline":baseline,"new":[],"errors":errors,"counts":counts},ensure_ascii=False,indent=2),"utf-8")
        raise RuntimeError("\\n".join(errors))
    new=[] if baseline else [x for x in uniq.values() if x["id"] not in seen]
    seen.update(uniq)
    STATE.write_text(json.dumps(sorted(seen),ensure_ascii=False,indent=2),"utf-8")
    RESULT.write_text(json.dumps({"status":"ok","checked_at":datetime.now(timezone.utc).isoformat(),"baseline":baseline,"new":new,"errors":errors,"counts":counts,"collected":len(uniq),"seen_count":len(seen)},ensure_ascii=False,indent=2),"utf-8")
    print("BASELINE_CREATED" if baseline else f"NEW_COUNT={len(new)}")
    for x in new: print(f'[{x["keyword"]}] {x["title"]} | ¥{x["price"]:,} | {x["url"]}')
    if errors: print("ERRORS\n"+"\n".join(errors))

if __name__=="__main__": main()
