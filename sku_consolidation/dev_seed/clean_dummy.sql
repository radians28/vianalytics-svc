-- Removes everything seed_dummy.sql created (and nothing else). DEV DATABASES ONLY.
--
--   docker exec -i autobahn-postgres psql -v ON_ERROR_STOP=1 -U postgres -d vianalytics \
--       < sku_consolidation/dev_seed/clean_dummy.sql
--
-- Fails on a foreign key if a real pipeline run has since attached its own rows to a dummy SKU
-- (for example an alias or listing added by process_sku); resolve those first.

\set ON_ERROR_STOP on
begin;
set local search_path = royal_canin, public;

create temp table _d on commit drop as
    select sku_id from m_sku where dq_flag like '%dummy_seed%';
create temp table _r on commit drop as
    select run_id from log_etl_run where upload_id like 'dummy000-%';

delete from log_sku_match
 where upload_id like 'dummy000-%'
    or run_id in (select run_id from _r)
    or suggested_sku_id in (select sku_id from _d)
    or resolved_sku_id in (select sku_id from _d);
delete from stg_shopee where source_file like 'DUMMY%' or load_run_id in (select run_id from _r);
delete from stg_lazada where source_file like 'DUMMY%' or load_run_id in (select run_id from _r);
delete from log_dq_issue where run_id in (select run_id from _r);
delete from log_etl_step where run_id in (select run_id from _r);
delete from log_etl_run  where run_id in (select run_id from _r);

delete from m_sku_history
 where sku_id in (select sku_id from _d)
    or platform_sku_id in (select platform_sku_id from m_platform_sku where sku_id in (select sku_id from _d));
delete from m_sku_bundle
 where bundle_sku_id in (select sku_id from _d) or component_sku_id in (select sku_id from _d);
delete from m_platform_sku where sku_id in (select sku_id from _d);
delete from m_sku_alias    where sku_id in (select sku_id from _d);
delete from m_sku          where sku_id in (select sku_id from _d);

delete from public.upload_progress where upload_id like 'dummy000-%';

commit;
