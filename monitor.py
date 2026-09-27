import json, re
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
    if any(x in t for x in ACCESSORIES): return False
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
    page.goto(url,wait_until="domcontentloaded",timeout=60000)
    page.wait_for_timeout(5000)
    links=page.locator('a[href*="/prd/detail.digital/DS"]')
    out=[]; used=set()
    for i in range(min(links.count(),300)):
        a=links.nth(i); href=a.get_attribute("href") or ""
        m=re.search(r"(DS\d+)",href)
        if not m or m.group(1) in used: continue
        ds=m.group(1); used.add(ds)
        try:
            box=a.locator("xpath=ancestor::*[self::li or self::article or self::div][1]")
            text=norm(box.inner_text(timeout=1000))
        except: text=norm(a.inner_text(timeout=1000))
        title=norm(a.get_attribute("title") or a.inner_text(timeout=1000))
        if len(title)<4:
            lines=[x.strip() for x in text.splitlines() if len(x.strip())>5]
            title=lines[0] if lines else title
        pm=re.search(r"[¥￥]\s*([\d,]+)",text)
        price=int(pm.group(1).replace(",","")) if pm else None
        if allowed(keyword,title,price):
            full=href if href.startswith("http") else "https://www.digimart.net"+href
            out.append({"id":ds,"keyword":keyword,"title":title,"price":price,"url":full})
        if len(used)>=50: break
    return out

def main():
    STATE.parent.mkdir(exist_ok=True)
    seen=set(json.loads(STATE.read_text("utf-8"))) if STATE.exists() else set()
    baseline=(not STATE.exists()) or len(seen)==0
    items=[]; errors=[]
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True,args=["--no-sandbox"])
        page=b.new_page(locale="ja-JP",user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129 Safari/537.36")
        for k in KEYWORDS:
            try: items+=scrape(page,k)
            except Exception as e: errors.append(f"{k}: {e}")
        b.close()
    uniq={x["id"]:x for x in items}
    new=[] if baseline else [x for x in uniq.values() if x["id"] not in seen]
    seen.update(uniq)
    STATE.write_text(json.dumps(sorted(seen),ensure_ascii=False,indent=2),"utf-8")
    RESULT.write_text(json.dumps({"baseline":baseline,"new":new,"errors":errors},ensure_ascii=False,indent=2),"utf-8")
    print("BASELINE_CREATED" if baseline else f"NEW_COUNT={len(new)}")
    for x in new: print(f'[{x["keyword"]}] {x["title"]} | ¥{x["price"]:,} | {x["url"]}')
    if errors: print("ERRORS\n"+"\n".join(errors))

if __name__=="__main__": main()
