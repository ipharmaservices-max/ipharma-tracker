import json, pathlib, datetime, re, html
from urllib.parse import urldefrag, urlparse
from playwright.sync_api import sync_playwright

SGT = datetime.timezone(datetime.timedelta(hours=8))
today = datetime.datetime.now(SGT).date().isoformat()
urls = [u.strip() for u in open("sites.txt") if u.strip()]
state = pathlib.Path("state"); state.mkdir(exist_ok=True)
hist_file = pathlib.Path("history.json")
history = json.load(open(hist_file)) if hist_file.exists() else []
failed, baseline_sites = [], []

def key(u):
    p = urlparse(u)
    return re.sub(r"\W+", "_", p.netloc + p.path)[:80]

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36")
    for url in urls:
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(2000)
            raw = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => [e.href, (e.innerText||'').trim()])")
        except Exception as e:
            failed.append((url, str(e)[:100])); page.close(); continue
        page.close()
        links = {urldefrag(h)[0]: t.split("\n")[0] for h, t in raw
                 if h.startswith("http") and len(t) > 25}
        f = state / (key(url) + ".json")
        old = json.load(open(f)) if f.exists() else None
        if old is None:
            baseline_sites.append(url)
        else:
            for u, t in links.items():
                if u not in old:
                    history.append({"date": today, "site": urlparse(url).netloc,
                                    "title": t, "url": u})
        json.dump({**(old or {}), **links}, open(f, "w"))
    browser.close()

json.dump(history, open(hist_file, "w"), indent=1)

# ---- build the web page ----
dates = sorted({h["date"] for h in history}, reverse=True)[:14]
e = html.escape
parts = [f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Pharma Updates</title>
<style>body{{font-family:Arial;max-width:900px;margin:20px auto;padding:0 12px}}
h2{{background:#0b5;color:#fff;padding:8px}}h3{{margin-bottom:4px}}
li{{margin:4px 0}}.old{{color:#555}}</style></head><body>
<h1>Daily Pharma &amp; Healthcare Updates</h1>
<p>Last run: {today} (Singapore time). Sites checked: {len(urls)-len(failed)} of {len(urls)}.</p>"""]
if baseline_sites:
    parts.append(f"<p><b>{len(baseline_sites)} sites were recorded for the first time today; "
                 "their new links will appear from the next run.</b></p>")
if not history:
    parts.append("<p>No updates yet. This is normal on the first run.</p>")
for d in dates:
    items = [h for h in history if h["date"] == d]
    parts.append(f"<h2>{d} ({len(items)} new)</h2>")
    for site in sorted({h["site"] for h in items}):
        parts.append(f"<h3>{e(site)}</h3><ul>")
        for h in items:
            if h["site"] == site:
                parts.append(f'<li><a href="{e(h["url"])}" target="_blank">{e(h["title"])}</a></li>')
        parts.append("</ul>")
if failed:
    parts.append("<h2>Sites that could not be checked today</h2><ul>")
    for u, why in failed:
        parts.append(f"<li class='old'>{e(u)}</li>")
    parts.append("</ul>")
parts.append("</body></html>")
open("index.html", "w", encoding="utf-8").write("\n".join(parts))
print(len(urls), "sites,", len(failed), "failed")
