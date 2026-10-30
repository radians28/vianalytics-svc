-- ===========================================================================
-- Relasi royal_canin.log_etl_run -> public.upload_progress
-- Untuk database yang sudah memakai ddl_royal_canin.sql sebelum kolom upload_id
-- ditambahkan. Aman dijalankan ulang. Butuh tabel upload_progress (migrasi
-- vianalytics-svc) sudah ada.
-- ===========================================================================

BEGIN;

ALTER TABLE royal_canin.log_etl_run ADD COLUMN IF NOT EXISTS upload_id varchar(36);

-- Run lama dari Airflow menyimpan upload di triggered_by = 'upload:<upload_id>'
UPDATE royal_canin.log_etl_run r
SET upload_id = substr(r.triggered_by, length('upload:') + 1)
WHERE r.upload_id IS NULL
  AND r.triggered_by LIKE 'upload:%'
  AND EXISTS (SELECT 1 FROM public.upload_progress u
              WHERE u.upload_id = substr(r.triggered_by, length('upload:') + 1));

DO $do$
BEGIN
    ALTER TABLE royal_canin.log_etl_run
        ADD CONSTRAINT fk_log_etl_run_upload FOREIGN KEY (upload_id)
        REFERENCES public.upload_progress (upload_id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN
    NULL;
END
$do$;

CREATE INDEX IF NOT EXISTS ix_log_etl_run_upload_id ON royal_canin.log_etl_run (upload_id);

COMMENT ON COLUMN royal_canin.log_etl_run.upload_id IS 'file upload (public.upload_progress) yang diproses run ini; NULL untuk run batch/offline. Tabel upload_progress dibuat oleh migrasi vianalytics-svc, jadi jalankan migrasi itu sebelum DDL ini';

COMMIT;
