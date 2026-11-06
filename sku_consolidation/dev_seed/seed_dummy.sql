-- Dummy data for developing the SKU master page and the SKU review flow (unmatched listings
-- found by the Airflow process_sku step). DEV DATABASES ONLY.
--
--   docker exec -i autobahn-postgres psql -v ON_ERROR_STOP=1 -U postgres -d vianalytics \
--       < sku_consolidation/dev_seed/seed_dummy.sql
--
-- Remove everything again with clean_dummy.sql. Dummy rows are recognisable by:
--   m_sku.dq_flag LIKE '%dummy_seed%'   (aliases, listings, history and bundle rows hang off these SKUs)
--   upload_progress.upload_id LIKE 'dummy000-%'   (log_etl_run, log_sku_match follow the upload)
--   stg_*.source_file LIKE 'DUMMY%'
-- Seller SKUs are 99100xxx so they never collide with real codes. Similarity scores in
-- log_sku_match are hand-written, NOT produced by sku.matcher.
--
-- Scenario map
--   dummy000-...-0003  Paused  shopee   4 PENDING (near-duplicate names, one without seller SKU)
--   dummy000-...-0004  Paused  lazada   2 PENDING (new platform SKU, new seller SKU)
--   dummy000-...-0001  Completed shopee   1 MAPPED   (reviewed: mapped to SKU 99100007, alias + listing exist)
--   dummy000-...-0002  Completed tiktok   1 CREATED_NEW by 'auto' (SKU 99100013, dq_flag name_unmatched)
--   0005 Processing blibli, 0006/0007 Queued lazada/shopee, 0008 Failed blibli
-- Listing cases for the SKU master modal: SKU 99100001 has two Shopee listings (latest flag) and
-- a seller SKU change; 99100003 has a change plus a Lazada listing still on the old code.
-- No Lazada listing for 99100001 on purpose (seller SKU known, platform SKU new).

\set ON_ERROR_STOP on
begin;
set local timezone = 'Asia/Jakarta';
set local search_path = royal_canin, public;

do $$
begin
    if exists (select 1 from m_sku where dq_flag like '%dummy_seed%')
       or exists (select 1 from public.upload_progress where upload_id like 'dummy000-%') then
        raise exception 'dummy data is already present; run clean_dummy.sql first';
    end if;
end $$;

-- helpers (dropped with the session)
create function pg_temp.shp(name text, var text) returns text language sql immutable as $$
    select 'SHP_' || substr(md5(lower(trim(coalesce(name, ''))) || '|' || lower(trim(coalesce(var, '')))), 1, 12)
$$;
create function pg_temp.sid(code text) returns integer language sql stable as $$
    select sku_id from royal_canin.m_sku where master_sku = code
$$;
create function pg_temp.cand(code text, score numeric) returns jsonb language sql stable as $$
    select jsonb_build_object('sku_id', sku_id, 'sku_master_code', sku_master_code, 'name', product_name, 'score', score)
    from royal_canin.m_sku where master_sku = code
$$;

