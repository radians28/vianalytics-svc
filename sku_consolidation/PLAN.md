# SKU Consolidation – Script Generation Plan


## Context
Raw order exports from 5 marketplaces (TikTok+Tokopedia merged → 4 pipelines + 1 shared export) must become (a) SKU master data and (b) order transaction data, as CSVs shaped like `ddl_royal_canin.sql` (schema `royal_canin`, PostgreSQL, Asia/Jakarta). Inputs: `raw/{shopee,lazada,blibli,tiktok_tokopedia}/*.xlsx`, `raw/sku_bundle/bundling_master.csv` (`Kode SKU;Nama SKU;Kode SKU BASE;Nama SKU BASE;Qty BASE in 1 BUNDLE`) and `bundling_price.csv` (`SKU;Name;Price`).

Existing: `01_extract_unique_products.py` (raw→unique products, filtered to 2026) and `02_cleanse_sku_master.py` (SKU cleaning, union-find identity, bundle rules R1–R6). These are **reused/refactored** (clean_sku, channel prefix regex `TKP_|TTS_|LZD_|SHP_|BLI_`, union-find), not rewritten. Proposed layout keeps them but renames to the new step numbering.

## Folder layout
```
sku_consolidation/
  PLAN.md
  common/            # shared helpers (package, imported by all scripts)
    config.py        # paths, channel configs (ts format, column maps)
    readers.py       # read_xlsx (calamine), tiktok desc-row filter, header validation
    parsers.py       # parse_ts (per-channel fmt → Asia/Jakarta tz-aware), parse_money (Shopee '414.090', Blibli 'Rp391.000'), clean_sku
    ids.py           # shopee platform sku = 'SHP_'+md5(name|variation)[:12]; surrogate-id allocators
  raw/               # input (unchanged)
  stg/               # step 1 + 2 output
  sku_master/        # step 3 + 4 output
  transaction/       # step 5 output
  step1_stg_shopee.py  step1_stg_lazada.py  step1_stg_blibli.py  step1_stg_tiktok_tokopedia.py
  step2_extract_unique_sku.py
  step3_cleanse_sku_master.py
  step4_bundle_price_check.py
  step5_bundle_sku.py
  step6_tx_shopee.py  step6_tx_lazada.py  step6_tx_blibli.py  step6_tx_tiktok_tokopedia.py
  run_all.sh         # step1 (parallel) → 2 → 3 → 4 → 5 → 6 (parallel)
```
Python: pandas + `python-calamine` (required: TikTok `sheet2.xml` files break openpyxl). Install via `requirements.txt`; default pyenv 3.11 lacks calamine. All scripts: argparse (`--raw-dir --out-dir`), logging INFO, `dtype=str` reads, idempotent overwrite, row-count log per step.

## Step 1 – `stg_{marketplace}.csv` (4 scripts → `stg/`)
Per marketplace: read all xlsx, validate header against the DDL `stg_*` column list (snake_cased original headers, all text), concat, add `source_file`, `source_row_no`, parse order-created timestamp into sort key, **sort by created asc, then order_id**, write `stg/stg_{shopee,lazada,blibli,tiktok,tokopedia}.csv`. Keep values as text (raw fidelity, same as DDL); parsing happens downstream.

| Marketplace | Sheet / quirks | Order ID | Created (fmt) |
|---|---|---|---|
| Shopee (95 files, 51 cols) | `orders`; 2025+ split into parts; no platform SKU | No. Pesanan | Waktu Pesanan Dibuat `YYYY-MM-DD HH:MM` |
| Lazada (5 files, 77 cols) | `sheet1`; newest-first | orderNumber (line: orderItemId) | createTime `DD Mon YYYY HH:MM` |
| Blibli (9 files, 44 cols) | sheet `Data`; **skip** `2025 full year` (dashboard, no `SKU Blibli` col) | Nomor pesanan (line: Nomor Item pesanan) | Tanggal pesanan `DD/MM/YYYY HH:MM` |
| TikTok+Tokopedia (8 files, 65 cols) | calamine; row 2 is a description row → keep only `Order ID` matching `\d+`; split into `stg_tiktok` / `stg_tokopedia` by `Purchase Channel` | Order ID | Created Time `DD/MM/YYYY HH:MM:SS` |

