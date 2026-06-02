import psycopg2

def fetch_authorized_accessions(bp_conn, bs_conn, dra_conn, account_id):
    """
    指定されたアカウントが「登録した」または「外部参照を許可された」
    BioProject, BioSample, DRA (DRRのみ) のアクセッション番号のSetを返す。
    """
    auth_projects = set()
    auth_samds = set()
    auth_dra = set()

    if not account_id:
        return auth_projects, auth_samds, auth_dra

    # =========================================================
    # 1. アカウント自身で登録した番号の取得
    # =========================================================
    
    # BioProject
    if bp_conn:
        bp_query = """
            SELECT 'PRJDB' || project_id_counter 
            FROM mass.submission 
            JOIN mass.project USING(submission_id) 
            WHERE submitter_id = %s AND project_id_counter IS NOT NULL
        """
        with bp_conn.cursor() as cur:
            cur.execute(bp_query, (account_id,))
            for row in cur.fetchall():
                if row[0]:
                    auth_projects.add(str(row[0]).strip().upper())

    # BioSample
    if bs_conn:
        bs_query = """
            SELECT accession_id 
            FROM mass.submission 
            JOIN mass.sample USING(submission_id) 
            JOIN mass.accession USING(smp_id) 
            WHERE submitter_id = %s AND accession_id IS NOT NULL
        """
        with bs_conn.cursor() as cur:
            cur.execute(bs_query, (account_id,))
            for row in cur.fetchall():
                if row[0]:
                    auth_samds.add(str(row[0]).strip().upper())

    # DRA Run
    if dra_conn:
        dra_query = """
            SELECT 'DRR' || CASE 
                WHEN LENGTH(acc_no::text) < 6 THEN LPAD(acc_no::text, 6, '0') 
                ELSE acc_no::text 
            END
            FROM mass.accession_entity 
            WHERE alias LIKE %s AND acc_type = 'DRR'
        """
        with dra_conn.cursor() as cur:
            cur.execute(dra_query, (f"{account_id}-%",))
            for row in cur.fetchall():
                if row[0]:
                    auth_dra.add(str(row[0]).strip().upper())

    # =========================================================
    # 2. 外部参照が許可された番号の取得 (DRA ext_permit)
    # =========================================================
    permitted_psubs = set()
    permitted_ssubs = set()
    permitted_dra_acc_ids = set()

    if dra_conn:
        ext_query = """
            SELECT acc_type, ref_name 
            FROM mass.ext_permit 
            JOIN mass.ext_entity USING(ext_id) 
            WHERE submitter_id = %s
        """
        with dra_conn.cursor() as cur:
            cur.execute(ext_query, (account_id,))
            for row in cur.fetchall():
                acc_type = str(row[0]).strip().upper() if row[0] else ""
                ref_name = str(row[1]).strip() if row[1] else ""
                if acc_type == 'PSUB':
                    permitted_psubs.add(ref_name)
                elif acc_type == 'SSUB':
                    permitted_ssubs.add(ref_name)
                elif acc_type == 'DRA':
                    permitted_dra_acc_ids.add(ref_name)

    # 許可された PSUB -> PRJDB 番号の取得
    if bp_conn and permitted_psubs:
        psub_query = """
            SELECT 'PRJDB' || project_id_counter 
            FROM mass.submission 
            JOIN mass.project USING(submission_id) 
            WHERE submission_id = ANY(%s) AND project_id_counter IS NOT NULL
        """
        with bp_conn.cursor() as cur:
            cur.execute(psub_query, (list(permitted_psubs),))
            for row in cur.fetchall():
                if row[0]:
                    auth_projects.add(str(row[0]).strip().upper())

    # 許可された SSUB (smp_id) -> SAMD 番号の取得
    if bs_conn and permitted_ssubs:
        valid_smp_ids = [int(x) for x in permitted_ssubs if x.isdigit()]
        if valid_smp_ids:
            ss_query = """
                SELECT accession_id 
                FROM mass.accession 
                WHERE smp_id = ANY(%s) AND accession_id IS NOT NULL
            """
            with bs_conn.cursor() as cur:
                cur.execute(ss_query, (valid_smp_ids,))
                for row in cur.fetchall():
                    if row[0]:
                        auth_samds.add(str(row[0]).strip().upper())

    # 許可された DRA (acc_id) -> DRR 番号の取得
    if dra_conn and permitted_dra_acc_ids:
        valid_acc_ids = [int(x) for x in permitted_dra_acc_ids if x.isdigit()]
        if valid_acc_ids:
            dra_permit_query = """
                SELECT 'DRR' || CASE 
                    WHEN LENGTH(T.acc_no::text) < 6 THEN LPAD(T.acc_no::text, 6, '0') 
                    ELSE T.acc_no::text 
                END
                FROM mass.accession_entity T
                JOIN mass.accession_entity S 
                  ON T.alias LIKE SPLIT_PART(S.alias, '_Submission', 1) || '%%'
                WHERE S.acc_id = ANY(%s) AND T.acc_type = 'DRR'
            """
            with dra_conn.cursor() as cur:
                cur.execute(dra_permit_query, (valid_acc_ids,))
                for row in cur.fetchall():
                    if row[0]:
                        auth_dra.add(str(row[0]).strip().upper())

    return auth_projects, auth_samds, auth_dra