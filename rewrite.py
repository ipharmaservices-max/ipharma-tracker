import json, os, re, time, datetime, pathlib, html
import requests
from bs4 import BeautifulSoup

KEY = os.environ["GEMINI_API_KEY"]
MODEL = "gemini-2.5-flash"      # if you get a "model not found" error, see the note below
MAX_ARTICLES = 8                # rewrites per day
MIN_SCORE = 7                   # importance cut-off (1-10)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36"}

SGT = datetime.timezone(datetime.timedelta(hours=8))
today = datetime.datetime.now(SGT).date().isoformat()

def load(name, default):
    p = pathlib.Path(name)
    return json.load(open(p, encoding="utf-8")) if p.exists() else default

history = load("history.json", [])
done = set(load("processed.json", []))
drafts = load("drafts.json", [])

def gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4}}
    for attempt in range(4):
        r = requests.post(url, headers={"x-goog-api-key": KEY}, json=body, timeout=180)
        if r.status_code == 200:
            try:
                return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            except Exception:
                pass
        else:
            print("Gemini error", r.status_code, r.text[:200])
        time.sleep(20 * (attempt + 1))
    return None

def grams(text, n=5):
    w = re.findall(r"\w+", text.lower())
    return {" ".join(w[i:i+n]) for i in range(len(w) - n + 1)}

def overlap(source, article):
    a = grams(article)
    return len(a & grams(source)) / len(a) if a else 0

