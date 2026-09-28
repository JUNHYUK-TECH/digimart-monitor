import json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright

KEYWORDS=["Tyler","Gibson","PRS","Fender","Nord","Helix","Quad Cortex","Fractal"]
MIN_PRICE=100000
MAX_PRICE=1000000
STATE=Path("data/yahoo_seen.json")
RESULT=Path("data/yahoo_latest.json")
PAGE_SIZE=50
MAX_PAGES=6

ARAI=("arai kazuki","kazuki arai","新井和輝","アライ カズキ")
ACCESSORY_WORDS=(
    "case","bag","gigbag","gig bag","hardcase","hard case","softcase","soft case",
    "cover","stand","cable","strap","ケース","バッグ","カバー","スタンド",
    "ケーブル","ストラップ","フットコントローラー","foot controller",
)
INSTRUMENT_HINTS=(
    "guitar","bass","stratocaster","telecaster","jazzmaster","jaguar","mustang",
    "precision","jazz bass","les paul","sg ","es-","j-45","j-50","j-200",
    "hummingbird","dove","firebird","explorer","flying v","custom 24","mccarty",
    "silver sky","stage ","electro ","piano","keyboard","synth","helix floor",
    "helix lt","helix rack","helix stadium","quad cortex","axe-fx","axe fx",
    "fm3","fm9","vp4","am4","ギター","ベース","キーボード","シンセ",
)

def norm(s):
    return re.sub(r"\s+"," ",s or "").strip()

def accessory_only(title):
    t=norm(title).lower()
    if not any(x in t for x in ACCESSORY_WORDS):
        return False
    return not any(x in t for x in INSTRUMENT_HINTS)

def allowed(keyword,title,price):
    t=norm(title).lower()
    if price is None or not (MIN_PRICE < price < MAX_PRICE):
        return False
    if accessory_only(title):
        return False

    if keyword=="Tyler":
        return bool(re.search(r"\b(?:james\s+)?tyler\b",t))
    if keyword=="Gibson":
        return "gibson" in t and not any(x in t for x in ("epiphone","orville"))
    if keyword=="PRS":
        return bool(re.search(r"\bprs\b|paul\s+reed\s+smith",t))
    if keyword=="Fender":
        if "fender" not in t:
            return False
        if any(x in t for x in ARAI):
            return True
        usa=(
            "fender usa","fender u.s.a","made in usa","made in u.s.a",
            "american ","american professional","american vintage",
            "american original","american standard","american ultra",
            "american performer","custom shop","masterbuilt","master built",
            "team built","corona","avri","highway one","highway 1",
        )
        non_usa=(
            "made in japan","made in mexico","japan","mexico","mij","mim",
            "player","player ii","vintera","traditional","hybrid ii",
            "jv modified","junior collection",
        )
        return any(x in t for x in usa) and not any(x in t for x in non_usa)
    if keyword=="Nord":
        return "nord" in t or "clavia" in t
    if keyword=="Helix":
        return "helix" in t and ("line 6" in t or "line6" in t)
    if keyword=="Quad Cortex":
        return ("quad cortex" in t) or ("quad" in t and "cortex" in t)
    if keyword=="Fractal":
        return ("fractal" in t or "axe-fx" in t or "axe fx" in t or
                bool(re.search(r"\bfm[39]\b|\bvp4\b|\bam4\b",t)))
    return False

def extract_rows(page):
    return page.evaluate(r"""() => {
      const idOf = a => {
        try {
          const u = new URL(a.getAttribute('href'), location.href);
          const m = u.pathname.match(/\/jp\/auction\/([^/?#]+)/);
          return m ? m[1] : null;
        } catch (_) { return null; }
      };
      const groups = new Map();
      for (const a of document.querySelectorAll('a[href*="/jp/auction/"]')) {
        const id=idOf(a);
        if (!id || !a.getClientRects().length) continue;
        if (!groups.has(id)) groups.set(id,[]);
        groups.get(id).push(a);
      }
      const out=[];
      for (const [id,anchors] of groups) {
        const a=anchors.find(x => (x.innerText||'').trim().length >= 5) || anchors[0];
        let box=a.parentElement, card=null;
        while (box && box!==document.body) {
          const ids=new Set([...box.querySelectorAll('a[href*="/jp/auction/"]')].map(idOf).filter(Boolean));
          if (ids.size>1) break;
          const text=box.innerText||'';
          if (/([\d,]+)\s*円/.test(text)) { card=box; break; }
          box=box.parentElement;
        }
        const imgAlt=anchors.map(x=>x.querySelector('img')?.getAttribute('alt')).find(Boolean)||'';
        let title=(a.innerText||a.getAttribute('aria-label')||a.getAttribute('title')||imgAlt||'').trim();
        title=title.replace(/_サムネイル画像\d+$/,'').replace(/_画像\d+$/,'').trim();
        let href='';
        try { href=new URL(a.getAttribute('href'),location.href).href; } catch (_) {}
        out.push({id,title,url:href,text:card ? card.innerText : ''});
      }
      return out;
    }""")

