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

# Scan multiple newest-first result pages.  PAGE_SIZE is what Digimart is
# asked to render; MAX_PAGES caps work even if the site exposes many pages.
PAGE_SIZE=50
MAX_PAGES=6

ARAI=("arai kazuki","kazuki arai","新井和輝","アライ カズキ")
ACCESSORY_PHRASES=(
    "gig bag","gigbag","hard case","hardcase","soft case","softcase",
    "carry case","carrying case","carrying bag","case only","bag only",
    "ギグバッグ","ギグケース","ハードケース","ソフトケース","キャリングケース",
    "キャリングバッグ","ケースのみ","バッグのみ","専用ケース","専用バッグ",
)
INSTRUMENT_HINTS=(
    "guitar","bass","stratocaster","telecaster","jazzmaster","jaguar","mustang",
    "precision","jazz bass","les paul","sg ","es-","j-45","j-50","j-200",
    "hummingbird","dove","firebird","explorer","flying v","custom 24","mccarty",
    "silver sky","stage ","piano","keyboard","synth","helix","quad cortex",
    "axe-fx","axe fx","fm3","fm9","vp4","am4","ギター","ベース","キーボード",
)

def norm(s):
    return re.sub(r"\s+"," ",s or "").strip()

def looks_accessory_only(title):
    """Reject obvious accessory-only listings, not instruments bundled with a case/bag."""
    t=norm(title).lower()
    if not any(x in t for x in ACCESSORY_PHRASES):
        return False
    if any(x in t for x in INSTRUMENT_HINTS):
        return False

    accessory_nouns=(
        "case","bag","ケース","バッグ","カバー","cover","stand","スタンド",
        "cable","ケーブル","strap","ストラップ",
    )
    return any(x in t for x in accessory_nouns)

def allowed(keyword,title,price):
    t=norm(title).lower()
    if price is None or not (MIN_PRICE < price < MAX_PRICE):
        return False

    # Previously any occurrence of "case"/"bag" rejected the entire listing.
    # That dropped real instruments whose titles merely listed an included case.
    if looks_accessory_only(title):
        return False

    if keyword=="Tyler":
        return bool(re.search(r"\b(?:james\s+)?tyler\b", t))

    if keyword=="PRS":
        return bool(re.search(r"\bprs\b|paul\s+reed\s+smith", t))

    if keyword=="Fender":
        if "fender" not in t:
            return False
        if any(x in t for x in ARAI):
            return True

        # USA-only rule, with additional common US-series wording.
        usa=(
            "fender usa","fender u.s.a","made in usa","made in u.s.a",
            "made in u.s.a.","american ","american professional",
            "american vintage","american original","american standard",
            "american ultra","american performer","custom shop","masterbuilt",
            "master built","team built","corona","avri","highway one","highway 1",
        )
        non_usa=(
            "made in japan","made in mexico","japan","mexico","mij","mim",
            "player","player ii","vintera","traditional","hybrid ii",
            "jv modified","junior collection",
        )
        return any(x in t for x in usa) and not any(x in t for x in non_usa)

    if keyword=="Gibson":
        if "gibson" not in t or any(x in t for x in ("epiphone","orville")):
            return False
        return True

    if keyword=="Nord":
        return "nord" in t or "clavia" in t

    if keyword=="Helix":
        # Avoid unrelated products such as K&K "Double Helix".
        return "helix" in t and ("line 6" in t or "line6" in t)

    if keyword=="Quad Cortex":
        return ("quad cortex" in t) or ("quad" in t and "cortex" in t)

    if keyword=="Fractal":
        return ("fractal" in t or "axe-fx" in t or "axe fx" in t or
                bool(re.search(r"\bfm[39]\b|\bvp4\b|\bam4\b", t)))

    return False