Cross-file de-dup on (order_id, line key / sku, …) because 2022–2025 TikTok/Tokped files include late-Dec-2025 rows and Shopee parts may overlap; log dropped dupes. Blibli `202609` has exactly 1000 rows → warn (possible export cap).

## Step 2 – `step2_extract_unique_sku.py` → `stg/stg_unique_sku.csv`
Input: all `stg_*.csv`. Per marketplace:
1. Normalize to (marketplace, seller_sku, marketplace_sku, product_name, variation, order_ts).
   Seller SKU: Shopee `Nomor Referensi SKU`; Lazada `sellerSku`; Blibli `SKU seller`; TikTok/Tokped `Seller SKU`. Marketplace SKU: TikTok/Tokped `SKU ID`; Lazada `lazadaSku`; Blibli `SKU Blibli`; Shopee synthesized `SHP_`+md5.
2. a. Unique on (seller_sku, marketplace, marketplace_sku). b. `first_order_at = min(order_ts)`, plus latest product name.
3. c. Metadata columns for downstream master tables: cleaned sku (prefix stripped), `channel_code`, and a dq note when seller SKU is blank / differs across the same marketplace_sku (feeds `m_sku_history`) or the same seller SKU maps to many platform SKUs (feeds `m_sku_alias`).
4. d. Concatenate all marketplaces, **order by first_order_at asc**, write once.

## Step 3 – `step3_cleanse_sku_master.py` → `sku_master/`
Based on existing `02_cleanse_sku_master.py`. Input `stg/stg_unique_sku.csv`. Outputs (columns = DDL):
- `m_sku`: `sku_id`, `sku_master_code` (SKU-00001…, assigned by first_order_at), `master_sku`, `product_name`, `sku_type`, `bundle_flag`(false for now), `first_order_at`, `dq_flag`.
- `m_sku_alias`: `sku_code`(cleaned), `sku_id`, `is_master_code`, `first_seen_at`.
- `m_platform_sku`: `channel_id`(from `m_channel` seed order SHOPEE/TOKOPEDIA/TIKTOK/LAZADA/BLIBLI), `merchant_sku`, `sku_id`, `current_seller_sku`, `product_name`, `is_on_master_sku`, `first_order_at`.
- `m_sku_history` (SCD2, version ≥ 2, `changed_at ≥ valid_from`): when a platform SKU's seller SKU changed over time (e.g. Apr-2026 `37/…` recode).
Identity: clean SKU → union-find across alias/platform links (existing logic). Also emit `m_channel.csv` seed for FK resolution.

## Step 4 – `step4_bundle_price_check.py` → `sku_master/` (new, review-only)
Purpose: sanity-check that each bundle's own price is consistent with the sum of its components, before bundles are loaded and GMV is split by price ratio. Does **not** change master data.
Input: `raw/sku_bundle/bundling_master.csv` + `bundling_price.csv` (price file lists bundle SKUs *and* component SKUs). Params: `--threshold 0.10`.
1. Read both CSVs (`;` delimiter, CRLF, cast Price to numeric). Keep only true bundles: `Kode SKU` with ≥1 component row where `Kode SKU BASE ≠ Kode SKU` (rows where base == self are plain SKUs, skipped).
2. Per bundle: `bundle_price` = price of `Kode SKU`; per component row: `component_price` = price of `Kode SKU BASE`, `component_qty` = `Qty BASE in 1 BUNDLE` (blank/0 → 1, flagged `qty_missing`), `component_total = component_price × component_qty`.
3. `components_sum = Σ component_total` per bundle.
4. Compare `bundle_price` vs `components_sum`: `diff = bundle_price − components_sum`, `diff_pct = |diff| / min(bundle_price, components_sum)` (relative to the **lower** of the two). Flag `price_gap` when `diff_pct > 10%`; direction `bundle_higher` / `bundle_lower`.
5. Data-quality statuses (not compared, listed separately): `bundle_price_missing`, `component_price_missing` (any component without price → sum incomplete), `qty_missing`, `price_zero`.
6. Outputs:
   - `bundle_price_check.csv` – one row per bundle: bundle sku/name, bundle_price, components_sum, diff, diff_pct, direction, status (`ok` / `price_gap` / DQ status).
   - `bundle_price_mismatch.csv` – detail for flagged bundles only: bundle row then its component rows (component sku/name, qty, unit price, total), so reviewers see each component beside the bundle.
   - Console summary: bundles checked, ok, price_gap (split higher/lower), skipped for DQ.