def parse_price(text):
    text=norm(text)
    # Prefer the current auction price, then buy-it-now, then any visible yen price.
    for pat in (
        r"(?:現在|現在価格)\s*[:：]?\s*([\d,]+)\s*円",
        r"(?:即決|即決価格)\s*[:：]?\s*([\d,]+)\s*円",
        r"([\d,]+)\s*円",
    ):
        m=re.search(pat,text)
        if m:
            return int(m.group(1).replace(",",""))
    return None

def parse_buyout(text):
    m=re.search(r"(?:即決|即決価格)\s*[:：]?\s*([\d,]+)\s*円",norm(text))
    return int(m.group(1).replace(",","")) if m else None

def parse_end(text):
    t=norm(text)
    for pat in (
        r"(\d{1,2}月\d{1,2}日[^ ]*\s*\d{1,2}時\d{1,2}分)",
        r"(\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2})",
    ):
        m=re.search(pat,t)
        if m:
            return m.group(1)
    return None

def scrape(page,keyword):
    rows_by_id={}
    stats=[]

    for page_no in range(1,MAX_PAGES+1):
        # Yahoo Auctions uses b=1, 51, 101... as the result offset even
        # though the redesigned UI may render the "next" control as #dummy.
        offset=1+(page_no-1)*PAGE_SIZE
        url=(
            "https://auctions.yahoo.co.jp/search/search"
            f"?p={quote_plus(keyword)}&b={offset}&n={PAGE_SIZE}&s1=new&o1=d"
        )
        response=page.goto(url,wait_until="domcontentloaded",timeout=60000)
        if response and response.status>=400:
            raise RuntimeError(f"HTTP {response.status}: {page.url}")
        page.wait_for_timeout(3500)

        rows=extract_rows(page)
        if not rows:
            if page_no==1:
                sample=norm(page.locator("body").inner_text())[:700]
                raise RuntimeError(f"No auction links found; title={page.title()!r}; page={sample}")
            break

        before=len(rows_by_id)
        for row in rows:
            rows_by_id[row["id"]]=row
        added=len(rows_by_id)-before
        stats.append({"page":page_no,"url":page.url,"links":len(rows),"unique_added":added})

        # No newly visible Auction IDs means the requested offset was ignored
        # or we reached the end of the result set.
        if added==0:
            break
        if len(rows)<PAGE_SIZE:
            break

    parsed=0
    qualified=[]
    for row in rows_by_id.values():
        title=norm(row["title"])
        if not title:
            continue
        price=parse_price(row["text"])
        if price is None:
            continue
        parsed+=1
        if allowed(keyword,title,price):
            qualified.append({
                "id":row["id"],
                "keyword":keyword,
                "title":title,
                "price":price,
                "buyout":parse_buyout(row["text"]),
                "end":parse_end(row["text"]),
                "url":row["url"],
            })

    if not parsed:
        raise RuntimeError(f"Found {len(rows_by_id)} auction links but parsed no prices")

    info={"pages":len(stats),"links":len(rows_by_id),"parsed":parsed,"qualifying":len(qualified),"page_stats":stats}
    print(f"{keyword}: {json.dumps(info,ensure_ascii=False)}",flush=True)
    return qualified,info

def main():
    STATE.parent.mkdir(exist_ok=True)
    seen=set(json.loads(STATE.read_text("utf-8"))) if STATE.exists() else set()
    baseline=(not STATE.exists()) or len(seen)==0
    items=[]; errors=[]; counts={}

    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
        page=browser.new_page(locale="ja-JP",timezone_id="Asia/Tokyo")
        for keyword in KEYWORDS:
            try:
                found,counts[keyword]=scrape(page,keyword)
                items.extend(found)
            except Exception as e:
                errors.append(f"{keyword}: {e}")
        browser.close()

    uniq={x["id"]:x for x in items}
    if errors:
        RESULT.write_text(json.dumps({
            "status":"failed","checked_at":datetime.now(timezone.utc).isoformat(),
            "baseline":baseline,"new":[],"errors":errors,"counts":counts
        },ensure_ascii=False,indent=2),"utf-8")
        raise RuntimeError("\n".join(errors))

    new=[] if baseline else [x for x in uniq.values() if x["id"] not in seen]
    seen.update(uniq)
    STATE.write_text(json.dumps(sorted(seen),ensure_ascii=False,indent=2),"utf-8")
    RESULT.write_text(json.dumps({
        "status":"ok","checked_at":datetime.now(timezone.utc).isoformat(),
        "baseline":baseline,"new":new,"errors":[],"counts":counts,
        "collected":len(uniq),"seen_count":len(seen)
    },ensure_ascii=False,indent=2),"utf-8")

    print("BASELINE_CREATED" if baseline else f"NEW_COUNT={len(new)}")
    for x in new:
        extra=[]
        if x.get("buyout"): extra.append(f'즉결 ¥{x["buyout"]:,}')
        if x.get("end"): extra.append(f'종료 {x["end"]}')
        suffix=(" | "+" | ".join(extra)) if extra else ""
        print(f'[{x["keyword"]}] {x["title"]} | ¥{x["price"]:,}{suffix} | {x["url"]}')

if __name__=="__main__":
    main()
