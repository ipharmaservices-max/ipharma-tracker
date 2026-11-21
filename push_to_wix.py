import json, os, re, time, pathlib
import requests

API_KEY = os.environ["WIX_API_KEY"]
SITE_ID = os.environ["WIX_SITE_ID"]
MEMBER_ID = os.environ.get("WIX_MEMBER_ID", "").strip()   # optional
HEAD = {"Authorization": API_KEY, "wix-site-id": SITE_ID, "Content-Type": "application/json"}
BASE = "https://www.wixapis.com"

def load(name, default):
    p = pathlib.Path(name)
    return json.load(open(p, encoding="utf-8")) if p.exists() else default

drafts = load("drafts.json", [])
pushed = set(load("wix_done.json", []))
todo = [d for d in drafts if d.get("source") and d["source"] not in pushed and d.get("article_html")]
print(len(todo), "drafts to send to Wix")

def to_ricos(html_text):
    r = requests.post(f"{BASE}/ricos/v1/ricos-document/convert/to-ricos",
                      headers=HEAD, json={"html": html_text}, timeout=60)
    if r.status_code != 200:
        print("Ricos conversion error", r.status_code, r.text[:300])
        return None
    return r.json().get("document")

def create_draft(d, rich, full=True):
    post = {"title": d.get("title", "Untitled")[:100],
            "richContent": rich,
            "excerpt": d.get("meta_description", "")[:300]}
    if MEMBER_ID:
        post["memberId"] = MEMBER_ID
    if full:
        post["slug"] = d.get("slug", "")
        post["seoData"] = {"tags": [
            {"type": "meta", "props": {"name": "description", "content": d.get("meta_description", "")},
             "custom": True, "disabled": False},
            {"type": "script", "props": {"type": "application/ld+json"},
             "children": d.get("jsonld", ""), "custom": True, "disabled": False}]}
    return requests.post(f"{BASE}/blog/v3/draft-posts", headers=HEAD,
                         json={"draftPost": post, "publish": False}, timeout=60)

for d in todo:
    html_text = d["article_html"]
    if len(html_text) > 9500:
        print("skipped (article too long for Wix converter):", d.get("title"))
        continue
    rich = to_ricos(html_text)
    if not rich:
        continue
    r = create_draft(d, rich, full=True)
    if r.status_code != 200:
        print("Wix error with SEO fields", r.status_code, r.text[:300])
        r = create_draft(d, rich, full=False)      # retry without slug / SEO fields
        if r.status_code == 200:
            print("  created WITHOUT slug/SEO fields: add the meta description and JSON-LD by hand")
    if r.status_code == 200:
        print("Draft created in Wix:", d.get("title"))
        pushed.add(d["source"])
    else:
        print("Wix error", r.status_code, r.text[:300])
    time.sleep(3)

json.dump(sorted(pushed), open("wix_done.json", "w"))
