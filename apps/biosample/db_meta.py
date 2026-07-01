"""BioSample DB 固有の取得関数（R0091 等）。

共通 DB fetch のうち biosample DB（mass.*）に固有のクエリはここに置く。
account/BioProject 系は common/db_meta（ddbj 実装の re-export）を使う。
"""


def fetch_registered_locus_tag_prefixes(bs_conn):
    """biosample DB 登録済みの locus_tag_prefix -> {submission_id, ...} を返す（R0091）。

    Ruby `get_all_locus_tag_prefix` 準拠:
      mass.attribute JOIN mass.sample、attribute_name='locus_tag_prefix'、空値除外、
      status_id 5600/5700（削除/取消相当）を除外。
    """
    q = """
        SELECT smp.submission_id, attr.attribute_value
        FROM mass.attribute attr
        JOIN mass.sample smp USING (smp_id)
        WHERE attr.attribute_name = 'locus_tag_prefix' AND attr.attribute_value <> ''
          AND (smp.status_id IS NULL OR smp.status_id NOT IN (5600, 5700))
    """
    result = {}
    with bs_conn.cursor() as cur:
        cur.execute(q)
        for submission_id, prefix in cur.fetchall():
            if prefix:
                result.setdefault(prefix.strip(), set()).add(submission_id)
    return result
