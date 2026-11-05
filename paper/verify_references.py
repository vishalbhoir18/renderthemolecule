"""Check every DOI in the manuscript's reference list against Crossref.

    python paper/verify_references.py

Prints, for each DOI, the registered first author, year, title and journal so
they can be compared with the reference as written.
"""
import json
import sys
import time
import urllib.request

DOIS = """
10.1093/nar/28.1.235
10.1093/nar/gkab314
10.1093/bioinformatics/bty419
10.1093/nar/gkv402
10.1093/bioinformatics/btu829
10.1002/ijch.201300024
10.1093/bioinformatics/btz502
10.1038/nmeth.4499
10.1002/pro.3235
10.1002/pro.3943
10.1016/0263-7855(96)00018-5
10.1093/bioinformatics/btaa009
10.1016/j.jmb.2018.01.013
10.1109/TVCG.2006.115
10.1016/S0076-6879(97)77028-9
10.1016/j.str.2019.08.011
10.1111/cgf.13072
10.1016/j.str.2019.09.001
10.1042/BST20190621
10.1016/j.str.2010.12.023
10.1186/1471-2105-13-S4-S16
10.1093/bioinformatics/bty968
10.1002/jcc.25155
10.1186/s12859-018-2367-z
10.1002/jcc.21787
10.1371/journal.pcbi.1008247
10.1145/15886.15902
10.1109/TIP.2003.819861
10.1093/nar/gkad1011
10.1038/s41586-021-03819-2
10.1038/s41592-022-01488-1
10.7717/peerj-cs.86
10.1038/s41597-022-01710-x
10.1038/nmeth.1427
10.1038/nrm3874
10.1371/journal.pcbi.1004516
10.1016/j.str.2005.01.012
10.1093/bioinformatics/btx789
10.1016/j.jmb.2007.05.022
10.1038/sdata.2016.18
10.1038/s41467-020-19160-7
10.1371/journal.pcbi.1003833
10.1016/j.cels.2018.03.014
10.1145/2723872.2723882
10.1016/j.jmb.2022.167599
10.1038/s41586-024-07487-w
""".split()


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "renderthemolecule-refcheck/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def describe(item):
    authors = item.get("author") or [{}]
    first = authors[0].get("family") or authors[0].get("name") or "?"
    issued = (item.get("issued") or {}).get("date-parts", [[None]])[0][0]
    title = (item.get("title") or ["?"])[0]
    journal = (item.get("container-title") or [""])[0]
    vol, page = item.get("volume", ""), item.get("page", "") or item.get("article-number", "")
    return f"{first} et al. ({issued}) {title} | {journal} {vol}:{page} | n_authors={len(item.get('author') or [])}"


def main(args):
    if args and args[0] == "search":
        q = " ".join(args[1:])
        data = get("https://api.crossref.org/works?rows=3&query.bibliographic=" + urllib.parse.quote(q))
        for item in data["message"]["items"]:
            print(item["DOI"], "::", describe(item))
        return
    for doi in args or DOIS:
        try:
            item = get("https://api.crossref.org/works/" + urllib.parse.quote(doi))["message"]
            print("OK  ", doi, "::", describe(item))
        except Exception as exc:
            print("FAIL", doi, "::", exc)
        time.sleep(0.2)


if __name__ == "__main__":
    import urllib.parse
    main(sys.argv[1:])
