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


def fetch_authorized_bp_submissions(bp_conn, dra_conn, account_id):
    """account が参照できる BioProject **submission id（PSUBxxxxxx）** の集合を返す（R0006 用）。

    bioproject_id 属性は PRJDB だけでなく PSUB（登録前の submission id）で書かれることがあるため、
    PRJDB（fetch_authorized_accessions）に加えて次の PSUB も「参照可」として扱う:
      - account 自身が登録した BioProject submission（mass.submission.submitter_id 一致）
      - DRA ext_permit で外部参照許可された PSUB（drmdb。ANN0422 と同じ許可元）
    """
    psubs = set()
    if not account_id:
        return psubs
    if bp_conn:
        with bp_conn.cursor() as cur:
            cur.execute(
                "SELECT submission_id FROM mass.submission JOIN mass.project USING(submission_id) "
                "WHERE submitter_id = %s", (account_id,))
            for (sid,) in cur.fetchall():
                if sid:
                    psubs.add(str(sid).strip().upper())
    if dra_conn:
        with dra_conn.cursor() as cur:
            cur.execute(
                "SELECT ref_name FROM mass.ext_permit JOIN mass.ext_entity USING(ext_id) "
                "WHERE submitter_id = %s AND acc_type = 'PSUB'", (account_id,))
            for (ref,) in cur.fetchall():
                if ref:
                    psubs.add(str(ref).strip().upper())
    return psubs
