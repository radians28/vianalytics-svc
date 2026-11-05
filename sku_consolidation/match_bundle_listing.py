"""Find order listings that look like a bundle of the bundling master (no AI, token / size / price scoring).

Output : sku_master/bundle_listing_candidates.csv   (top candidates per bundle that has no order listing yet)
Rule   : every component of the bundle must be found in the listing name (coverage of the component's own
         words >= --min-coverage; a "B - ..." gift component uses the name of the SKU it refers to) and the
         main component's size (grams) must appear in the listing name.
Score  = 0.4 * mean component coverage + 0.2 * main size match
       + 0.2 * price match (listing median unit price within --price-tol of the bundle price or of the main component)
       + 0.2 * quantity match (qty > 1 of a component appears as "N pouch/pack/pcs" or "x N" in the listing name)
"""
import argparse
import os
import re
import statistics

import pandas as pd

from common import bundle, normalize as nz
from common.config import CHANNELS, SKU_MASTER, STG

STOP = set("""bdl royal canin makanan kucing anjing dewasa anak induk bayi dry wet pcs box free gratis b fhn fcn fbn shn bhn
ccn pouch pouches pouce pouces pack packs pcs paket isi bundling with set of and amp the for gift gimmick exclusive""".split())
SYN = {"intens": "intense", "inst": "instinctive", "instictive": "instinctive", "steril": "sterilised",
       "sterilized": "sterilised", "longhair": "long hair", "xsmall": "xsmall", "x": "", "k": ""}
SIZE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|k|gr|g)\b", re.I)


def sizes(text):
    out = set()
    for q, u in SIZE.findall(text.lower()):
        out.add(float(q.replace(",", ".")) * (1000 if u in ("kg", "k") else 1))
    return out


def tokens(text):
    t = re.sub(r"\d+\s*x\s*\d+\s*(?:g|gr)\b", " ", text.lower())          # 12x85g
    t = SIZE.sub(" ", t.replace("x-small", "xsmall"))
    out = []
    for w in re.findall(r"[a-z]+", t):
        w = SYN.get(w, w)
        out += [x for x in w.split() if x and x not in STOP]
    return set(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--price-tol", type=float, default=0.03)
    ap.add_argument("--min-score", type=float, default=0.65)
    ap.add_argument("--min-coverage", type=float, default=0.5)
    a = ap.parse_args()

    master = bundle.load_master()
    prices = bundle.load_prices()
    raw = pd.read_csv(os.path.join(bundle.BUNDLE_DIR, "bundling_master.csv"), sep=";", dtype=str,
                      encoding="utf-8-sig", keep_default_na=False)
    # name of the SKU a B- gift refers to, so the gift's real product words are used
    ref_name = {}
    for b, g in raw[raw["Kode SKU"] != raw["Kode SKU BASE"]].groupby("Kode SKU"):
        ref_name[b] = " ".join(g["Nama SKU BASE"])

    # bundles that already have an order listing (resolved bundle SKU via m_platform_sku)
    m_sku = pd.read_csv(os.path.join(SKU_MASTER, "m_sku.csv"), dtype=str, keep_default_na=False)
    pl = pd.read_csv(os.path.join(SKU_MASTER, "m_platform_sku.csv"), dtype=str, keep_default_na=False)
    code_of = m_sku.set_index("sku_id")["master_sku"]
    linked = {code_of[s] for s in pl["sku_id"].unique()}

    # listings: name, channel, median unit price
    rows = []
    for ch in CHANNELS:
        n = nz.normalize(nz.load_stg(ch), ch)
        n = n[n["platform_sku"].notna() & (n["unit_price"] > 0)]
        g = n.groupby("platform_sku").agg(name=("product_name", "last"), lines=("order_no", "size"),
                                          price=("unit_price", "median"),
                                          first=("created_at", "min"), last=("created_at", "max")).reset_index()
        g.insert(0, "channel", ch)
        rows.append(g)
    L = pd.concat(rows, ignore_index=True)
    L["tok"] = L["name"].map(tokens)
    L["siz"] = L["name"].map(sizes)

    price_of = prices["price"]
    out = []
    for b, comp in raw[raw["Kode SKU"] != raw["Kode SKU BASE"]].groupby("Kode SKU", sort=False):
        if b in linked or b not in set(master["bundle_sku"]) or b.startswith("37/B"):    # 37/B... = gift wrappers
            continue
        parts = []                                    # (qty, tokens, sizes, base price)
        for _, c in comp.iterrows():
            code = c["Kode SKU BASE"]
            name = ref_name.get(code, c["Nama SKU BASE"])    # B- gift -> name of the SKU it refers to
            q = int(c["Qty BASE in 1 BUNDLE"] or 1) if (c["Qty BASE in 1 BUNDLE"] or "1").isdigit() else 1
            parts.append((max(q, 1), tokens(name), sizes(name), price_of.get(code)))
        parts = [p for p in parts if p[1]]
        if not parts:
            continue
        main = max(parts, key=lambda p: (p[3] or 0))
        main_size = max(main[2]) if main[2] else None
        need_sizes = {z for p in parts for z in p[2] if z >= 300}      # every dry size of the bundle (e.g. 2K and 400G)
        bprice = price_of.get(b)
        need_qty = {q for q, *_ in parts if q > 1}
        for r in L.itertuples():
            if not r.tok:
                continue
            cov = [len(t & r.tok) / len(t) for _, t, _, _ in parts]
            if min(cov) < a.min_coverage:
                continue
            sm = 1.0 if (main_size and main_size in r.siz) else 0.0
            if main_size and not sm:
                continue
            if need_sizes and not need_sizes <= r.siz:
                continue
            pm = float(any(ref and abs(r.price - ref) <= a.price_tol * ref for ref in (bprice, main[3])))
            nums = {int(n) for tup in re.findall(r"(?:x|\+)\s*(\d+)\b|(\d+)\s*(?:pouch|pouces|packs?|pcs)", r.name.lower()) for n in tup if n}
            qm = 1.0 if (not need_qty or need_qty <= nums) else 0.0
            score = 0.4 * (sum(cov) / len(cov)) + 0.2 * sm + 0.2 * pm + 0.2 * qm
            if score >= a.min_score:
                out.append(dict(bundle_sku=b, bundle_name=comp["Nama SKU"].iloc[0], bundle_price=bprice,
                                channel=r.channel, platform_sku=r.platform_sku, listing_name=r.name,
                                listing_lines=r.lines, listing_median_price=round(r.price),
                                min_coverage=round(min(cov), 2), size_match=int(sm), price_match=int(pm),
                                qty_match=int(qm), score=round(score, 2),
                                first_order=str(r.first)[:10], last_order=str(r.last)[:10]))
    res = pd.DataFrame(out).sort_values(["bundle_sku", "score"], ascending=[True, False])
    res = res.groupby("bundle_sku").head(3)
    res.to_csv(os.path.join(SKU_MASTER, "bundle_listing_candidates.csv"), index=False)
    orphan = [b for b in master["bundle_sku"].unique() if b not in linked]
    print("bundles:", master["bundle_sku"].nunique(), "| without listing:", len(orphan), "| with candidates:",
          res["bundle_sku"].nunique(), "| candidate rows:", len(res))


if __name__ == "__main__":
    main()
