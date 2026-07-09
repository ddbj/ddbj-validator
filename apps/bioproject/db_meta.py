"""BioProject DB 固有の取得関数（BP_R0016 / R0021 / R0004）。

Ruby `ddbj_db_validator.rb` の umbrella_project? / get_biosample_locus_tag_prefix /
get_bioproject_names_list 相当。status_id 5600/5700（削除/取消相当）は除外する。
"""
import re
import defusedxml.ElementTree as ET

_XMLDECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)


def fetch_umbrella_accessions(bp_conn, accessions):
    """referenced accession（PRJDB.../PSUB...）のうち umbrella project の集合を返す（BP_R0016）。

    Ruby umbrella_project? 準拠: mass.project.project_type='umbrella'、
    PRJDB は project_id_counter、PSUB は submission_id で判定。
    """
    ok = set()
    if not bp_conn or not accessions:
        return ok
    prjdb_nums = sorted({int(a[5:]) for a in accessions
                         if a.upper().startswith("PRJDB") and a[5:].isdigit()})
    psubs = sorted({a for a in accessions if a.upper().startswith("PSUB")})
    with bp_conn.cursor() as cur:
        if prjdb_nums:
            cur.execute(
                "SELECT project_id_counter FROM mass.project "
                "WHERE project_type = 'umbrella' AND project_id_counter = ANY(%s) "
                "AND (status_id IS NULL OR status_id NOT IN (5600, 5700))",
                (prjdb_nums,))
            for (counter,) in cur.fetchall():
                if counter is not None:
                    ok.add("PRJDB" + str(counter))
        if psubs:
            cur.execute(
                "SELECT submission_id FROM mass.project "
                "WHERE project_type = 'umbrella' AND submission_id = ANY(%s) "
                "AND (status_id IS NULL OR status_id NOT IN (5600, 5700))",
                (psubs,))
            for (sid,) in cur.fetchall():
                if sid:
                    ok.add(str(sid).strip())
    return ok


def fetch_biosample_locus_prefix(bs_conn, samds):
    """SAMD -> {locus_tag_prefix, ...} を返す（BP_R0021）。Ruby get_biosample_locus_tag_prefix 準拠。"""
    res = {}
    if not bs_conn or not samds:
        return res
    samd_list = sorted({str(s).strip() for s in samds if s})
    with bs_conn.cursor() as cur:
        cur.execute(
            "SELECT acc.accession_id, attr.attribute_value "
            "FROM mass.attribute attr "
            "JOIN mass.accession acc USING(smp_id) "
            "JOIN mass.sample smp USING(smp_id) "
            "WHERE attr.attribute_name = 'locus_tag_prefix' AND attr.attribute_value <> '' "
            "AND acc.accession_id = ANY(%s) "
            "AND (smp.status_id IS NULL OR smp.status_id NOT IN (5600, 5700))",
            (samd_list,))
        for acc_id, val in cur.fetchall():
            if acc_id and val:
                res.setdefault(str(acc_id).strip(), set()).add(str(val).strip())
    return res


def fetch_account_project_names(bp_conn, submitter_id):
    """account の登録済み（accession 付き）BioProject の [(title, description), ...] を返す（BP_R0004）。

    submission 毎の最新版 XML を取得し、project_id_counter not null（＝登録済み）に絞り、
    XML から Title / Description を抽出する。登録途中（accession 無し）は含めない。
    """
    out = []
    if not bp_conn or not submitter_id:
        return out
    q = ("SELECT x.content FROM mass.xml x "
         "JOIN mass.submission s USING(submission_id) "
         "JOIN mass.project p USING(submission_id) "
         "WHERE s.submitter_id = %s AND p.project_id_counter IS NOT NULL "
         "AND (p.status_id IS NULL OR p.status_id NOT IN (5600, 5700)) "
         "AND (x.version, x.submission_id) IN "
         "(SELECT max(version), submission_id FROM mass.xml GROUP BY submission_id)")
    with bp_conn.cursor() as cur:
        cur.execute(q, (submitter_id,))
        rows = cur.fetchall()
    for (content,) in rows:
        if not content:
            continue
        text = content if isinstance(content, str) else content.decode("latin-1", "replace")
        text = _XMLDECL_RE.sub("", text, count=1)   # encoding 宣言付き unicode は ET が拒否するため除去
        try:
            root = ET.fromstring(text)
        except Exception:
            continue
        for proj in root.findall(".//Project/Project"):
            descr = proj.find("./ProjectDescr")
            if descr is None:
                continue
            t = (descr.findtext("./Title") or "").strip()
            d = (descr.findtext("./Description") or "").strip()
            out.append((t, d))
    return out
