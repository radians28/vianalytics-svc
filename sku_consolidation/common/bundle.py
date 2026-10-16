"""Load raw/sku_bundle/{bundling_master,bundling_price}.csv into tidy frames."""
import os
import re

import numpy as np
import pandas as pd

from .config import RAW

BUNDLE_DIR = os.path.join(RAW, "sku_bundle")


def _read(path):
    df = pd.read_csv(path, sep=";", dtype=str, encoding="utf-8-sig", keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    return df.apply(lambda c: c.str.strip())


FREE_GIFT = re.compile(r"^37/B\d|(^|[\s\]])B - ")


def load_prices(bundle_dir=BUNDLE_DIR):
    """SKU -> (name, price, free_gift). A blank price stays NaN, except for free gifts (code 37/B..., i.e.
    the "B - ..." gimmick / sampling / box items): they are not sold, so their price is set to 0 and the whole
    bundle value goes to the other components."""
    p = _read(os.path.join(bundle_dir, "bundling_price.csv"))
    p["price"] = pd.to_numeric(p["Price"].replace("", pd.NA), errors="coerce")
    p = p.rename(columns={"SKU": "sku", "Name": "name"})[["sku", "name", "price"]]
    p["free_gift"] = p["price"].isna() & (p["sku"].str.match(r"^37/B\d") | p["name"].str.contains(r"(?:^|[\s\]])B - ", regex=True))
    p.loc[p["free_gift"], "price"] = 0.0
    return p.drop_duplicates("sku", keep="last").set_index("sku")


def price_of(prices, skus, names):
    """(price, free_gift) per SKU. Listed prices win; a SKU that is blank in the price file or absent from it is a
    free gift (price 0) when its code is 37/B... or its name starts with "B - "; otherwise the price is NaN."""
    skus, names = pd.Series(skus).reset_index(drop=True), pd.Series(names).reset_index(drop=True)
    price = skus.map(prices["price"])
    gift = skus.map(prices["free_gift"].astype(bool)).astype("boolean").fillna(False).astype(bool)
    gift |= price.isna() & (skus.str.match(r"^37/B\d") | names.str.contains(r"(?:^|[\s\]])B - ", regex=True, na=False))
    price = price.mask(gift & price.isna(), 0.0)
    return price.values, gift.values


def load_master(bundle_dir=BUNDLE_DIR):
    """One row per (bundle, leaf component) for TRUE bundles only (a row whose base is the SKU itself,
    i.e. a plain SKU listed in the master, is not a bundle).
    Recursive PCS<->BOX pairs are resolved and bundle-in-bundle components are flattened (see below);
    `df.attrs["log"]` lists those actions as dicts (bundle_sku, dq_flag, detail).

    Columns: bundle_sku, bundle_name, component_seq, component_sku, component_name,
             qty (>0, blank/0 -> 1), notes (comma list: qty_missing, dup_component, flattened, nested_bundle=unresolved cycle)
    """
    m = _read(os.path.join(bundle_dir, "bundling_master.csv")).rename(columns={
        "Kode SKU": "bundle_sku", "Nama SKU": "bundle_name", "Kode SKU BASE": "component_sku",
        "Nama SKU BASE": "component_name", "Qty BASE in 1 BUNDLE": "qty_raw"})
    bundles = set(m.loc[m["bundle_sku"] != m["component_sku"], "bundle_sku"])
    m = m[m["bundle_sku"].isin(bundles)].copy()
    q = pd.to_numeric(m["qty_raw"].replace("", pd.NA), errors="coerce")
    m["qty_missing"] = ~(q > 0)
    m["qty"] = q.where(q > 0, 1).astype(int)
    m["dup_component"] = m.duplicated(["bundle_sku", "component_sku"], keep=False)
    agg = (m.groupby(["bundle_sku", "component_sku"], sort=False)
             .agg(bundle_name=("bundle_name", "first"), component_name=("component_name", "first"),
                  qty=("qty", "sum"), qty_missing=("qty_missing", "any"),
                  dup_component=("dup_component", "any")).reset_index())
    agg["notes"] = [",".join(n for n, f in (("qty_missing", a), ("dup_component", b)) if f)
                    for a, b in zip(agg["qty_missing"], agg["dup_component"])]
    return _flatten(_resolve_recursive(agg))


def _resolve_recursive(agg):
    """PCS <-> BOX pairs: A lists B (qty blank) and B lists A (qty 12). The row with a quantity is the real
    conversion (BOX = 12 x PCS), the blank-quantity row is its inverse and is dropped, so the priced
    component (PCS) becomes a plain SKU. Pairs where both or neither row has a quantity are kept and flagged."""
    key = {(b, c): i for i, (b, c) in enumerate(zip(agg["bundle_sku"], agg["component_sku"]))}
    drop, log = set(), []
    for (b, c), i in key.items():
        j = key.get((c, b))
        if j is None or b > c:
            continue
        qa, qb = agg.at[i, "qty_missing"], agg.at[j, "qty_missing"]
        if qa != qb:
            d = i if qa else j
            drop.add(d)
            log.append({"bundle_sku": agg.at[d, "bundle_sku"], "dq_flag": "recursive_edge_dropped",
                        "detail": "%s -> %s (inverse of %s -> %s, which has the quantity)" % (
                            agg.at[d, "bundle_sku"], agg.at[d, "component_sku"],
                            agg.at[d, "component_sku"], agg.at[d, "bundle_sku"])})
        else:
            log.append({"bundle_sku": b, "dq_flag": "recursive_unresolved", "detail": "%s <-> %s" % (b, c)})
    out = agg.drop(index=sorted(drop)).reset_index(drop=True)
    out.attrs["log"] = log
    return out


def _flatten(agg):
    """Expand components that are bundles themselves until only leaf components remain (qty multiplied,
    duplicate leaves summed). Cycles that could not be resolved are left as they are."""
    log = list(agg.attrs.get("log", []))
    boms, names = {}, {}
    for r in agg.itertuples():
        boms.setdefault(r.bundle_sku, []).append((r.component_sku, r.qty, r.notes))
        names.setdefault(r.bundle_sku, r.bundle_name)
        names.setdefault(r.component_sku, r.component_name)

    def leaves(sku, stack):
        out = {}                                       # leaf -> [qty, notes set]
        for comp, qty, notes in boms[sku]:
            nn = {x for x in notes.split(",") if x}
            if comp in boms and comp not in stack:
                for leaf, (lq, ln) in leaves(comp, stack + (comp,)).items():
                    o = out.setdefault(leaf, [0, set()])
                    o[0] += qty * lq
                    o[1] |= nn | ln | {"flattened"}
            else:
                o = out.setdefault(comp, [0, set()])
                o[0] += qty
                o[1] |= nn
        return out

    rows = []
    for b in boms:
        flat = leaves(b, (b,))
        if any("flattened" in n for _, n in flat.values()):
            log.append({"bundle_sku": b, "dq_flag": "flattened",
                        "detail": "components expanded to " + ",".join(flat)})
        for seq, (leaf, (q, nn)) in enumerate(flat.items(), 1):
            if leaf in boms:        # unresolved cycle
                nn.add("nested_bundle")
            rows.append({"bundle_sku": b, "bundle_name": names[b], "component_seq": seq,
                         "component_sku": leaf, "component_name": names[leaf], "qty": int(q),
                         "notes": ",".join(sorted(nn))})
    out = pd.DataFrame(rows)
    out.attrs["log"] = log
    return out
