#!/usr/bin/env bash
# Run the whole SKU consolidation pipeline: stg -> sku_master -> transaction.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}

echo "== step 1: stg_{marketplace} (parallel)"
for s in shopee lazada blibli tiktok_tokopedia; do $PY step1_stg_$s.py & done
wait
echo "== step 2: unique SKU";            $PY step2_extract_unique_sku.py
echo "== step 3: SKU master";            $PY step3_cleanse_sku_master.py
echo "== step 4: bundle price check";    $PY step4_bundle_price_check.py; $PY step4_bundle_price_report.py
echo "== step 5: bundle SKU";            $PY step5_bundle_sku.py
echo "== step 6: transactions (parallel)"
for s in shopee lazada blibli tiktok_tokopedia; do $PY step6_tx_$s.py & done
wait
echo "== step 7: merge into single t_order / t_order_detail"; $PY step7_merge_transactions.py
echo "done"
