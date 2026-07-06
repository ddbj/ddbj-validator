"""BioSample DB 固有の取得関数（R0091 等）。

共通 DB fetch のうち biosample DB（mass.*）に固有のクエリはここに置く。
account/BioProject 系は common/db_meta（ddbj 実装の re-export）を使う。
"""
import re

_SAMD_RE = re.compile(r"SAMD\d+", re.IGNORECASE)


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


def fetch_authorized_bp_submissions(bp_conn, dra_conn, account_id, referenced=None):
    """account が参照できる BioProject **submission id（PSUBxxxxxx）** の集合を返す（R0006 用）。

    bioproject_id 属性は PRJDB だけでなく PSUB（登録前の submission id）で書かれることがあるため、
    PRJDB（fetch_authorized_refs）に加えて次の PSUB も「参照可」として扱う:
      - account 自身が登録した BioProject submission（mass.submission.submitter_id 一致）
      - DRA ext_permit で外部参照許可された PSUB（drmdb。ANN0422 と同じ許可元）

    `referenced`（submission が参照する PSUB 集合）を渡すと、それに絞って判定する
    （アカウント保有全 PSUB を取得しない＝大規模アカウントの固定コスト回避）。
    """
    psubs = set()
    if not account_id:
        return psubs
    ref = {str(r).strip().upper() for r in referenced} if referenced is not None else None
    if ref is not None and not ref:
        return psubs  # 参照 PSUB が無ければ問い合わせ不要
    ref_list = sorted(ref) if ref is not None else None
    if bp_conn:
        with bp_conn.cursor() as cur:
            if ref_list is not None:
                cur.execute(
                    "SELECT submission_id FROM mass.submission JOIN mass.project USING(submission_id) "
                    "WHERE submitter_id = %s AND upper(submission_id) = ANY(%s)",
                    (account_id, ref_list))
            else:
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
            for (ref_name,) in cur.fetchall():
                if ref_name:
                    val = str(ref_name).strip().upper()
                    if ref is None or val in ref:
                        psubs.add(val)
    return psubs


def fetch_authorized_refs(bp_conn, bs_conn, dra_conn, account_id, ref_projects, ref_samds):
    """account が「登録した」または「ext_permit で外部参照許可された」アクセッションのうち、
    **submission が実際に参照するものだけ** に絞って所属判定する（R0006/R0129/R0095 用）。

    全件フェッチ（apps/ddbj/db_auth.fetch_authorized_accessions）と異なり、参照集合を
    `= ANY(...)` で絞り込むため **アカウント保有数に依存せず高速**。BioSample は DRR を使わないため
    DRA（自身の DRR / DRA permit）は問い合わせない。
    戻り値: (auth_projects, auth_samds)。いずれも「参照 ∩ 所属」で値は大文字。
    """
    auth_projects, auth_samds = set(), set()
    if not account_id:
        return auth_projects, auth_samds

    # 参照 PRJDB の数値部（'PRJDB'+counter の counter）／参照 SAMD（大文字・DB は正規化済み大文字）
    ref_prjdb_nums = sorted({int(p[5:]) for p in ref_projects
                             if str(p).upper().startswith("PRJDB") and str(p)[5:].isdigit()})
    ref_samd_list = sorted({str(s).upper() for s in ref_samds}) if ref_samds else []

    # --- 1. account 自身が登録した PRJDB（参照分のみ）---
    if bp_conn and ref_prjdb_nums:
        with bp_conn.cursor() as cur:
            cur.execute(
                "SELECT 'PRJDB' || project_id_counter "
                "FROM mass.submission JOIN mass.project USING(submission_id) "
                "WHERE submitter_id = %s AND project_id_counter = ANY(%s)",
                (account_id, ref_prjdb_nums))
            for (acc,) in cur.fetchall():
                if acc:
                    auth_projects.add(str(acc).strip().upper())

    # --- 2. account 自身が登録した SAMD（参照分のみ）---
    if bs_conn and ref_samd_list:
        with bs_conn.cursor() as cur:
            cur.execute(
                "SELECT accession_id "
                "FROM mass.submission JOIN mass.sample USING(submission_id) "
                "JOIN mass.accession USING(smp_id) "
                "WHERE submitter_id = %s AND accession_id = ANY(%s)",
                (account_id, ref_samd_list))
            for (acc,) in cur.fetchall():
                if acc:
                    auth_samds.add(str(acc).strip().upper())

    # --- 3. ext_permit 経由の外部参照許可（PSUB→PRJDB / SSUB→SAMD、参照分のみ）---
    permitted_psubs, permitted_ssubs = [], []
    if dra_conn and (ref_prjdb_nums or ref_samd_list):
        with dra_conn.cursor() as cur:
            cur.execute(
                "SELECT acc_type, ref_name FROM mass.ext_permit JOIN mass.ext_entity USING(ext_id) "
                "WHERE submitter_id = %s", (account_id,))
            for acc_type, ref_name in cur.fetchall():
                t = str(acc_type).strip().upper() if acc_type else ""
                rn = str(ref_name).strip() if ref_name else ""
                if t == "PSUB":
                    permitted_psubs.append(rn)
                elif t == "SSUB":
                    permitted_ssubs.append(rn)

    # 許可 PSUB -> PRJDB（参照分のみ）
    if bp_conn and permitted_psubs and ref_prjdb_nums:
        with bp_conn.cursor() as cur:
            cur.execute(
                "SELECT 'PRJDB' || project_id_counter "
                "FROM mass.submission JOIN mass.project USING(submission_id) "
                "WHERE submission_id = ANY(%s) AND project_id_counter = ANY(%s)",
                (permitted_psubs, ref_prjdb_nums))
            for (acc,) in cur.fetchall():
                if acc:
                    auth_projects.add(str(acc).strip().upper())

    # 許可 SSUB(smp_id) -> SAMD（参照分のみ）
    if bs_conn and permitted_ssubs and ref_samd_list:
        smp_ids = [int(x) for x in permitted_ssubs if str(x).isdigit()]
        if smp_ids:
            with bs_conn.cursor() as cur:
                cur.execute(
                    "SELECT accession_id FROM mass.accession "
                    "WHERE smp_id = ANY(%s) AND accession_id = ANY(%s)",
                    (smp_ids, ref_samd_list))
                for (acc,) in cur.fetchall():
                    if acc:
                        auth_samds.add(str(acc).strip().upper())

    return auth_projects, auth_samds