Result is advisory: step 5 still builds `m_sku_bundle`; flagged bundles carry `dq_flag='price_gap'` there.

## Step 5 – `step5_bundle_sku.py` → `sku_master/`
Input: step 3 CSVs + `bundling_master.csv` + `bundling_price.csv` + step 4 `bundle_price_check.csv` (for `dq_flag`).
a. Every distinct `Kode SKU` that has ≥1 component whose base ≠ itself (or qty > 1 / multiple rows) → set `bundle_flag=true`, `sku_type='bundle'` in `m_sku` (rewrite `m_sku.csv`). Rows where base == self are plain SKUs, not bundles.
b. Any bundle or component code missing from `m_sku`/`m_sku_alias` → append new `m_sku` row (+ alias row, `first_order_at` null, `dq_flag='from_bundle_master'`).
c. `m_sku_bundle.csv`: `bundle_sku_id`, `component_seq`, `component_sku_id`, `component_sku_code`, `qty`, `dq_flag`, plus **extra `component_price` column** from `bundling_price.csv` (join on component code; not in DDL). Blank/0 qty → default 1 with `dq_flag='qty_missing'`; missing price → null + flag.
d. Also write `bundle_dq_review.csv`.

## Step 6 – transaction scripts (4 scripts → `transaction/`)
Per marketplace read `stg_*.csv`, parse timestamps (naive WIB → tz-aware Asia/Jakarta, offset `+07`) and money, then write `t_order_{channel}.csv` and `t_order_detail_{channel}.csv` per DDL (`order_no`, `channel_id`, status, created/paid/shipped/completed, buyer, warehouse, delivery option, payment method, `item_line_count`, `total_quantity`, `shipping_fee`, `gmv_2`; detail: `line_key`, `platform_sku_id`, `sku_id`, `seller_sku`, `quantity`, `unit_price`, discounts, `gmv_1`, `unit_sold`, `is_bundle`).
a. Resolve each line to `platform_sku_id`/`sku_id` via `m_platform_sku` (fallback `m_sku_alias`); check `m_sku.bundle_flag`.
b. Non-bundle: one detail row. Bundle: explode into one row per component from `m_sku_bundle`: `quantity = order_qty × component_qty`, `is_bundle=true`, `line_key = <orig>#<component_seq>`, **GMV allocated by price ratio**: `gmv_component = line_gmv × (component_price×component_qty) / Σ(component_price×component_qty)` (equal split by qty if any price missing, flagged; rounding remainder to last component so sums match).
c. Order-level `item_line_count`/`total_quantity` computed after explosion; `gmv_2` de-duplicated per order (Shopee repeats order-level fees on each line; `m_channel.gmv2_dedup_by_order`).
Per-channel notes: Shopee money dotted; Blibli `Rp`/`-Rp`; Lazada has **no quantity column** (see assumption); Lazada city = `shippingCity`; TikTok & Tokopedia go through one script and split on `Purchase Channel`.

