"""Layer LOG: ETL runs, steps, data-quality issues and SKU name-match review queue.

Generated from sku_consolidation/ddl_royal_canin.sql; keep both in sync until the SQL file is retired.
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.extensions import db
from app.models.royal_canin import SCHEMA


class LogEtlRun(db.Model):
    __tablename__ = 'log_etl_run'
    __table_args__ = (
        sa.PrimaryKeyConstraint('run_id', name='pk_log_etl_run'),
        sa.CheckConstraint("status IN ('RUNNING','SUCCESS','FAILED')", name='ck_log_etl_run_1'),
        sa.ForeignKeyConstraint(['upload_id'], ['upload_progress.upload_id'], name='fk_log_etl_run_upload', ondelete='SET NULL'),
        sa.Index('ix_log_etl_run_upload_id', 'upload_id'),
        {'schema': SCHEMA, 'comment': '1 baris per eksekusi ETL'},
    )

    run_id = db.Column(sa.BigInteger(), sa.Identity(always=False), nullable=False)
    started_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    finished_at = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    status = db.Column(sa.Text(), nullable=False, server_default=sa.text("'RUNNING'"))
    channels = db.Column(sa.Text())
    source_files = db.Column(sa.Text())
    triggered_by = db.Column(sa.Text())
    upload_id = db.Column(sa.String(length=36), comment='file upload (public.upload_progress) yang diproses run ini; NULL untuk run batch/offline. Tabel upload_progress dibuat oleh migrasi vianalytics-svc, jadi jalankan migrasi itu sebelum DDL ini')
    error_message = db.Column(sa.Text())


class LogEtlStep(db.Model):
    __tablename__ = 'log_etl_step'
    __table_args__ = (
        sa.PrimaryKeyConstraint('step_id', name='pk_log_etl_step'),
        sa.UniqueConstraint('run_id', 'step_seq', name='uq_log_etl_step_run_id_step_seq'),
        sa.CheckConstraint("status IN ('RUNNING','SUCCESS','FAILED','SKIPPED')", name='ck_log_etl_step_1'),
        sa.ForeignKeyConstraint(['run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_log_etl_step_run_id'),
        {'schema': SCHEMA, 'comment': '1 baris per langkah / tabel'},
    )

    step_id = db.Column(sa.BigInteger(), sa.Identity(always=False), nullable=False)
    run_id = db.Column(sa.BigInteger(), nullable=False)
    step_seq = db.Column(sa.Integer(), nullable=False)
    step_name = db.Column(sa.Text(), nullable=False)
    channel_code = db.Column(sa.Text())
    target_table = db.Column(sa.Text())
    status = db.Column(sa.Text(), nullable=False)
    rows_read = db.Column(sa.Integer())
    rows_inserted = db.Column(sa.Integer())
    rows_updated = db.Column(sa.Integer())
    rows_rejected = db.Column(sa.Integer())
    message = db.Column(sa.Text())
    logged_at = db.Column(sa.DateTime(timezone=True), server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')


class LogDqIssue(db.Model):
    __tablename__ = 'log_dq_issue'
    __table_args__ = (
        sa.PrimaryKeyConstraint('issue_id', name='pk_log_dq_issue'),
        sa.CheckConstraint("status IN ('OPEN','CONFIRMED','FIXED','IGNORED')", name='ck_log_dq_issue_1'),
        sa.ForeignKeyConstraint(['run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_log_dq_issue_run_id'),
        sa.ForeignKeyConstraint(['sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_log_dq_issue_sku_id'),
        sa.Index('ix_log_dq_issue_run_id', 'run_id'),
        sa.Index('ix_log_dq_issue_sku_id', 'sku_id'),
        {'schema': SCHEMA, 'comment': 'temuan data quality untuk data steward'},
    )

    issue_id = db.Column(sa.BigInteger(), sa.Identity(always=False), nullable=False)
    run_id = db.Column(sa.BigInteger())
    source_table = db.Column(sa.Text(), nullable=False)
    dq_flag = db.Column(sa.Text(), nullable=False)
    record_key = db.Column(sa.Text())
    sku_id = db.Column(sa.Integer())
    detail = db.Column(sa.Text())
    status = db.Column(sa.Text(), nullable=False, server_default=sa.text("'OPEN'"))
    logged_at = db.Column(sa.DateTime(timezone=True), server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')


class LogSkuMatch(db.Model):
    __tablename__ = 'log_sku_match'
    __table_args__ = (
        sa.PrimaryKeyConstraint('match_id', name='pk_log_sku_match'),
        sa.CheckConstraint("status IN ('PENDING','MAPPED','CREATED_NEW')", name='ck_log_sku_match_1'),
        sa.CheckConstraint('similarity_score BETWEEN 0 AND 1', name='ck_log_sku_match_2'),
        sa.CheckConstraint("status = 'PENDING' OR resolved_sku_id IS NOT NULL", name='ck_log_sku_match_3'),
        sa.CheckConstraint("resolution IS NULL OR resolution IN ('manual','sibling','auto_created','auto_mapped')", name='ck_log_sku_match_4'),
        sa.ForeignKeyConstraint(['run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_log_sku_match_run_id'),
        sa.ForeignKeyConstraint(['upload_id'], ['upload_progress.upload_id'], name='fk_log_sku_match_upload', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['channel_id'], ['royal_canin.m_channel.channel_id'], name='fk_log_sku_match_channel_id'),
        sa.ForeignKeyConstraint(['suggested_sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_log_sku_match_suggested_sku_id'),
        sa.ForeignKeyConstraint(['resolved_sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_log_sku_match_resolved_sku_id'),
        sa.Index('uq_log_sku_match_pending', 'channel_id', 'merchant_sku', 'sku_code', unique=True, postgresql_where=sa.text("status = 'PENDING'")),
        sa.Index('ix_log_sku_match_upload_id', 'upload_id'),
        sa.Index('ix_log_sku_match_status', 'status'),
        sa.Index('ix_log_sku_match_sku_code_pending', 'sku_code', postgresql_where=sa.text("status = 'PENDING' AND sku_code <> ''")),
        {'schema': SCHEMA, 'comment': 'listing baru (seller SKU & SKU platform belum ada di master) dicocokkan berdasarkan nama produk; PENDING = menunggu keputusan di UI (SKU sanitize: petakan ke saran atau buat SKU baru)'},
    )

    match_id = db.Column(sa.BigInteger(), sa.Identity(always=False), nullable=False)
    run_id = db.Column(sa.BigInteger())
    upload_id = db.Column(sa.String(length=36))
    channel_id = db.Column(sa.Integer(), nullable=False)
    merchant_sku = db.Column(sa.Text(), nullable=False)
    sku_code = db.Column(sa.Text(), nullable=False, server_default=sa.text("''"), comment='seller SKU bersih (R1); string kosong bila listing tanpa seller SKU')
    seller_sku = db.Column(sa.Text())
    product_name = db.Column(sa.Text())
    variation = db.Column(sa.Text())
    first_order_at = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    last_order_at = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    order_line_count = db.Column(sa.Integer())
    suggested_sku_id = db.Column(sa.Integer())
    suggested_name = db.Column(sa.Text())
    similarity_score = db.Column(sa.Numeric(precision=5, scale=4), comment='cosine similarity TF-IDF n-gram karakter (3..5) nama ternormalisasi; cocok bila >= 0.55 (jarak <= 0.45)')
    candidates = db.Column(postgresql.JSONB(astext_type=sa.Text()), comment='maks. 3 SKU master terdekat: [{sku_id, sku_master_code, name, score}]')
    status = db.Column(sa.Text(), nullable=False, server_default=sa.text("'PENDING'"), comment='PENDING: menunggu review · MAPPED: dipetakan ke SKU yang ada · CREATED_NEW: dibuat sebagai SKU baru')
    resolved_sku_id = db.Column(sa.Integer())
    resolved_by = db.Column(sa.Text(), comment="'auto' bila tidak ada nama yang mirip dan SKU baru dibuat otomatis oleh DAG, selain itu user yang memutuskan")
    resolved_at = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    resolution = db.Column(sa.Text(), comment='cara diputuskan: manual (user) · sibling (ikut keputusan seller SKU yang sama) · auto_created (DAG membuat SKU baru, baris order sudah dimuat) · auto_mapped (DAG menemukan listing sudah dikenal)')
    created_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    updated_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')


class LogSkuMatchUpload(db.Model):
    __tablename__ = 'log_sku_match_upload'
    __table_args__ = (
        sa.PrimaryKeyConstraint('match_id', 'upload_id', name='pk_log_sku_match_upload'),
        sa.ForeignKeyConstraint(['match_id'], ['royal_canin.log_sku_match.match_id'], name='fk_log_sku_match_upload_match', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['upload_id'], ['upload_progress.upload_id'], name='fk_log_sku_match_upload_upload', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_log_sku_match_upload_run'),
        sa.Index('ix_log_sku_match_upload_upload_id', 'upload_id'),
        {'schema': SCHEMA, 'comment': 'upload yang memuat listing review (log_sku_match); satu baris review bisa menahan beberapa upload'},
    )

    match_id = db.Column(sa.BigInteger(), nullable=False)
    upload_id = db.Column(sa.String(length=36), nullable=False)
    run_id = db.Column(sa.BigInteger())
    order_line_count = db.Column(sa.Integer(), comment='baris order listing ini di upload tsb')
    first_order_at = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    last_order_at = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    created_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')


class LogBundleChange(db.Model):
    __tablename__ = 'log_bundle_change'
    __table_args__ = (
        sa.PrimaryKeyConstraint('change_id', name='pk_log_bundle_change'),
        sa.CheckConstraint("status IN ('PENDING','RUNNING','DONE','FAILED','SKIPPED')", name='ck_log_bundle_change_1'),
        sa.ForeignKeyConstraint(['run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_log_bundle_change_run_id'),
        sa.ForeignKeyConstraint(['bundle_sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_log_bundle_change_bundle_sku_id'),
        sa.Index('ix_log_bundle_change_status', 'status'),
        sa.Index('ix_log_bundle_change_run_id', 'run_id'),
        {'schema': SCHEMA, 'comment': 'perubahan komponen bundle per upload SKU bundling, dan status pemecahan ulang baris order yang sudah dimuat (DAG reconsolidate_bundle_orders)'},
    )

    change_id = db.Column(sa.BigInteger(), sa.Identity(always=False), nullable=False)
    run_id = db.Column(sa.BigInteger(), nullable=False, comment='log_etl_run upload SKU bundling')
    bundle_sku_id = db.Column(sa.Integer(), nullable=False)
    old_bom = db.Column(postgresql.JSONB(astext_type=sa.Text()), comment='komponen sebelum upload [{seq, component_sku_id, qty, price_ratio, dq_flag}]; NULL bila SKU belum bundle')
    new_bom = db.Column(postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='komponen setelah upload, format sama')
    status = db.Column(sa.Text(), nullable=False, server_default=sa.text("'PENDING'"), comment='PENDING: baris order lama belum dipecah ulang · RUNNING · DONE · FAILED · SKIPPED (tidak diminta)')
    lines_rebuilt = db.Column(sa.Integer(), comment='baris order asli yang dipecah ulang')
    lines_mismatch = db.Column(sa.Integer(), comment='baris yang tidak bisa dibangun ulang dari komponen lama (dq rebundle_mismatch)')
    orders_touched = db.Column(sa.Integer())
    message = db.Column(sa.Text())
    created_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    processed_at = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