-- 1. SKU masters ---------------------------------------------------------------------------
with v(master_sku, product_name, sku_type, bundle_flag, dq_flag) as (values
    ('99100001', 'Royal Canin Kitten 2kg',                              'single',    false, 'dummy_seed'),
    ('99100002', 'Royal Canin Persian Adult 2kg',                       'single',    false, 'dummy_seed'),
    ('99100003', 'Royal Canin Indoor Adult 2kg',                        'single',    false, 'dummy_seed'),
    ('99100004', 'Royal Canin Mother & Babycat 2kg',                    'single',    false, 'dummy_seed'),
    ('99100005', 'Royal Canin Maxi Adult 4kg',                          'single',    false, 'dummy_seed'),
    ('99100006', 'Royal Canin Mini Starter 1kg',                        'single',    false, 'dummy_seed'),
    ('99100007', 'Royal Canin Mini Adult 2kg',                          'single',    false, 'dummy_seed'),
    ('99100008', 'Royal Canin Poodle Adult 1.5kg',                      'single',    false, 'dummy_seed'),
    ('99100009', 'Royal Canin Urinary Care Wet 85g',                    'single',    false, 'dummy_seed'),
    ('99100010', 'Royal Canin Kitten Pouch 85g',                        'single',    false, 'dummy_seed'),
    ('99100011', 'Royal Canin Kitten 2kg Multipack 3pcs',               'multipack', false, 'dummy_seed'),
    ('99100012', 'Bundle Royal Canin Kitten 2kg + Kitten Pouch 85g',    'bundle',    true,  'dummy_seed'),
    ('99100013', 'Royal Canin Hairball Care Adult 2kg',                 'single',    false, 'dummy_seed,name_unmatched')
), ids as (
    select v.*, nextval(pg_get_serial_sequence('royal_canin.m_sku', 'sku_id')) as id from v
)
insert into m_sku (sku_id, sku_master_code, master_sku, product_name, sku_type, bundle_flag, dq_flag)
select id, 'SKU-' || lpad(id::text, 5, '0'), master_sku, product_name, sku_type, bundle_flag, dq_flag
from ids order by id;

-- 2. marketplace listings (Shopee has no platform id: key = SHP_ + md5(name|variation)[:12]) ----
create temp table _pl on commit drop as
select v.ch, v.master, v.cur, v.name, v.var,
       case when v.ch = 'SHOPEE' then pg_temp.shp(v.name, v.var) else v.mid end as merchant_sku,
       v.foa::timestamptz as foa, v.upd::timestamptz as upd