def extract_rows(page):
    return page.evaluate(r"""() => {
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

def find_next_url(page,next_page_number):
    """Follow Digimart's real pagination link instead of guessing its query parameter."""
    return page.evaluate(r"""(nextPage) => {
      const current = new URL(location.href);
      const visible = a => !!a.getClientRects().length;
      const clean = s => (s || '').replace(/\s+/g, ' ').trim();
      const links = [...document.querySelectorAll('a[href]')].filter(visible);

      const sameSearch = a => {
        try {
          const u = new URL(a.getAttribute('href'), location.href);
          return u.origin === current.origin && u.pathname === current.pathname;
        } catch (_) {
          return false;
        }
      };

      // Prefer semantic/visible "next" controls.
      for (const a of links) {
        if (!sameSearch(a)) continue;
        const rel = clean(a.getAttribute('rel')).toLowerCase().split(' ');
        const label = clean([
          a.innerText,
          a.getAttribute('aria-label'),
          a.getAttribute('title')
        ].filter(Boolean).join(' '));
        if (rel.includes('next') ||
            /^(次へ|次のページ|次|next|next page|›|»|＞|>|→)$/i.test(label)) {
          return new URL(a.getAttribute('href'), location.href).href;
        }
      }

      // Robust fallback: use the numeric link for the page we actually want.
      // This works even if Digimart changes ?page= to another parameter name.
      const target = String(nextPage);
      for (const a of links) {
        if (!sameSearch(a)) continue;
        if (clean(a.innerText) === target) {
          return new URL(a.getAttribute('href'), location.href).href;
        }
      }
      return null;
    }""",next_page_number)

def scrape(page,keyword):
    url=f"https://www.digimart.net/search?keywordAnd={quote_plus(keyword)}&sortKey=INITIAL_PUBLIC_DATE_DESC&readCount={PAGE_SIZE}"
    all_rows={}
    page_stats=[]
    visited=set()

    for page_no in range(1,MAX_PAGES+1):
        if url in visited:
            break
        visited.add(url)

        response=page.goto(url,wait_until="domcontentloaded",timeout=60000)
        if response and response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}: {page.url}")
        page.wait_for_timeout(5000)
        rows=extract_rows(page)

        if not rows:
            if page_no==1:
                sample=norm(page.locator("body").inner_text())[:500]
                raise RuntimeError(f"No product links found; title={page.title()!r}; page={sample}")
            break

        before=len(all_rows)
        for row in rows:
            all_rows[row["id"]]=row
        added=len(all_rows)-before
        page_stats.append({
            "page":page_no,
            "url":page.url,
            "links":len(rows),
            "unique_added":added,
        })

        # A repeated result set means pagination did not advance.
        if added==0:
            break

        if page_no >= MAX_PAGES:
            break
        next_url=find_next_url(page,page_no+1)
        if not next_url or next_url in visited:
            break
        url=next_url

    out=[]; parsed=0
    for row in all_rows.values():
        text=norm(row["text"])
        pm=re.search(r"[¥￥]\s*([\d,]+)|([\d,]+)\s*円",text)
        if not pm:
            continue
        price=int((pm.group(1) or pm.group(2)).replace(",",""))
        title=norm(row["title"])
        if not title:
            continue
        parsed+=1
        if allowed(keyword,title,price):
            out.append({
                "id":row["id"],
                "keyword":keyword,
                "title":title,
                "price":price,
                "url":row["url"],
            })

    if not parsed:
        raise RuntimeError(f"Found {len(all_rows)} products but could not parse any title/price")

    stats={
        "pages":len(page_stats),
        "links":len(all_rows),
        "parsed":parsed,
        "qualifying":len(out),
        "page_stats":page_stats,
    }
    print(f"{keyword}: {json.dumps(stats,ensure_ascii=False)}",flush=True)
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
            except Exception as e:
                errors.append(f"{k}: {e}")
        b.close()

    uniq={x["id"]:x for x in items}
    if baseline and not uniq and not errors:
        errors.append("Initial scan found no qualifying products; baseline was not created")

    if errors:
        RESULT.write_text(json.dumps({
            "status":"failed",
            "checked_at":datetime.now(timezone.utc).isoformat(),
            "baseline":baseline,
            "new":[],
            "errors":errors,
            "counts":counts,
        },ensure_ascii=False,indent=2),"utf-8")
        raise RuntimeError("\n".join(errors))

    new=[] if baseline else [x for x in uniq.values() if x["id"] not in seen]
    seen.update(uniq)
    STATE.write_text(json.dumps(sorted(seen),ensure_ascii=False,indent=2),"utf-8")
    RESULT.write_text(json.dumps({
        "status":"ok",
        "checked_at":datetime.now(timezone.utc).isoformat(),
        "baseline":baseline,
        "new":new,
        "errors":errors,
        "counts":counts,
        "collected":len(uniq),
        "seen_count":len(seen),
    },ensure_ascii=False,indent=2),"utf-8")

    print("BASELINE_CREATED" if baseline else f"NEW_COUNT={len(new)}")
    for x in new:
        print(f'[{x["keyword"]}] {x["title"]} | ¥{x["price"]:,} | {x["url"]}')
    if errors:
        print("ERRORS\n"+"\n".join(errors))

if __name__=="__main__":
    main()
