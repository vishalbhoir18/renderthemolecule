"""Deposited atom counts for every current PDB entry (RCSB Data API).

    python paper/benchmark/pdb_size_distribution.py

Writes paper/benchmark/pdb_atom_counts.csv and prints the share of entries at
or below the sizes that the benchmark rendered.
"""
import csv
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "pdb_atom_counts.csv"
QUERY = "query($ids:[String!]!){entries(entry_ids:$ids){rcsb_id rcsb_entry_info{deposited_atom_count}}}"


def post(ids):
    body = json.dumps({"query": QUERY, "variables": {"ids": ids}}).encode()
    for attempt in range(5):
        try:
            req = urllib.request.Request("https://data.rcsb.org/graphql", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)["data"]["entries"]
        except Exception:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(ids[0])


def main():
    with urllib.request.urlopen("https://data.rcsb.org/rest/v1/holdings/current/entry_ids", timeout=120) as r:
        ids = json.load(r)
    batches = [ids[i:i + 500] for i in range(0, len(ids), 500)]
    rows = []
    with ThreadPoolExecutor(4) as pool:
        for entries in pool.map(post, batches):
            for e in entries:
                n = (e.get("rcsb_entry_info") or {}).get("deposited_atom_count")
                rows.append((e["rcsb_id"], n))
    with open(OUT, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pdb_id", "deposited_atom_count"])
        w.writerows(sorted(rows))
    counts = [n for _, n in rows if n is not None]
    print(f"{len(ids)} entries listed, {len(counts)} with an atom count")
    for t in (10_000, 58_870, 218_776, 300_000, 1_000_000, 3_000_000):
        share = sum(n <= t for n in counts) / len(counts)
        print(f"<= {t:>9,} atoms: {share:.2%}")
    counts.sort()
    print("median", counts[len(counts) // 2], "p90", counts[int(len(counts) * 0.9)], "p99", counts[int(len(counts) * 0.99)])


if __name__ == "__main__":
    main()