from (values
    -- channel, master SKU, seller SKU as in the order file, listing name, variation, platform id, first order, updated
    ('SHOPEE',    '99100001', '99100001',    'Royal Canin Kitten 2kg',                           '',       null,              '2025-01-10 09:00+07', '2026-04-01 00:00+07'),
    ('SHOPEE',    '99100001', '99100001',    'Royal Canin Kitten Cat Food 2 Kg',                 'Kitten', null,              '2025-02-01 10:00+07', '2025-08-01 10:00+07'),
    ('SHOPEE',    '99100002', '99100002',    'Royal Canin Persian Adult 2kg',                    '',       null,              '2025-01-12 10:30+07', '2026-10-03 21:00+07'),
    ('SHOPEE',    '99100003', '99100003',    'Royal Canin Indoor Adult 2kg',                     '',       null,              '2025-01-15 08:15+07', '2026-02-10 00:00+07'),
    ('SHOPEE',    '99100004', '99100004',    'Royal Canin Mother & Babycat 2kg',                 '',       null,              '2025-02-02 13:00+07', '2026-09-28 09:00+07'),
    ('SHOPEE',    '99100007', '99100007',    'Royal Canin Mini Adult 2kg',                       '',       null,              '2025-03-01 09:10+07', '2026-10-05 12:00+07'),
    ('SHOPEE',    '99100007', 'MINI-AD-2',   'Royal Canin Mini Adult Dog 2 Kg',                  '',       null,              '2026-09-10 11:05+07', '2026-09-10 11:05+07'),
    ('SHOPEE',    '99100009', '99100009',    'Royal Canin Urinary Care Wet 85g',                 '',       null,              '2025-03-20 10:00+07', '2026-09-15 10:00+07'),
    ('SHOPEE',    '99100010', '99100010',    'Royal Canin Kitten Pouch 85g',                     'Kitten', null,              '2025-03-22 12:00+07', '2026-09-20 12:00+07'),
    ('SHOPEE',    '99100012', '99100012',    'Bundle Royal Canin Kitten 2kg + Kitten Pouch 85g', '',       null,              '2025-07-01 09:00+07', '2026-08-01 09:00+07'),
    ('TOKOPEDIA', '99100001', 'TKP_99100001','Royal Canin Kitten 2kg',                           '',       '1729000001',      '2025-03-05 12:00+07', '2026-03-01 10:00+07'),
    ('TOKOPEDIA', '99100003', 'TKP_99100003','Royal Canin Indoor Adult 2kg',                     '',       '1729000003',      '2025-03-06 09:00+07', '2026-03-01 10:00+07'),
    ('TOKOPEDIA', '99100005', 'TKP_99100005','Royal Canin Maxi Adult 4kg',                       '',       '1729000005',      '2025-03-10 11:00+07', '2026-03-01 10:00+07'),
    ('TOKOPEDIA', '99100006', 'TKP_99100006','Royal Canin Mini Starter 1kg',                     '',       '1729000006',      '2025-03-12 11:00+07', '2026-03-01 10:00+07'),
    ('TOKOPEDIA', '99100008', 'TKP_99100008','Royal Canin Poodle Adult 1.5kg',                   '',       '1729000008',      '2025-03-15 11:00+07', '2026-03-01 10:00+07'),
    ('TOKOPEDIA', '99100010', 'TKP_99100010','Royal Canin Kitten Pouch 85g',                     '',       '1729000010',      '2025-03-22 12:00+07', '2026-03-01 10:00+07'),
    ('TIKTOK',    '99100001', 'TKP_99100001','Royal Canin Kitten 2kg',                           '',       '1731000000001',   '2025-04-01 09:00+07', '2026-09-30 09:00+07'),
    ('TIKTOK',    '99100004', 'TKP_99100004','Royal Canin Mother & Babycat 2kg',                 '',       '1731000000004',   '2025-04-03 09:00+07', '2026-09-30 09:00+07'),
    ('TIKTOK',    '99100007', 'TKP_99100007','Royal Canin Mini Adult 2kg',                       '',       '1731000000007',   '2025-04-05 09:00+07', '2026-09-30 09:00+07'),
    ('TIKTOK',    '99100013', 'TKP_99100013','Royal Canin Hairball Care Adult 2kg',              '',       '1731000000099',   '2026-09-14 10:00+07', '2026-09-14 10:00+07'),
    ('LAZADA',    '99100002', 'LZD_99100002','Royal Canin Persian Adult 2kg',                    '',       '4000123402',      '2025-04-10 10:00+07', '2026-10-04 10:00+07'),
    ('LAZADA',    '99100003', 'LZD_99100103','Royal Canin Indoor Adult 2kg',                     '',       '4000123403',      '2025-04-12 10:00+07', '2025-04-12 10:00+07'),
    ('LAZADA',    '99100005', 'LZD_99100005','Royal Canin Maxi Adult 4kg',                       '',       '4000123405',      '2025-04-15 10:00+07', '2026-09-01 10:00+07'),
    ('BLIBLI',    '99100001', 'BLI_99100001','Royal Canin Kitten 2kg',                           '',       'RCN-70001-00001', '2025-05-02 09:00+07', '2026-09-10 09:00+07'),
    ('BLIBLI',    '99100005', 'BLI_99100005','Royal Canin Maxi Adult 4kg',                       '',       'RCN-70001-00005', '2025-05-04 09:00+07', '2026-09-10 09:00+07'),
    ('BLIBLI',    '99100008', 'BLI_99100008','Royal Canin Poodle Adult 1.5kg',                   '',       'RCN-70001-00008', '2025-05-06 09:00+07', '2026-09-10 09:00+07'),
    ('BLIBLI',    '99100012', 'BLI_99100012','Bundle Royal Canin Kitten 2kg + Kitten Pouch 85g', '',     'RCN-70001-00012', '2025-07-02 09:00+07', '2026-08-01 09:00+07')
) as v(ch, master, cur, name, var, mid, foa, upd);

insert into m_platform_sku (channel_id, merchant_sku, sku_id, current_seller_sku, product_name,
                            is_on_master_sku, first_order_at, updated_at)
