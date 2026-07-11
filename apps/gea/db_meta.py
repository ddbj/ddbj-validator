"""GEA の DB 参照メタ取得（dordb / drmdb / biosample）。

- ADF（Array Design）: account 所有（dordb mass.accession type=3）∪ 公開（dordb mass.resource_adf）。REF0005 用。
- DRA linkage: SDRF が参照する DRR から連携先 DRA submission を特定し、その全 Run/BioSample を取得。REF0003/0004 用。
"""

_ARRAY_DESIGN_TYPE = 3    # dordb mass.accession.accession_type: ArrayDesign
_PUBLIC_STATUS = 300      # dordb mass.current_object_status.object_status_type: 公開（released）


def _acc_from_no(acc_type, acc_no):
    """acc_no を 6 桁ゼロ埋め（7 桁以上はそのまま）にして accession 文字列化。"""
    s = str(acc_no)
    return f"{acc_type}{s if len(s) >= 6 else s.zfill(6)}"


def fetch_array_designs(gea_conn, account=None):
    """REF0005 で参照可能な Array Design accession 集合。

    「この account に登録済み（非公開含む） ∪ 公開」を許容する:
    - 自 account 登録済み: dordb mass.accession type3 で submitter_id=account（状態問わず＝非公開も可）。
    - 公開: object_status_type=300（released。任意 owner） ∪ mass.resource_adf（ArrayExpress 公開マスタ）。
    他 account の非公開 ADF は許容しない（実在しても error）。
    """
    owned, public = set(), set()
    with gea_conn.cursor() as cur:
        if account:
            cur.execute(
                "SELECT accession FROM mass.accession "
                "WHERE accession_type=%s AND submitter_id=%s AND accession IS NOT NULL",
                (_ARRAY_DESIGN_TYPE, account))
            owned = {r[0].strip().upper() for r in cur.fetchall() if r[0]}
        cur.execute(
            "SELECT a.accession FROM mass.accession a "
            "JOIN mass.current_object_status cos USING(accession_id) "
            "WHERE a.accession_type=%s AND cos.object_status_type=%s AND a.accession IS NOT NULL",
            (_ARRAY_DESIGN_TYPE, _PUBLIC_STATUS))
        public = {r[0].strip().upper() for r in cur.fetchall() if r[0]}
        cur.execute("SELECT adf_accession FROM mass.resource_adf")
        public |= {r[0].strip().upper() for r in cur.fetchall() if r[0]}
    return owned | public


def _dra_submission_prefixes(dra_conn, ref_drrs):
    """参照 DRR（accession 文字列）から連携先 DRA submission の alias prefix 群を得る。"""
    nos = []
    for d in ref_drrs:
        d = d.strip().upper()
        if d.startswith("DRR") and d[3:].isdigit():
            nos.append(int(d[3:]))
    if not nos:
        return set()
    prefixes = set()
    with dra_conn.cursor() as cur:
        cur.execute(
            "SELECT alias FROM mass.accession_entity WHERE acc_type='DRR' AND acc_no = ANY(%s)", (nos,))
        for (alias,) in cur.fetchall():
            if alias and "_Run_" in alias:
                prefixes.add(alias.split("_Run_")[0])
    return prefixes


def fetch_dra_submission_objects(dra_conn, bs_conn, ref_drrs):
    """参照 DRR が属する DRA submission の全 Run(DRR)・全 BioSample(SAMD) を返す。

    Run: accession_entity の alias prefix ＋ '_Run_'（is_delete 除外）。
    BioSample: 各 Experiment の object group → ext_relation → ext_entity(SSUB, ref_name=smp_id)
      → biosample DB で smp_id→SAMD。
    """
    prefixes = _dra_submission_prefixes(dra_conn, ref_drrs)
    if not prefixes:
        return None, None
    runs, smp_ids = set(), set()
    with dra_conn.cursor() as cur:
        for prefix in prefixes:
            cur.execute(
                "SELECT acc_no FROM mass.accession_entity "
                "WHERE acc_type='DRR' AND alias LIKE %s AND is_delete=false", (prefix + "\\_Run\\_%",))
            for (no,) in cur.fetchall():
                runs.add(_acc_from_no("DRR", no))
            # Experiment の group 経由で SSUB(smp_id) を収集
            cur.execute(
                "SELECT acc_id FROM mass.accession_entity "
                "WHERE acc_type='DRX' AND alias LIKE %s AND is_delete=false", (prefix + "\\_Experiment\\_%",))
            exp_ids = [r[0] for r in cur.fetchall()]
            if exp_ids:
                cur.execute("SELECT DISTINCT grp_id FROM mass.accession_relation WHERE acc_id = ANY(%s)", (exp_ids,))
                grp_ids = [r[0] for r in cur.fetchall()]
                if grp_ids:
                    cur.execute(
                        "SELECT DISTINCT ee.ref_name FROM mass.ext_relation er "
                        "JOIN mass.ext_entity ee USING(ext_id) "
                        "WHERE er.grp_id = ANY(%s) AND ee.acc_type='SSUB'", (grp_ids,))
                    for (rn,) in cur.fetchall():
                        if rn and str(rn).isdigit():
                            smp_ids.add(int(rn))
    samds = set()
    if smp_ids:
        with bs_conn.cursor() as cur:
            cur.execute(
                "SELECT accession_id FROM mass.accession WHERE smp_id = ANY(%s) AND accession_id IS NOT NULL",
                (sorted(smp_ids),))
            samds = {r[0].strip().upper() for r in cur.fetchall() if r[0]}
    return runs, samds


def fetch_experiment_metadata(gea_conn, esub_or_egead):
    """dordb から Experiment の IDF/SDRF テキストを取得。(idf_text, sdrf_text) を返す。

    esub_or_egead: 'ESUB002584' または 'E-GEAD-1237'。
    """
    with gea_conn.cursor() as cur:
        if esub_or_egead.upper().startswith("ESUB"):
            cur.execute("SELECT accession_id FROM mass.accession WHERE alias=%s AND accession_type=1",
                        (esub_or_egead + "_Experiment_1",))
        else:
            cur.execute("SELECT accession_id FROM mass.accession WHERE accession=%s AND accession_type=1",
                        (esub_or_egead,))
        row = cur.fetchone()
        if not row:
            return None, None
        acc_id = row[0]
        cur.execute("SELECT metadata_type, metadata FROM mass.current_metadata "
                    "WHERE accession_id=%s AND metadata_type IN (1,2)", (acc_id,))
        idf = sdrf = None
        for mt, md in cur.fetchall():
            if mt == 1:
                idf = md
            elif mt == 2:
                sdrf = md
        return idf, sdrf
