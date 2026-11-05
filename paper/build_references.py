"""Build APA 7 reference entries from Crossref metadata for the manuscript's DOIs.

    python paper/build_references.py > paper/references_crossref.md
"""
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request

DOIS = [l.split("#")[0].strip() for l in open(sys.argv[1]) if l.split("#")[0].strip()]


def get(doi):
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
    req = urllib.request.Request(url, headers={"User-Agent": "renderthemolecule-refcheck/1.0"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)["message"]
        except Exception:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(doi)


def clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\s+", " ", text).strip()


def person(a):
    if "family" not in a:
        return a.get("name", "")
    given = a.get("given", "")
    initials = " ".join(p[0] + "." for p in re.split(r"[\s]+", given) if p and p[0].isalpha())
    initials = re.sub(r"(\w)\.-", r"\1.-", initials)
    return f"{a['family']}, {initials}".strip().rstrip(",")


def authors(lst):
    names = [person(a) for a in lst]
    if len(names) == 1:
        return names[0]
    if len(names) <= 20:
        return ", ".join(names[:-1]) + ", & " + names[-1]
    return ", ".join(names[:19]) + ", . . . " + names[-1]


def year(m):
    for key in ("published-print", "journal-issue", "issued", "published-online"):
        part = m.get(key)
        if isinstance(part, dict) and "published-print" in part:
            part = part["published-print"]
        if part and part.get("date-parts") and part["date-parts"][0][0]:
            return part["date-parts"][0][0]
    return "n.d."


for doi in DOIS:
    m = get(doi)
    title = clean((m.get("title") or [""])[0])
    journal = clean((m.get("container-title") or [""])[0])
    vol, issue = m.get("volume", ""), m.get("issue", "")
    pages = m.get("page", "") or m.get("article-number", "")
    pages = pages.replace("-", "–")
    src = f"*{journal}*"
    if vol:
        src += f", *{vol}*"
        if issue:
            src += f"({issue})"
    if pages:
        src += f", {pages}"
    print(f"{authors(m.get('author', []))} ({year(m)}). {title}. {src}. https://doi.org/{doi.lower()}")
    time.sleep(1)