select c.channel_id, p.merchant_sku, s.sku_id, p.cur, p.name,
       upper(regexp_replace(p.cur, '^(TKP|TTS|LZD|SHP|BLI)[_-]', '', 'i')) = s.master_sku,
       p.foa, p.upd
from _pl p
join m_channel c on c.channel_code = p.ch
join m_sku s on s.master_sku = p.master;

-- the master's first order is its earliest listing
update m_sku s set first_order_at = (select min(p.first_order_at) from m_platform_sku p where p.sku_id = s.sku_id)
where s.dq_flag like '%dummy_seed%';

-- 3. seller SKU aliases ----------------------------------------------------------------------
insert into m_sku_alias (sku_code, sku_id, is_master_code, first_seen_at)
select master_sku, sku_id, true, first_order_at from m_sku where dq_flag like '%dummy_seed%';

insert into m_sku_alias (sku_code, sku_id, is_master_code, first_seen_at)
select v.code, s.sku_id, false, v.seen::timestamptz
from (values ('37/KIT2',   '99100001', '2025-01-10 09:00+07'),
             ('99100103',  '99100003', '2025-01-15 08:15+07'),
             ('MINI-AD-2', '99100007', '2026-09-10 11:05+07')) v(code, master, seen)
join m_sku s on s.master_sku = v.master;

-- 4. seller SKU changes on a listing (SCD 2, version >= 2; version 1 is implicit) ------------
insert into m_sku_history (platform_sku_id, sku_id, version, old_seller_sku, new_seller_sku, valid_from, changed_at)
select p.platform_sku_id, p.sku_id, 2, h.old_sku, h.new_sku, p.first_order_at, h.changed::timestamptz
from (values ('SHOPEE', 'Royal Canin Kitten 2kg',        '37/KIT2',  '99100001', '2026-04-01 00:00+07'),
             ('SHOPEE', 'Royal Canin Indoor Adult 2kg',  '99100103', '99100003', '2026-02-10 00:00+07')) h(ch, name, old_sku, new_sku, changed)
join _pl x on x.ch = h.ch and x.name = h.name and x.var = ''
join m_channel c on c.channel_code = h.ch
join m_platform_sku p on p.channel_id = c.channel_id and p.merchant_sku = x.merchant_sku;

-- 5. bundle bill of materials ----------------------------------------------------------------
insert into m_sku_bundle (bundle_sku_id, component_seq, component_sku_id, component_sku_code, qty, component_price, price_ratio)
select b.sku_id, v.seq, comp.sku_id, comp.master_sku, v.qty, v.price, v.ratio
from (values (1, '99100001', 1, 150000.00, 0.90909091),
             (2, '99100010', 1,  15000.00, 0.09090909)) v(seq, code, qty, price, ratio)
join m_sku b on b.master_sku = '99100012'
join m_sku comp on comp.master_sku = v.code;

-- 6. uploads ----------------------------------------------------------------------------------
insert into public.upload_progress (upload_id, file_name, file_path, channel, status, total_rows, processed_rows,
                                    error_message, meta_data, created_at, updated_at, queued_at, processed_at,
                                    finished_at, last_heartbeat)
select v.id, v.file_name, '/dummy/' || v.file_name, v.channel, v.status, v.total_rows, coalesce(v.processed, 0),
       v.error_message, v.meta::json, v.created::timestamptz, coalesce(v.finished, v.created)::timestamptz,
       v.created::timestamptz, v.started::timestamptz, v.finished::timestamptz, v.heartbeat::timestamptz
