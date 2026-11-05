"""Bundling master SKUs absent from stg_unique_sku, matched to the closest staging product name.

1. bundle SKUs (Kode SKU, not the BASE components) of raw/sku_bundle/bundling_master.csv that are
   not in stg/stg_unique_sku.csv (compared on sku_clean and seller_sku)      -> sku_master/bundle_sku_missing_in_stg.csv
2. product-name similarity: normalised names -> TF-IDF over character n-grams (3..5, word bounded)
   -> cosine distance; DBSCAN(eps=0.45, min_samples=2, cosine) over bundle + staging names confirms the fit
3. best (highest-score) staging SKU per bundle SKU                           -> sku_master/bundle_sku_name_match.csv
"""
import argparse
import os
import re

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer

from common.config import SKU_MASTER, STG, RAW

THRESHOLD = 0.45


def normalise(s):
    s = str(s).lower()
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)                    # 1,5 -> 1.5
    s = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", s)  # 400g -> 400 g, x12 -> x 12
    s = re.sub(r"[^a-z0-9.\s]", " ", s)                       # scrub symbols, keep spacing
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)                 # '.' only inside decimals
    return re.sub(r"\s+", " ", s).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", default=os.path.join(RAW, "sku_bundle", "bundling_master.csv"))
    ap.add_argument("--stg", default=os.path.join(STG, "stg_unique_sku.csv"))
    ap.add_argument("--out-dir", default=SKU_MASTER)
    a = ap.parse_args()

    b = pd.read_csv(a.bundle, sep=";", dtype=str)[["Kode SKU", "Nama SKU"]].drop_duplicates()
    b.columns = ["bundle_sku", "bundle_name"]
    b = b.assign(bundle_sku=b.bundle_sku.str.strip()).drop_duplicates("bundle_sku")
    u = pd.read_csv(a.stg, dtype=str).fillna("")

    known = set(u.sku_clean.str.strip().str.upper()) | set(u.seller_sku.str.strip().str.upper())
    miss = b[~b.bundle_sku.str.upper().isin(known)].reset_index(drop=True)
    print("bundle SKUs %d, missing in stg_unique_sku %d" % (len(b), len(miss)))
    miss.to_csv(os.path.join(a.out_dir, "bundle_sku_missing_in_stg.csv"), index=False)

    cand = (u[u.product_name.str.strip() != ""]
            .groupby(["sku_clean", "product_name"], as_index=False)
            .agg(marketplace=("marketplace", lambda s: ",".join(sorted(set(s)))),
                 order_line_count=("order_line_count", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).sum())),
                 stg_seller_skus=("seller_sku", lambda s: " | ".join(sorted(set(x for x in s if x)))),
                 stg_marketplace_skus=("marketplace_sku", lambda s: " | ".join(sorted(set(x for x in s if x)))),
                 stg_variations=("variation", lambda s: " | ".join(sorted(set(x for x in s if x)))),
                 stg_first_order_at=("first_order_at", "min"), stg_last_order_at=("last_order_at", "max")))
    miss["_n"] = miss.bundle_name.map(normalise)
    cand["_n"] = cand.product_name.map(normalise)

    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
    X = vec.fit_transform(pd.concat([miss._n, cand._n], ignore_index=True))
    Xb, Xc = X[: len(miss)], X[len(miss):]
    dist = 1.0 - (Xb @ Xc.T).toarray().clip(0, 1)            # cosine distance (rows are L2-normalised)
    best = dist.argmin(axis=1)
    bd = dist[np.arange(len(miss)), best]

    labels = DBSCAN(eps=THRESHOLD, min_samples=2, metric="cosine").fit_predict(X)
    lb, lc = labels[: len(miss)], labels[len(miss):]

    out = pd.DataFrame({
        "bundle_sku": miss.bundle_sku, "bundle_name": miss.bundle_name,
        "matched_sku": cand.sku_clean.values[best], "matched_name": cand.product_name.values[best],
        "matched_marketplace": cand.marketplace.values[best],
        "stg_seller_skus": cand.stg_seller_skus.values[best],
        "stg_marketplace_skus": cand.stg_marketplace_skus.values[best],
        "stg_variations": cand.stg_variations.values[best],
        "stg_order_line_count": cand.order_line_count.values[best],
        "stg_first_order_at": cand.stg_first_order_at.values[best],
        "stg_last_order_at": cand.stg_last_order_at.values[best],
        "distance": bd.round(4), "score": (1 - bd).round(4),
        "within_threshold": bd <= THRESHOLD,
        "dbscan_cluster_bundle": lb, "dbscan_cluster_match": lc[best],
    })
    out["dbscan_fit"] = (out.dbscan_cluster_bundle >= 0) & (out.dbscan_cluster_bundle == out.dbscan_cluster_match)
    out = out.sort_values(["score", "bundle_sku"], ascending=[False, True])
    path = os.path.join(a.out_dir, "bundle_sku_name_match.csv")
    out.to_csv(path, index=False)
    print("-> %s  %d rows | within %.2f: %d | dbscan fit: %d | both: %d" % (
        path, len(out), THRESHOLD, out.within_threshold.sum(), out.dbscan_fit.sum(),
        (out.within_threshold & out.dbscan_fit).sum()))


if __name__ == "__main__":
    main()
