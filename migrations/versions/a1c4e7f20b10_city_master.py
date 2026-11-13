"""city master: m_city canonical (Kemendagri kabupaten/kota), m_city_alias (marketplace wording -> city),
m_zipcode (one city per postal code), t_order.zip_code

Revision ID: a1c4e7f20b10
Revises: a1c4e7f20b09
Create Date: 2026-11-13 19:00:00.000000

Schema only. The data (reference rows, aliases, repointing t_order) is loaded by
airflow/scripts/city_cleanup.py in the root repo from sku_consolidation/reference/.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a1c4e7f20b10'
down_revision = 'a1c4e7f20b09'
branch_labels = None
depends_on = None

SCHEMA = 'royal_canin'
TS_COMMENT = 'timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'
OLD_CITY_COMMENT = 'kota + provinsi sesuai penulisan marketplace (tanpa normalisasi)'
CITY_COMMENT = ('kabupaten/kota kanonik sesuai Kepmendagri (city_code); penulisan marketplace dipetakan lewat '
                'm_city_alias. Baris tanpa city_code = penulisan yang belum bisa dipetakan (dq_flag unresolved)')
MATCH_METHODS = ('zip_majority', 'name_exact', 'name_normalized', 'bare_name_kota', 'manual', 'unresolved')


def upgrade():
    op.add_column('m_city', sa.Column('city_code', sa.Text(), comment='kode Kemendagri kabupaten/kota, mis. 32.75'),
                  schema=SCHEMA)
    op.add_column('m_city', sa.Column('city_type', sa.Text(), comment='KOTA | KABUPATEN'), schema=SCHEMA)
    op.add_column('m_city', sa.Column('province_code', sa.Text(), comment='kode Kemendagri provinsi, mis. 32'),
                  schema=SCHEMA)
    op.add_column('m_city', sa.Column('dq_flag', sa.Text(),
                                      comment='unresolved: penulisan marketplace yang belum cocok dengan referensi'),
                  schema=SCHEMA)
    op.create_check_constraint('ck_m_city_1', 'm_city', "city_type IN ('KOTA','KABUPATEN')", schema=SCHEMA)
    op.create_index('uq_m_city_city_code', 'm_city', ['city_code'], unique=True, schema=SCHEMA,
                    postgresql_where=sa.text('city_code IS NOT NULL'))
    op.create_table_comment('m_city', CITY_COMMENT, existing_comment=OLD_CITY_COMMENT, schema=SCHEMA)

    op.create_table(
        'm_city_alias',
        sa.Column('raw_city_name', sa.Text(), nullable=False, comment='kota persis seperti di file marketplace'),
        sa.Column('raw_province_name', sa.Text(), nullable=False,
                  comment="provinsi persis seperti di file marketplace ('' bila kosong)"),
        sa.Column('city_id', sa.Integer(), nullable=False),
        sa.Column('match_method', sa.Text(), nullable=False,
                  comment='zip_majority: kode pos order · name_exact / name_normalized: nama · bare_name_kota: '
                          'nama tanpa Kota/Kab. dianggap Kota · manual · unresolved: menunjuk baris m_city tanpa city_code'),
        sa.Column('dq_flag', sa.Text(), comment='mis. bare_name_kota, name_zip_conflict'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'),
                  comment=TS_COMMENT),
        sa.PrimaryKeyConstraint('raw_city_name', 'raw_province_name', name='pk_m_city_alias'),
        sa.ForeignKeyConstraint(['city_id'], [f'{SCHEMA}.m_city.city_id'], name='fk_m_city_alias_city_id'),
        sa.CheckConstraint('match_method IN (' + ','.join(f"'{m}'" for m in MATCH_METHODS) + ')',
                           name='ck_m_city_alias_1'),
        schema=SCHEMA,
        comment='penulisan kota/provinsi dari marketplace -> m_city kanonik',
    )
    op.create_index('ix_m_city_alias_city_id', 'm_city_alias', ['city_id'], schema=SCHEMA)

    op.create_table(
        'm_zipcode',
        sa.Column('zip_code', sa.Text(), nullable=False),
        sa.Column('city_id', sa.Integer(), nullable=False),
        sa.Column('dq_flag', sa.Text(),
                  comment='multi_city_in_reference: referensi memuat kode pos ini di >1 kabupaten/kota; '
                          'dipilih yang desanya terbanyak'),
        sa.Column('other_city_ids', postgresql.ARRAY(sa.Integer()),
                  comment='kabupaten/kota lain yang juga memakai kode pos ini menurut referensi; bila penulisan '
                          'kota order menyebut salah satunya, penulisan itu yang dipakai'),
        sa.Column('source', sa.Text(), nullable=False, comment='mis. kepmendagri_2025'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'),
                  comment=TS_COMMENT),
        sa.PrimaryKeyConstraint('zip_code', name='pk_m_zipcode'),
        sa.ForeignKeyConstraint(['city_id'], [f'{SCHEMA}.m_city.city_id'], name='fk_m_zipcode_city_id'),
        sa.CheckConstraint("zip_code ~ '^[0-9]{5}$'", name='ck_m_zipcode_1'),
        schema=SCHEMA,
        comment='kode pos -> satu kabupaten/kota',
    )
    op.create_index('ix_m_zipcode_city_id', 'm_zipcode', ['city_id'], schema=SCHEMA)

    op.add_column('t_order', sa.Column('zip_code', sa.Text(), comment='kode pos pengiriman dari file marketplace (5 digit)'),
                  schema=SCHEMA)


def downgrade():
    op.drop_column('t_order', 'zip_code', schema=SCHEMA)
    op.drop_index('ix_m_zipcode_city_id', table_name='m_zipcode', schema=SCHEMA)
    op.drop_table('m_zipcode', schema=SCHEMA)
    op.drop_index('ix_m_city_alias_city_id', table_name='m_city_alias', schema=SCHEMA)
    op.drop_table('m_city_alias', schema=SCHEMA)
    op.create_table_comment('m_city', OLD_CITY_COMMENT, existing_comment=CITY_COMMENT, schema=SCHEMA)
    op.drop_index('uq_m_city_city_code', table_name='m_city', schema=SCHEMA)
    op.drop_constraint('ck_m_city_1', 'm_city', schema=SCHEMA)
    for col in ('dq_flag', 'province_code', 'city_type', 'city_code'):
        op.drop_column('m_city', col, schema=SCHEMA)