from (values
    ('dummy000-0000-4000-8000-000000000001', 'DUMMY_shopee_orders_2026-09.xlsx',        'shopee',        'Completed',  1840, 1840, null,
        '{"channel":"shopee","size":482304}',        '2026-10-01 09:00:00+07', '2026-10-01 09:00:30+07', '2026-10-01 09:08:12+07', '2026-10-01 09:08:12+07'),
    ('dummy000-0000-4000-8000-000000000002', 'DUMMY_tiktok_tokopedia_2026-09.xlsx',     'tiktok_tokped', 'Completed',  2310, 2310, null,
        '{"channel":"tiktok_tokped","size":611840}', '2026-10-02 10:00:00+07', '2026-10-02 10:00:30+07', '2026-10-02 10:09:47+07', '2026-10-02 10:09:47+07'),
    ('dummy000-0000-4000-8000-000000000003', 'DUMMY_shopee_orders_2026-10.xlsx',        'shopee',        'Paused',     2105, 2105, null,
        '{"channel":"shopee","size":553984}',        '2026-11-04 09:30:00+07', '2026-11-04 09:30:40+07', null,                     '2026-11-04 09:36:10+07'),
    ('dummy000-0000-4000-8000-000000000004', 'DUMMY_lazada_orders_2026-10.xlsx',        'lazada',        'Paused',      940,  940, null,
        '{"channel":"lazada","size":251904}',        '2026-11-04 10:15:00+07', '2026-11-04 10:15:25+07', null,                     '2026-11-04 10:18:02+07'),
    ('dummy000-0000-4000-8000-000000000005', 'DUMMY_blibli_orders_2026-10.xlsx',        'blibli',        'Processing',  620,  310, null,
        '{"channel":"blibli","size":160256}',        (now() - interval '5 minutes')::text, (now() - interval '4 minutes')::text, null, (now() - interval '20 seconds')::text),
    ('dummy000-0000-4000-8000-000000000006', 'DUMMY_lazada_orders_2026-11.xlsx',        'lazada',        'Queued',      null, 0,   null,
        '{"channel":"lazada","size":198656}',        (now() - interval '3 minutes')::text, null, null, null),
    ('dummy000-0000-4000-8000-000000000007', 'DUMMY_shopee_orders_2026-11.xlsx',        'shopee',        'Queued',      null, 0,   null,
        '{"channel":"shopee","size":402432}',        (now() - interval '2 minutes')::text, null, null, null),
    ('dummy000-0000-4000-8000-000000000008', 'DUMMY_blibli_orders_2026-09.xlsx',        'blibli',        'Failed',      null, 0,   'Missing required column: sku_seller',
        '{"channel":"blibli","size":98304}',         '2026-10-20 14:00:00+07', '2026-10-20 14:00:05+07', '2026-10-20 14:00:20+07', '2026-10-20 14:00:20+07')
) as v(id, file_name, channel, status, total_rows, processed, error_message, meta, created, started, finished, heartbeat);

