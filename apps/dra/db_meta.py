"""DRA DB 固有の取得関数（account/DB 依存ルール用）。

参照解決の原則:
- DRA object（Experiment/Run/Analysis）は「アクセッション番号があれば accession、なければ alias」で参照する
  （新規登録時点では accession 未採番のため alias 参照になる）。owned は drmdb.mass.accession_entity から
  alias（＋acc_no があれば accession）を集める。
- BioProject/BioSample は事前採番済みのため accession（PRJDB/SAMD）で照合。
  account 所有（bp/bs DB）∪ DRA permit（ext_permit: PSUB→PRJDB / SSUB→SAMD / DRA→DRR）を「参照可」とする。

status_id 5600/5700 は除外。失敗時は None/空で graceful degrade。
"""
_EXCLUDED_STATUS = (5600, 5700)


def _acc_from_no(acc_type, acc_no):
    """acc_type ＋ acc_no（6 桁ゼロ埋め、7 桁以上はそのまま）で accession を組む。"""
    if acc_no is None:
        return None
    s = str(acc_no).strip()
    if not s.isdigit():
        return None
    return f"{acc_type}{s.zfill(6)}" if len(s) < 7 else f"{acc_type}{s}"


def fetch_submitter_center_name(sub_conn, account):
    """account の組織名を返す（submitterdb.mass.organization.organization）。

    新規登録時にこの organization が submission の center_name として引き写される（編集可）。
    R0004 は metadata の center_name がこれと不一致なら warning（reminder）。
    """
    if not sub_conn or not account:
        return None
    with sub_conn.cursor() as cur:
        cur.execute("SELECT organization FROM mass.organization WHERE submitter_id = %s", (account,))
        row = cur.fetchone()
    return (row[0].strip() if row and row[0] else None)


def _accession_entity(dra_conn, account, kind, acc_type):
    """account の DRA object を accession_entity から取得（alias∪accession の集合）。is_delete 除外。"""
    out = set()
    if not dra_conn or not account:
        return out
    pattern = rf'{account}-\d{{4,}}_{kind}_\d{{4,}}'
    try:
        with dra_conn.cursor() as cur:
            cur.execute(
                "SELECT alias, acc_no FROM mass.accession_entity "
                "WHERE alias ~ %s AND acc_type = %s AND (is_delete IS NULL OR is_delete = false)",
                (pattern, acc_type))
            for alias, acc_no in cur.fetchall():
                if alias:
                    out.add(alias.strip())
                acc = _acc_from_no(acc_type, acc_no)
                if acc:
                    out.add(acc)
    except Exception:
        pass
    return out


def _permit(dra_conn, account, acc_type):
    """ext_permit で account に許可された ref_name の集合（acc_type 別）。"""
    if not dra_conn or not account:
        return set()
    try:
        with dra_conn.cursor() as cur:
            cur.execute(
                "SELECT ref_name FROM mass.ext_permit JOIN mass.ext_entity USING(ext_id) "
                "WHERE submitter_id = %s AND acc_type = %s", (account, acc_type))
            return {str(r[0]).strip() for r in cur.fetchall() if r[0]}
    except Exception:
        return set()


def _psub_to_prjdb(bp_conn, psubs):
    """許可 PSUB（submission_id）→ PRJDB。ref_name が既に PRJDB のものはそのまま通す。"""
    out = {p.upper() for p in psubs if p.upper().startswith("PRJDB")}
    subs = [p for p in psubs if p.upper().startswith("PSUB")]
    if bp_conn and subs:
        try:
            with bp_conn.cursor() as cur:
                cur.execute(
                    "SELECT 'PRJDB' || project_id_counter FROM mass.project "
                    "WHERE submission_id = ANY(%s) AND project_id_counter IS NOT NULL", (subs,))
                out |= {str(a).strip().upper() for (a,) in cur.fetchall() if a}
        except Exception:
            pass
    return out


