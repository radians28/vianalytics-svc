# Indonesian region and postal code reference

Used to clean `royal_canin.m_city` (one canonical row per kabupaten/kota) and fill `royal_canin.m_zipcode`
(one kabupaten/kota per postal code). Loaded by `airflow/scripts/city_cleanup.py` in the root repo.

| File | Rows | Columns |
|---|---|---|
| `ref_city.csv` | 514 kabupaten/kota | `city_code` (Kemendagri, e.g. `32.75`), `city_name`, `city_type` (`KOTA`/`KABUPATEN`), `province_code`, `province_name` |
| `ref_zipcode.csv` | 10,632 postal codes | `zip_code`, `city_code`, `villages` (desa/kelurahan with this code in that city), `dq_flag`, `other_city_codes` |

A postal code that the source lists in more than one kabupaten/kota goes to the one with the most
villages (ties: lowest code). It gets `dq_flag = multi_city_in_reference`, and the others are listed in
`other_city_codes` as `code:villages`.

## Source
Kepmendagri No. 300.2.2-2138 Tahun 2025, as compiled by cahya dsn (MIT License):
- regions: https://github.com/cahyadsn/wilayah, `db/wilayah.sql` @ `c2eff0881e3c75b8822f8c84ea9d23affc11aadb`
- postal codes: https://github.com/cahyadsn/wilayah_kodepos, `db/wilayah_kodepos.sql` @ `ba8497156c5cc9bcbfc527f7b8875d403eda2354`

Extracted on 2026-11-13: level-2 codes (`NN.NN`) from `wilayah`, and postal codes per village
(`NN.NN.NN.NNNN`) from `wilayah_kodepos`, grouped by the village's kabupaten/kota.