-- load runs (the Paused uploads' stg rows hang off these)
insert into log_etl_run (started_at, finished_at, status, channels, source_files, triggered_by, upload_id, error_message)
select u.created_at, u.finished_at,
       case u.status when 'Processing' then 'RUNNING' when 'Failed' then 'FAILED' else 'SUCCESS' end,
       case u.channel when 'tiktok_tokped' then 'TIKTOK,TOKOPEDIA' else upper(u.channel) end,
       u.file_name, 'upload', u.upload_id, u.error_message
from public.upload_progress u
where u.upload_id like 'dummy000-%' and u.status not in ('Queued');

-- 7. staged order lines of the two Paused uploads --------------------------------------------
insert into stg_shopee (no_pesanan, status_pesanan, waktu_pesanan_dibuat, nama_produk, nomor_referensi_sku, nama_variasi,
                        harga_awal, harga_setelah_diskon, jumlah, subtotal_pesanan, source_file, source_row_no, load_run_id)
select v.order_no, 'Selesai', v.ts, v.name, v.sku, v.var, v.price, v.price, v.qty,
       (v.price::numeric * v.qty::int)::text, 'DUMMY_shopee_orders_2026-10.xlsx', row_number() over (order by v.order_no), r.run_id
from (values
    -- already in the master: loaded with the order handling
    ('DMY2610A001', '2026-10-03 14:22', 'Royal Canin Kitten 2kg',                       '99100001',    '',            '185000', '1'),
    ('DMY2610A002', '2026-10-04 09:10', 'Royal Canin Kitten 2kg',                       '99100001',    '',            '185000', '2'),
    ('DMY2610A003', '2026-10-06 20:45', 'Royal Canin Kitten 2kg',                       '99100001',    '',            '185000', '1'),
    ('DMY2610A004', '2026-10-05 11:30', 'Royal Canin Persian Adult 2kg',                '99100002',    '',            '190000', '1'),
    ('DMY2610A005', '2026-10-08 16:05', 'Royal Canin Persian Adult 2kg',                '99100002',    '',            '190000', '1'),
    ('DMY2610A006', '2026-10-09 10:00', 'Royal Canin Mini Adult 2kg',                   '99100007',    '',            '210000', '1'),
    -- unmatched: wait for review
    ('DMY2610B001', '2026-10-02 13:15', 'Royal Canin Kitten 2 Kg Makanan Kucing Anak',  'SHP-KIT-2KG', '',            '179000', '1'),
    ('DMY2610B002', '2026-10-05 08:40', 'Royal Canin Kitten 2 Kg Makanan Kucing Anak',  'SHP-KIT-2KG', '',            '179000', '2'),
    ('DMY2610B003', '2026-10-12 19:20', 'Royal Canin Kitten 2 Kg Makanan Kucing Anak',  'SHP-KIT-2KG', '',            '179000', '1'),
    ('DMY2610C001', '2026-10-03 10:05', 'Royal Canin Mother and Baby Cat 2kg',          '99100204',    '',            '205000', '1'),
    ('DMY2610C002', '2026-10-10 15:30', 'Royal Canin Mother and Baby Cat 2kg',          '99100204',    '',            '205000', '1'),
    ('DMY2610D001', '2026-10-07 12:00', 'RC Indoor 27 Adult Cat Food 2kg',              'RC-IN27-2KG', '',            '195000', '1'),
    ('DMY2610D002', '2026-10-11 18:10', 'RC Indoor 27 Adult Cat Food 2kg',              'RC-IN27-2KG', '',            '195000', '1'),
    ('DMY2610E001', '2026-10-13 09:45', 'Royal Canin Persian Adult 2kg Promo Bonus Pouch', null,        'Paket Hemat', '215000', '1')
) as v(order_no, ts, name, sku, var, price, qty)
join log_etl_run r on r.upload_id = 'dummy000-0000-4000-8000-000000000003';

insert into stg_lazada (order_number, status, create_time, seller_sku, lazada_sku, item_name, variation,
                        paid_price, unit_price, source_file, source_row_no, load_run_id)
select v.order_no, 'delivered', v.ts, v.seller, v.lzd, v.name, '', v.price, v.price,
       'DUMMY_lazada_orders_2026-10.xlsx', row_number() over (order by v.order_no), r.run_id
from (values
    ('DMYLZ0001', '04 Oct 2026 10:12', 'LZD_99100002', '4000123402', 'Royal Canin Persian Adult 2kg',                 '188000'),
    ('DMYLZ0002', '08 Oct 2026 21:03', 'LZD_99100002', '4000123402', 'Royal Canin Persian Adult 2kg',                 '188000'),
    ('DMYLZ0003', '05 Oct 2026 13:40', 'LZD_99100505', '4000123499', 'ROYAL CANIN Maxi Adult Dog Food 4 kg',          '455000'),
    ('DMYLZ0004', '11 Oct 2026 08:15', 'LZD_99100505', '4000123499', 'ROYAL CANIN Maxi Adult Dog Food 4 kg',          '455000'),
    ('DMYLZ0005', '09 Oct 2026 17:25', 'LZD_99100606', '4000123498', 'Royal Canin Mini Starter Mother & Babydog 1kg', '98000')
) as v(order_no, ts, seller, lzd, name, price)
join log_etl_run r on r.upload_id = 'dummy000-0000-4000-8000-000000000004';

-- 8. review queue: log_sku_match -------------------------------------------------------------
insert into log_sku_match (run_id, upload_id, channel_id, merchant_sku, sku_code, seller_sku, product_name, variation,
                           first_order_at, last_order_at, order_line_count, suggested_sku_id, suggested_name,
                           similarity_score, candidates, status)
select r.run_id, r.upload_id, c.channel_id, v.merchant, v.sku_code, v.seller, v.name, v.var,
       v.first_at::timestamptz, v.last_at::timestamptz, v.lines,
       pg_temp.sid(v.c1), (select product_name from m_sku where master_sku = v.c1), v.s1,
       jsonb_build_array(pg_temp.cand(v.c1, v.s1), pg_temp.cand(v.c2, v.s2), pg_temp.cand(v.c3, v.s3)), 'PENDING'
from (values
    -- upload 3 (Shopee): merchant SKU = SHP_ + md5(name|variation)[:12]
    ('dummy000-0000-4000-8000-000000000003', 'SHOPEE', pg_temp.shp('Royal Canin Kitten 2 Kg Makanan Kucing Anak', ''),
        'KIT-2KG',      'SHP-KIT-2KG', 'Royal Canin Kitten 2 Kg Makanan Kucing Anak', '',
        '2026-10-02 13:15+07', '2026-10-12 19:20+07', 3, '99100001', 0.9120, '99100010', 0.6140, '99100004', 0.5710),
    ('dummy000-0000-4000-8000-000000000003', 'SHOPEE', pg_temp.shp('Royal Canin Mother and Baby Cat 2kg', ''),
        '99100204',     '99100204',    'Royal Canin Mother and Baby Cat 2kg',          '',
        '2026-10-03 10:05+07', '2026-10-10 15:30+07', 2, '99100004', 0.8450, '99100002', 0.6020, '99100001', 0.5610),
    ('dummy000-0000-4000-8000-000000000003', 'SHOPEE', pg_temp.shp('RC Indoor 27 Adult Cat Food 2kg', ''),
        'RC-IN27-2KG',  'RC-IN27-2KG', 'RC Indoor 27 Adult Cat Food 2kg',             '',
        '2026-10-07 12:00+07', '2026-10-11 18:10+07', 2, '99100003', 0.6630, '99100007', 0.5870, '99100002', 0.5560),
    ('dummy000-0000-4000-8000-000000000003', 'SHOPEE', pg_temp.shp('Royal Canin Persian Adult 2kg Promo Bonus Pouch', 'Paket Hemat'),
        '',             null,          'Royal Canin Persian Adult 2kg Promo Bonus Pouch', 'Paket Hemat',
        '2026-10-13 09:45+07', '2026-10-13 09:45+07', 1, '99100002', 0.7210, '99100010', 0.6240, '99100001', 0.5920),
    -- upload 4 (Lazada): merchant SKU = lazada_sku
    ('dummy000-0000-4000-8000-000000000004', 'LAZADA', '4000123499',
        '99100505',     'LZD_99100505', 'ROYAL CANIN Maxi Adult Dog Food 4 kg',        '',
        '2026-10-05 13:40+07', '2026-10-11 08:15+07', 2, '99100005', 0.8830, '99100008', 0.6110, '99100007', 0.5740),
    ('dummy000-0000-4000-8000-000000000004', 'LAZADA', '4000123498',
        '99100606',     'LZD_99100606', 'Royal Canin Mini Starter Mother & Babydog 1kg', '',
        '2026-10-09 17:25+07', '2026-10-09 17:25+07', 1, '99100006', 0.8040, '99100007', 0.6350, '99100004', 0.5810)
) as v(upload_id, ch, merchant, sku_code, seller, name, var, first_at, last_at, lines, c1, s1, c2, s2, c3, s3)
join log_etl_run r on r.upload_id = v.upload_id
join m_channel c on c.channel_code = v.ch;

-- reviewed in the past: MAPPED by a person, CREATED_NEW by the pipeline
insert into log_sku_match (run_id, upload_id, channel_id, merchant_sku, sku_code, seller_sku, product_name, variation,
                           first_order_at, last_order_at, order_line_count, suggested_sku_id, suggested_name,
                           similarity_score, candidates, status, resolved_sku_id, resolved_by, resolved_at)
select r.run_id, r.upload_id, c.channel_id, pg_temp.shp('Royal Canin Mini Adult Dog 2 Kg', ''), 'MINI-AD-2', 'MINI-AD-2',
       'Royal Canin Mini Adult Dog 2 Kg', '', '2026-09-10 11:05+07', '2026-09-28 16:40+07', 4,
       pg_temp.sid('99100007'), 'Royal Canin Mini Adult 2kg', 0.8230,
       jsonb_build_array(pg_temp.cand('99100007', 0.8230), pg_temp.cand('99100006', 0.6340), pg_temp.cand('99100008', 0.5760)),
       'MAPPED', pg_temp.sid('99100007'), 'dummy.reviewer', '2026-10-01 15:30+07'
from log_etl_run r join m_channel c on c.channel_code = 'SHOPEE'
where r.upload_id = 'dummy000-0000-4000-8000-000000000001';

insert into log_sku_match (run_id, upload_id, channel_id, merchant_sku, sku_code, seller_sku, product_name, variation,
                           first_order_at, last_order_at, order_line_count, candidates, status,
                           resolved_sku_id, resolved_by, resolved_at)
select r.run_id, r.upload_id, c.channel_id, '1731000000099', '99100013', 'TKP_99100013',
       'Royal Canin Hairball Care Adult 2kg', '', '2026-09-14 10:00+07', '2026-09-29 18:20+07', 5, '[]'::jsonb,
       'CREATED_NEW', pg_temp.sid('99100013'), 'auto', '2026-10-02 10:05+07'
from log_etl_run r join m_channel c on c.channel_code = 'TIKTOK'
where r.upload_id = 'dummy000-0000-4000-8000-000000000002';

-- pending counts the DAG would have written to the upload's meta data
update public.upload_progress u
set meta_data = (u.meta_data::jsonb || jsonb_build_object(
        'sku_review_pending', (select count(*) from log_sku_match m where m.upload_id = u.upload_id and m.status = 'PENDING'),
        'sku_review_run_id',  (select r.run_id from log_etl_run r where r.upload_id = u.upload_id)))::json
where u.upload_id in ('dummy000-0000-4000-8000-000000000003', 'dummy000-0000-4000-8000-000000000004');

commit;

-- summary (search_path set by `set local` ended with the transaction)
set search_path = royal_canin, public;
select 'm_sku' as t, count(*) from m_sku where dq_flag like '%dummy_seed%'
union all select 'm_sku_alias', count(*) from m_sku_alias a join m_sku s using (sku_id) where s.dq_flag like '%dummy_seed%'
union all select 'm_platform_sku', count(*) from m_platform_sku p join m_sku s using (sku_id) where s.dq_flag like '%dummy_seed%'
union all select 'm_sku_history', count(*) from m_sku_history h join m_sku s using (sku_id) where s.dq_flag like '%dummy_seed%'
union all select 'm_sku_bundle', count(*) from m_sku_bundle where bundle_sku_id = pg_temp.sid('99100012')
union all select 'upload_progress', count(*) from public.upload_progress where upload_id like 'dummy000-%'
union all select 'log_etl_run', count(*) from log_etl_run where upload_id like 'dummy000-%'
union all select 'stg_shopee', count(*) from stg_shopee where source_file like 'DUMMY%'
union all select 'stg_lazada', count(*) from stg_lazada where source_file like 'DUMMY%'
union all select 'log_sku_match ' || status, count(*) from log_sku_match where upload_id like 'dummy000-%' group by status;