## Assumptions / open items (confirm at approval)
1. Lazada: each row = 1 unit (qty=1); multipack "2X" in names is handled as SKU type, not qty.
2. `bundling_price.csv` price is per component unit (used only as a ratio).
3. Blibli 2025 order data is absent from raw (only a dashboard); nothing to be done.
4. Output is CSV only (no DB load); `*_id` surrogate keys generated deterministically (sorted by first order) so reruns are stable.

## Verification
- Step 4: hand-check 2–3 bundles (e.g. `37/390109901B`) against the CSV; flagged count equals rows with `diff_pct > 0.10`; bundles with missing prices appear only as DQ, never as `ok`.
- Run `run_all.sh` on a small sample (one month per marketplace) then full.
- Checks (assert in each script, log in summary): stg row count = Σ input rows − dupes; stg sorted; unique key uniqueness in step 2; no orphan `sku_id` in alias/platform/history/bundle; `m_sku_history` CHECK rules; Σ detail `gmv_1` before vs after bundle explosion equal per order; Σ detail quantity matches for non-bundles; all timestamps carry +07.
- Load the CSVs into a scratch Postgres created from `ddl_royal_canin.sql` with `\copy` to confirm constraints (PK/FK/CHECK) pass.

## As built (implementation notes)
- All scripts exist as planned; `./run_all.sh` runs steps 1–6. `common/` also has `normalize.py` (stg → standard line frame), `bundle.py` (bundle CSV loaders), `skutils.py`, `tx.py` (step 6 logic), `ddl.py` (stg column lists are read from the DDL).
- `01_extract_unique_products.py` / `02_cleanse_sku_master.py` are superseded (logic ported to step 2/3) and left untouched.
- Deviations: `t_order_*` carry `city_name`/`province_name` instead of `city_id` (no `m_city` is generated); `t_order_detail_*` carry an extra `dq_flag` (`equal_split`, `sku_not_resolved`). Ids are `channel_id × 1e9 + n`.
- Definitions: `gmv_1` = unit_price (original) × quantity, before discounts; `gmv_2` = order-level total taken once per order (Shopee/TikTok/Tokopedia) or summed over lines (Lazada/Blibli). Bundles are expanded one level only.
- Not done: loading the CSVs into a scratch Postgres.
- Update: step 6 writes per-channel files to `transaction/by_channel/`; new `step7_merge_transactions.py` merges them into single `transaction/t_order.csv` and `transaction/t_order_detail.csv` (DDL columns, ids renumbered 1..N, `city_id` from the new `sku_master/m_city.csv`); detail dq flags moved to `transaction/t_order_detail_dq.csv`.
- Update: bundle loader resolves recursive PCS<->BOX pairs (keeps the row with the quantity) and flattens bundle-in-bundle components; single-component price gaps are marked `pass` in step 4.
- Update (2026-10-29): bundles are broken down **one level only**; a component that is a bundle itself stays as that bundle SKU (`m_sku_bundle.dq_flag='nested_bundle'`, priced at the bundle price). A blank / unlisted price is 0 (`component_price_missing`) and `price_ratio` = price × qty / Σ(price × qty); quantity split (`equal_split`) only when every component is 0. Step 3 no longer merges a bundle with its own first-level component when a listing carries both (the code with fewer order lines stays apart, `sku_dq_review.dq_flag='bundle_component_split'`; listing `sku_id` = its busiest SKU), and step 6 resolves each line by its seller SKU first, then by the listing.
- Update: components without a price whose code is `37/B…` or name starts with "B - " (gimmick / sampling / box / voucher) are free gifts: price 0, `m_sku_bundle.dq_flag='free_gift'`, `m_sku.sku_type='free_gift'`; the bundle value is split over the other components. Gift-only bundles (all prices 0) fall back to a quantity split (`equal_split`).
- Update: `step4_bundle_price_report.py` writes `sku_master/laporan_harga_bundling.xlsx` (Indonesian report: bundle info | components | possible mismatch).
