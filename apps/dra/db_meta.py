"""DRA DB 固有の取得関数（account/DB 依存ルール用）。

Ruby `ddbj_db_validator.rb` 準拠。status_id 5600/5700 は除外。失敗時は None/空で graceful degrade。
- fetch_submitter_center_name: submitterdb.mass.organization.center_name（DRA_R0004）。
- fetch_account_bioprojects: account 所有 BioProject（PRJDB, 参照分のみ）（DRA_R0015）。
- fetch_account_biosamples: account 所有 BioSample（SAMD, 参照分のみ）（DRA_R0016）。
- fetch_account_object_names: account の既存 DRA object 名（alias）（DRA_R0009）。※ DRA スキーマ未確定のため best-effort。
"""
_EXCLUDED_STATUS = (5600, 5700)


def fetch_submitter_center_name(sub_conn, account):
    if not sub_conn or not account:
        return None
    with sub_conn.cursor() as cur:
        cur.execute("SELECT center_name FROM mass.organization WHERE submitter_id = %s", (account,))
        row = cur.fetchone()
    return (row[0].strip() if row and row[0] else None)


def _permit_refs(dra_conn, account, acc_type):
    """DRA permit（mass.ext_permit）で account に参照許可された ref_name 集合（acc_type 別。best-effort）。"""
    if not dra_conn or not account:
        return set()
    try:
        with dra_conn.cursor() as cur:
            cur.execute(
                "SELECT ref_name FROM mass.ext_permit JOIN mass.ext_entity USING(ext_id) "
                "WHERE submitter_id = %s AND acc_type = %s", (account, acc_type))
            return {str(r[0]).strip().upper() for r in cur.fetchall() if r[0]}
    except Exception:
        return set()


def fetch_account_bioprojects(bp_conn, dra_conn, account, ref_prjdbs):
    """参照 PRJDB のうち account 所有 ∪ DRA permit の集合（DRA_R0041/0015）。"""
    owned = set()
    if not account:
        return owned
    nums = sorted({int(p[5:]) for p in ref_prjdbs
                   if str(p).upper().startswith("PRJDB") and str(p)[5:].isdigit()})
    if bp_conn and nums:
        with bp_conn.cursor() as cur:
            cur.execute(
                "SELECT 'PRJDB' || project_id_counter "
                "FROM mass.submission JOIN mass.project USING(submission_id) "
                "WHERE submitter_id = %s AND project_id_counter = ANY(%s)",
                (account, nums))
            for (acc,) in cur.fetchall():
                if acc:
                    owned.add(str(acc).strip().upper())
    owned |= _permit_refs(dra_conn, account, "PRJDB")   # permit（PRJDB）
    return owned


def fetch_account_biosamples(bs_conn, dra_conn, account, ref_samds):
    """参照 SAMD のうち account 所有 ∪ DRA permit の集合（DRA_R0042/0016）。"""
    owned = set()
    if not account:
        return owned
    samd_list = sorted({str(s).strip().upper() for s in ref_samds if s})
    if bs_conn and samd_list:
        with bs_conn.cursor() as cur:
            cur.execute(
                "SELECT accession_id FROM mass.submission JOIN mass.sample USING(submission_id) "
                "JOIN mass.accession USING(smp_id) "
                "WHERE submitter_id = %s AND accession_id = ANY(%s) "
                "AND (mass.sample.status_id IS NULL OR mass.sample.status_id NOT IN %s)",
                (account, samd_list, _EXCLUDED_STATUS))
            for (acc,) in cur.fetchall():
                if acc:
                    owned.add(str(acc).strip().upper())
    owned |= _permit_refs(dra_conn, account, "SAMD")    # permit（SAMD）
    return owned


def fetch_account_runs(dra_conn, account, ref_drrs):
    """参照 DRR のうち account 所有 ∪ DRA permit の集合（DRA_R0043）。

    drmdb の Run テーブルが未確定のため best-effort。所有分が取得できなければ permit のみ、
    どちらも取得不可なら None（=ルールスキップ）を返す。
    """
    if not dra_conn or not account:
        return None
    permit = _permit_refs(dra_conn, account, "DRR")
    owned = None
    drr_list = sorted({str(d).strip().upper() for d in ref_drrs if d})
    try:
        with dra_conn.cursor() as cur:
            cur.execute(
                "SELECT accession_id FROM mass.submission JOIN mass.run USING(submission_id) "
                "JOIN mass.accession USING(run_id) "
                "WHERE submitter_id = %s AND accession_id = ANY(%s)",
                (account, drr_list))
            owned = {str(r[0]).strip().upper() for r in cur.fetchall() if r[0]}
    except Exception:
        owned = None
    if owned is None:
        return (permit if permit else None)
    return owned | permit


def fetch_account_object_names(dra_conn, account):
    """account の既存 DRA object alias 集合（DRA_R0009）。

    DRA(drmdb) の object 名テーブルが未確定のため best-effort。取得できなければ None（=ルールスキップ）。
    """
    if not dra_conn or not account:
        return None
    try:
        with dra_conn.cursor() as cur:
            cur.execute(
                "SELECT alias FROM mass.submission WHERE submitter_id = %s AND alias IS NOT NULL",
                (account,))
            return {r[0].strip() for r in cur.fetchall() if r[0]}
    except Exception:
        return None