def fetch_text(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            t.decompose()
        text = "\n".join(p.get_text(" ", strip=True) for p in soup.find_all(["p", "li"])
                         if len(p.get_text(strip=True)) > 40)
        return text[:12000]
    except Exception as e:
        print("fetch failed", url, e)
        return ""

new = [h for h in history if h["date"] == today and h["url"] not in done]
print(len(new), "new links to look at")

# ---------- Step 3: importance scoring (batches) ----------
keep = []
for i in range(0, len(new), 40):
    batch = new[i:i+40]
    lines = "\n".join(f"{j}. [{b['site']}] {b['title']}" for j, b in enumerate(batch))
    prompt = ("You are an editor of a pharma and healthcare news website for industry professionals. "
              "Score each link title from 1 to 10 for newsworthiness. High (7-10): drug approvals, "
              "clinical trial results, safety alerts or recalls, regulatory decisions, pricing or policy "
              "changes, major deals, important company announcements. Low (1-3): menu items, careers, "
              "about-us, events, generic pages, marketing, duplicate navigation links. "
              'Return JSON only: [{"id": 0, "score": 8}, ...]\n\n' + lines)
    res = gemini(prompt) or []
    scores = {r.get("id"): r.get("score", 0) for r in res if isinstance(r, dict)}
    for j, b in enumerate(batch):
        b["score"] = scores.get(j, 0)
        if b["score"] >= MIN_SCORE:
            keep.append(b)
    time.sleep(8)

keep.sort(key=lambda x: -x["score"])
keep = keep[:MAX_ARTICLES]
print(len(keep), "important articles to rewrite")

# ---------- Step 4: rewrite + SEO + social ----------
def write_prompt(src, extra=""):
    return f"""You are a senior pharma and healthcare journalist writing for iPharmaCenter.
Read the SOURCE text and write an ORIGINAL news article for our readers.

Rules:
- 400 to 600 words. Use your own wording and your own structure. Never copy sentences or long phrases.
- Keep every fact, name, number, dose and date exactly correct. Do NOT invent facts or quotes.
- Structure: a clear headline, a short summary paragraph, 2-3 sections with h2 headings, and a section
  titled "Why this matters" with brief context for pharma professionals (clearly analysis, no new claims).
- End with a short sentence crediting the original source.
- If the source is not really a news item, return {{"skip": true}}.
{extra}
Return JSON only with these keys:
"title" (max 65 characters, SEO-friendly), "meta_description" (max 155 characters),
"slug" (lowercase-words-with-hyphens), "tags" (list of 5 short tags),
"article_html" (HTML using only h2, p, ul, li tags), "linkedin_post" (professional, 3-5 lines, 3 hashtags),
"x_post" (max 250 characters, 2 hashtags).

SOURCE:
{src}"""

def plain(h):
    return re.sub(r"<[^>]+>", " ", h)

for item in keep:
    done.add(item["url"])
    src = fetch_text(item["url"])
    if len(src) < 800:
        print("skipped (could not read)", item["url"])
        continue
    out = gemini(write_prompt(src))
    if not out or out.get("skip"):
        continue
    ov = overlap(src, plain(out.get("article_html", "")))
    if ov > 0.15:
        out2 = gemini(write_prompt(src, "IMPORTANT: your last attempt was too close to the source. "
                                        "Use completely different wording and sentence structure."))
        if out2 and not out2.get("skip"):
            out, ov = out2, overlap(src, plain(out2.get("article_html", "")))
    out["article_html"] = re.sub(r"(?is)<script.*?</script>", "", out.get("article_html", ""))
    jsonld = {"@context": "https://schema.org", "@type": "NewsArticle",
              "headline": out.get("title", ""), "description": out.get("meta_description", ""),
              "datePublished": today, "dateModified": today,
              "author": {"@type": "Organization", "name": "iPharmaCenter"},
              "publisher": {"@type": "Organization", "name": "iPharmaCenter",
                            "url": "https://www.ipharmacenter.com"},
              "keywords": ", ".join(out.get("tags", [])), "isBasedOn": item["url"]}
    drafts.insert(0, {"date": today, "site": item["site"], "source": item["url"], "score": item["score"],
                      "overlap": round(ov * 100), "jsonld": json.dumps(jsonld, indent=2), **out})
    time.sleep(8)

# mark every scored link as done so it is not processed again
for h in new:
    done.add(h["url"])
json.dump(sorted(done), open("processed.json", "w"))
json.dump(drafts[:60], open("drafts.json", "w"), indent=1)

# ---------- drafts page ----------
e = html.escape
page = ["""<!doctype html><html><head><meta charset="utf-8">
<meta name="robots" content="noindex, nofollow">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Drafts</title><style>body{font-family:Arial;max-width:900px;margin:20px auto;padding:0 12px}
details{border:1px solid #ccc;margin:10px 0;padding:8px}summary{font-weight:bold;cursor:pointer}
textarea{width:100%;height:90px}.warn{color:#b00}</style></head><body>
<h1>Draft articles for review</h1><p>Check every fact against the source before publishing.</p>"""]
for d in drafts[:60]:
    flag = " <span class='warn'>(high overlap, check)</span>" if d.get("overlap", 0) > 15 else ""
    page.append(f"<details><summary>{e(d['date'])} | {e(d.get('title',''))} | {e(d['site'])}{flag}</summary>")
    page.append(f"<p>Source: <a href='{e(d['source'])}' target='_blank'>{e(d['source'])}</a> "
                f"| importance {d['score']}/10 | overlap with source {d['overlap']}%</p>")
    page.append(f"<p><b>Meta description:</b></p><textarea>{e(d.get('meta_description',''))}</textarea>")
    page.append(f"<p><b>Slug:</b> {e(d.get('slug',''))} | <b>Tags:</b> {e(', '.join(d.get('tags', [])))}</p>")
    page.append(f"<h2>Article</h2>{d.get('article_html','')}")
    page.append(f"<p><b>Article HTML (copy):</b></p><textarea>{e(d.get('article_html',''))}</textarea>")
    page.append(f"<p><b>JSON-LD:</b></p><textarea>{e(d['jsonld'])}</textarea>")
    page.append(f"<p><b>LinkedIn:</b></p><textarea>{e(d.get('linkedin_post',''))}</textarea>")
    page.append(f"<p><b>X post:</b></p><textarea>{e(d.get('x_post',''))}</textarea></details>")
page.append("</body></html>")
open("drafts.html", "w", encoding="utf-8").write("\n".join(page))
print("drafts page built:", len(drafts))
