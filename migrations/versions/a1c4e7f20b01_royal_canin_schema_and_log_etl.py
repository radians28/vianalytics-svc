"""royal_canin schema, helper functions and log_etl tables

Revision ID: a1c4e7f20b01
Revises: 7c1d2e4f9a10
Create Date: 2026-11-04 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c4e7f20b01'
down_revision = '7c1d2e4f9a10'
branch_labels = None
depends_on = None

SCHEMA = 'royal_canin'


def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS royal_canin")

    # Wall-clock times in the marketplace files are WIB; keep the DB on Asia/Jakarta.
    op.execute("SET TIME ZONE 'Asia/Jakarta'")
    op.execute("""
        DO $do$
        BEGIN
            EXECUTE format('ALTER DATABASE %I SET timezone = %L', current_database(), 'Asia/Jakarta');
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'No privilege to ALTER DATABASE %: ask a DBA to set timezone = Asia/Jakarta', current_database();
        END
        $do$
    """)

    # Jam di file marketplace = jam dinding WIB tanpa offset. Nilai kosong / '-' -> NULL.
    op.execute("""
        CREATE OR REPLACE FUNCTION royal_canin.to_jakarta_ts(p_value text, p_format text)
        RETURNS timestamp with time zone
        LANGUAGE sql STABLE AS $function$
            SELECT CASE WHEN p_value IS NULL OR btrim(p_value) IN ('', '-') THEN NULL
                        ELSE to_timestamp(btrim(p_value), p_format)::timestamp AT TIME ZONE 'Asia/Jakarta' END
        $function$
    """)
    op.execute("COMMENT ON FUNCTION royal_canin.to_jakarta_ts(text, text) IS "
               "'parse jam dinding WIB dari file mentah -> timestamptz; format: m_channel.order_ts_format'")

    op.execute("""
        CREATE OR REPLACE FUNCTION royal_canin.jakarta_date(p_ts timestamp with time zone)
        RETURNS date
        LANGUAGE sql IMMUTABLE AS $function$
            SELECT (p_ts AT TIME ZONE 'Asia/Jakarta')::date
        $function$
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION royal_canin.set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $function$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $function$
    """)

    op.create_table(
        'log_etl_run',
        sa.Column('run_id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('finished_at', sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('status', sa.Text(), nullable=False, server_default=sa.text("'RUNNING'")),
        sa.Column('channels', sa.Text()),
        sa.Column('source_files', sa.Text()),
        sa.Column('triggered_by', sa.Text()),
        sa.Column('upload_id', sa.String(length=36), comment='file upload (public.upload_progress) yang diproses run ini; NULL untuk run batch/offline. Tabel upload_progress dibuat oleh migrasi vianalytics-svc, jadi jalankan migrasi itu sebelum DDL ini'),
        sa.Column('error_message', sa.Text()),
        sa.PrimaryKeyConstraint('run_id', name='pk_log_etl_run'),
        sa.CheckConstraint("status IN ('RUNNING','SUCCESS','FAILED')", name='ck_log_etl_run_1'),
        sa.ForeignKeyConstraint(['upload_id'], ['public.upload_progress.upload_id'], name='fk_log_etl_run_upload', ondelete='SET NULL'),
        schema=SCHEMA,
        comment='1 baris per eksekusi ETL',
    )
    op.create_index('ix_log_etl_run_upload_id', 'log_etl_run', ['upload_id'], unique=False, schema=SCHEMA)

    op.create_table(
        'log_etl_step',
        sa.Column('step_id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('run_id', sa.BigInteger(), nullable=False),
        sa.Column('step_seq', sa.Integer(), nullable=False),
        sa.Column('step_name', sa.Text(), nullable=False),
        sa.Column('channel_code', sa.Text()),
        sa.Column('target_table', sa.Text()),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('rows_read', sa.Integer()),
        sa.Column('rows_inserted', sa.Integer()),
        sa.Column('rows_updated', sa.Integer()),
        sa.Column('rows_rejected', sa.Integer()),
        sa.Column('message', sa.Text()),
        sa.Column('logged_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('step_id', name='pk_log_etl_step'),
        sa.UniqueConstraint('run_id', 'step_seq', name='uq_log_etl_step_run_id_step_seq'),
        sa.CheckConstraint("status IN ('RUNNING','SUCCESS','FAILED','SKIPPED')", name='ck_log_etl_step_1'),
        sa.ForeignKeyConstraint(['run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_log_etl_step_run_id'),
        schema=SCHEMA,
        comment='1 baris per langkah / tabel',
    )


def downgrade():
    op.drop_table('log_etl_step', schema=SCHEMA)
    op.drop_table('log_etl_run', schema=SCHEMA)
    op.execute("DROP FUNCTION IF EXISTS royal_canin.set_updated_at()")
    op.execute("DROP FUNCTION IF EXISTS royal_canin.jakarta_date(timestamp with time zone)")
    op.execute("DROP FUNCTION IF EXISTS royal_canin.to_jakarta_ts(text, text)")
    op.execute("DROP SCHEMA IF EXISTS royal_canin")