def _ssub_to_samd(bs_conn, ssubs):
    """許可 SSUB（submission_id or smp_id）→ SAMD。"""
    out = {s.upper() for s in ssubs if s.upper().startswith("SAMD")}
    sub_ids = [s for s in ssubs if s.upper().startswith("SSUB")]
    smp_ids = [int(s) for s in ssubs if str(s).isdigit()]
    if bs_conn and (sub_ids or smp_ids):
        try:
            with bs_conn.cursor() as cur:
                if sub_ids:
                    cur.execute("SELECT accession_id FROM mass.sample JOIN mass.accession USING(smp_id) "
                                "WHERE submission_id = ANY(%s)", (sub_ids,))
                    out |= {str(a).strip().upper() for (a,) in cur.fetchall() if a}
                if smp_ids:
                    cur.execute("SELECT accession_id FROM mass.accession WHERE smp_id = ANY(%s)", (smp_ids,))
                    out |= {str(a).strip().upper() for (a,) in cur.fetchall() if a}
        except Exception:
            pass
    return out


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
                "WHERE submitter_id = %s AND project_id_counter = ANY(%s)", (account, nums))
            owned |= {str(a).strip().upper() for (a,) in cur.fetchall() if a}
    owned |= _psub_to_prjdb(bp_conn, _permit(dra_conn, account, "PSUB"))
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
            owned |= {str(a).strip().upper() for (a,) in cur.fetchall() if a}
    owned |= _ssub_to_samd(bs_conn, _permit(dra_conn, account, "SSUB"))
    return owned


def fetch_account_runs(dra_conn, account, ref_drrs):
    """参照 DRR のうち account 所有（accession_entity）∪ DRA permit（その DRA submission 配下の DRR）の集合（DRA_R0043）。

    DRA permit の ref_name は DRA submission の acc_id（数値。accession_entity.acc_id）または alias（例 dradev-0041）。
    それを submission alias の prefix（`_Submission` 前）に解決し、同 prefix の DRR を許可対象に含める。
    ※他アカウントの DRR を ext_permit 経由で参照する場合（DRA Analysis の RUN_REF / GEA の SRA_RUN）に効く。
    owned/permit が全く取れなければ None（=スキップ）。
    """
    import re as _re
    if not dra_conn or not account:
        return None
    owned = _accession_entity(dra_conn, account, "Run", "DRR")
    try:
        permit_dra = _permit(dra_conn, account, "DRA")
        prefixes = {r for r in permit_dra if r and not r.isdigit()}   # alias 直接（dradev-XXXX）
        nums = sorted({int(r) for r in permit_dra if r.isdigit()})
        if nums:
            # DRA permit の numeric ref_name は accession_entity の acc_id（acc_no ではない）。
            with dra_conn.cursor() as cur:
                cur.execute("SELECT alias FROM mass.accession_entity WHERE acc_type='DRA' AND acc_id = ANY(%s)", (nums,))
                for (alias,) in cur.fetchall():
                    if alias:
                        prefixes.add(alias.split("_Submission")[0].strip())
        if prefixes:
            pat = "^(" + "|".join(_re.escape(p) for p in sorted(prefixes)) + ")_"
            with dra_conn.cursor() as cur:
                cur.execute(
                    "SELECT alias, acc_no FROM mass.accession_entity "
                    "WHERE acc_type='DRR' AND alias ~ %s AND (is_delete IS NULL OR is_delete=false)", (pat,))
                for alias, acc_no in cur.fetchall():
                    if alias:
                        owned.add(alias.strip())
                    acc = _acc_from_no("DRR", acc_no)
                    if acc:
                        owned.add(acc)
    except Exception:
        pass
    return owned or None


def fetch_account_object_names(dra_conn, account):
    """account の既存 DRA object 名（alias∪accession）集合（DRA_R0009）。accession_entity 由来。"""
    if not dra_conn or not account:
        return None
    names = set()
    for kind, acc_type in (("Submission", "DRA"), ("Experiment", "DRX"),
                           ("Run", "DRR"), ("Analysis", "DRZ")):
        names |= _accession_entity(dra_conn, account, kind, acc_type)
    return names or None
