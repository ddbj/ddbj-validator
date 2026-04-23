import psycopg2
import re
from common.utils.features import get_features

def _extract_qualifiers(records, feature_type, qualifier_key=None):
    """
    レコード群から特定のフィーチャー（およびQualifier）の値を抽出する。
    qualifier_key が None の場合は、そのフィーチャーが持つ全 Qualifier の値を返す。
    """

    for record in records.values():
        for feature in get_features(record, feature_type):
            if qualifier_key:
                for val in feature.qualifiers.get(qualifier_key, []):
                    yield val
            else:
                for vals in feature.qualifiers.values():
                    for val in vals:
                        yield val

def get_samds_from_records(records):
    """
    メモリ上のレコード（COMMON含む）から、すべての BioSample (SAMD) アクセッションを抽出する
    """
    samds = set()
    samd_pattern = re.compile(r'(SAMD\d+)')
    
    for record in records.values():
        # 1. カスタムパーサーの仕様: features の中から探す
        if hasattr(record, 'features'):
            for feature in record.features:
                for vals in feature.qualifiers.values():
                    if isinstance(vals, str):
                        vals = [vals]
                    for val in vals:
                        match = samd_pattern.search(str(val))
                        if match:
                            samds.add(match.group(1))
                            
    return list(samds)
    

def get_projects_from_records(records):
    return list({v.strip() for v in _extract_qualifiers(records, "DBLINK", "project") if v.strip()})


def get_drrs_from_records(records):
    return list({v.strip() for v in _extract_qualifiers(records, "DBLINK", "sequence read archive") if v.strip()})


def get_journals_from_records(records):
    return list({v.strip() for v in _extract_qualifiers(records, "REFERENCE", "journal") if v.strip()})


def fetch_biosample_data(db_conn, samd_list):
    if not samd_list: return {}
    placeholders = ', '.join(['%s'] * len(samd_list))
    query = f"""
        SELECT accession_id, attribute_name, attribute_value, status_id
        FROM mass.accession
        JOIN mass.attribute USING(smp_id) JOIN mass.sample USING(smp_id)
        WHERE accession_id IN ({placeholders})
        ORDER BY accession_id, attribute_name
    """
    bs_data = {}
        
    with db_conn.cursor() as cursor:
        cursor.execute(query, tuple(samd_list))
        for acc_id, attr_name, attr_val, status_id in cursor.fetchall():
            if acc_id not in bs_data:
                bs_data[acc_id] = {}
                bs_data[acc_id]["status_id"] = status_id
                
            norm_attr = str(attr_name)
            bs_data[acc_id][norm_attr] = attr_val

    return bs_data

    
def fetch_biosample_submitters(db_conn, samd_list):
    if not samd_list: return {}
    placeholders = ', '.join(['%s'] * len(samd_list))
    query = f"""
        SELECT accession_id, email, first_name, last_name
        FROM mass.accession
        JOIN mass.sample USING(smp_id)
        JOIN mass.contact USING(submission_id)
        WHERE accession_id IN ({placeholders})
    """
    submitters = {}
    with db_conn.cursor() as cursor:
        cursor.execute(query, tuple(samd_list))
        for acc_id, email, first, last in cursor.fetchall():
            if acc_id not in submitters: submitters[acc_id] = []
            submitters[acc_id].append({
                "email": str(email).strip() if email else "",
                "first": str(first).strip() if first else "",
                "last": str(last).strip() if last else ""
            })
    return submitters


def fetch_biosample_smp_ids(db_conn, samd_list):
    if not samd_list: return {}
    placeholders = ', '.join(['%s'] * len(samd_list))
    query = f"SELECT accession_id, smp_id FROM mass.accession WHERE accession_id IN ({placeholders})"
    smp_ids = {}
    with db_conn.cursor() as cursor:
        cursor.execute(query, tuple(samd_list))
        for acc_id, smp_id in cursor.fetchall():
            smp_ids[acc_id] = str(smp_id)
    return smp_ids


def fetch_bp_psubs(db_conn, project_list):
    bp_psubs = {}
    prj_map = {}
    for prj in project_list:
        if prj.upper().startswith("PRJDB"):
            try:
                num = int(prj[5:])
                prj_map[num] = prj
            except ValueError:
                pass
    if prj_map:
        placeholders = ', '.join(['%s'] * len(prj_map))
        query = f"""
            SELECT project_id_counter, submission_id, project_type, project.status_id
            FROM mass.project 
            JOIN mass.submission USING(submission_id) 
            WHERE project_id_counter IN ({placeholders})
        """
        with db_conn.cursor() as cursor:
            cursor.execute(query, tuple(prj_map.keys()))
            for num, sub_id, project_type, status_id in cursor.fetchall():
                if num in prj_map:
                    bp_psubs[prj_map[num]] = {
                        "submission_id": str(sub_id),
                        "project_type": project_type,
                        "status_id": status_id
                    }
    return bp_psubs


def fetch_dra_refs(db_conn, drr_list):
    dra_refs = {}
    drr_map = {}
    for drr in drr_list:
        if drr.upper().startswith("DRR"):
            try:
                num = int(drr[3:])
                drr_map[num] = drr
            except ValueError:
                pass
    
    if drr_map:
        placeholders = ', '.join(['%s'] * len(drr_map))
        
        query = f"""
            WITH target_drr AS (
                -- 1. 対象のDRRを絞り込み
                SELECT acc_id, acc_no 
                FROM mass.accession_entity 
                WHERE acc_type = 'DRR' AND acc_no IN ({placeholders})
            ),
            latest_rel AS (
                -- 2. DRR -> 親(DRX) の最新リレーション（大きい順にソートして1件取得）
                SELECT DISTINCT ON (acc_id) acc_id, p_acc_id 
                FROM mass.accession_relation 
                WHERE acc_id IN (SELECT acc_id FROM target_drr)
                ORDER BY acc_id, grp_id DESC
            ),
            latest_extrel AS (
                -- 3. 親(DRX) -> 外部ID の最新リレーション
                -- BioSampleとBioProject等、複数紐づく同着1位を全て取るために RANK() を使用
                SELECT acc_id, ext_id
                FROM (
                    SELECT acc_id, ext_id, RANK() OVER (PARTITION BY acc_id ORDER BY grp_id DESC) as rnk
                    FROM mass.ext_relation
                    WHERE acc_id IN (SELECT p_acc_id FROM latest_rel)
                ) sub
                WHERE rnk = 1
            )
            -- 4. 絞り込んだ最新結果だけをJOIN
            SELECT drr.acc_no, extt.ref_name 
            FROM target_drr drr
            JOIN latest_rel rel ON drr.acc_id = rel.acc_id
            JOIN mass.accession_entity ent2 ON rel.p_acc_id = ent2.acc_id
            JOIN latest_extrel extrel ON ent2.acc_id = extrel.acc_id
            JOIN mass.ext_entity extt ON extrel.ext_id = extt.ext_id
            WHERE (ent2.acc_type = 'DRX' OR extt.ref_name LIKE 'PSUB%%')
        """
        with db_conn.cursor() as cursor:
            cursor.execute(query, tuple(drr_map.keys()))
            for num, ref_name in cursor.fetchall():
                if num in drr_map:
                    drr = drr_map[num]
                    if drr not in dra_refs: dra_refs[drr] = set()
                    dra_refs[drr].add(str(ref_name))
    
    return dra_refs


def fetch_prjdb_by_psub(db_conn, psub_list):
    if not psub_list: return {}
    placeholders = ', '.join(['%s'] * len(psub_list))
    query = f"""
        SELECT submission_id, project_id_counter, project.status_id
        FROM mass.submission 
        JOIN mass.project USING(submission_id) 
        WHERE submission_id IN ({placeholders})
    """
    psub_to_prj = {}
    with db_conn.cursor() as cursor:
        cursor.execute(query, tuple(psub_list))
        for sub_id, num, status_id in cursor.fetchall():
            psub_to_prj[sub_id] = {
                "accession": f"PRJDB{num}",
                "status_id": status_id
            }
    return psub_to_prj


def fetch_samd_by_smp_id(db_conn, smp_list):
    if not smp_list: return {}
    placeholders = ', '.join(['%s'] * len(smp_list))
    query = f"""
        SELECT smp_id, accession_id, status_id
        FROM mass.accession JOIN mass.sample USING(smp_id)
        WHERE smp_id IN ({placeholders})
    """
    smp_to_samd = {}
    with db_conn.cursor() as cursor:
        cursor.execute(query, tuple(smp_list))
        for smp_id, acc_id, status_id in cursor.fetchall():
            smp_to_samd[str(smp_id)] = {
                "accession": acc_id,
                "status_id": status_id
            }
    return smp_to_samd


def fetch_dra_library_metadata(db_conn, drr_list):
    """DRRアクセッションから対応するExperiment(DRX)のXMLをパースし、Libraryメタデータを取得する"""
    if not drr_list: return {}
    
    drr_map = {}
    for drr in drr_list:
        if drr.upper().startswith("DRR"):
            try:
                num = int(drr[3:])
                drr_map[num] = drr
            except ValueError:
                pass
                
    if not drr_map: return {}
    
    placeholders = ', '.join(['%s'] * len(drr_map))
    
    query = f"""
        SELECT 
            ent.acc_no AS drr_no,
            ent2.acc_no AS drx_no,
            (xpath('//LIBRARY_SOURCE/text()', m.content::xml))[1]::text AS library_source,
            (xpath('//LIBRARY_SELECTION/text()', m.content::xml))[1]::text AS library_selection,
            (xpath('//LIBRARY_STRATEGY/text()', m.content::xml))[1]::text AS library_strategy,
            (xpath('//INSTRUMENT_MODEL/text()', m.content::xml))[1]::text AS instrument_model
        FROM mass.accession_entity ent 
        JOIN mass.accession_relation rel USING(acc_id) 
        JOIN mass.accession_entity ent2 ON(rel.p_acc_id = ent2.acc_id) 
        JOIN mass.meta_entity m ON(ent2.acc_id = m.acc_id)
        WHERE ent.acc_type = 'DRR' 
          AND ent2.acc_type = 'DRX'
          AND ent.acc_no IN ({placeholders})
          AND m.meta_version = (
              SELECT MAX(meta_version) 
              FROM mass.meta_entity 
              WHERE acc_id = ent2.acc_id
          )
    """
    
    results = {}
    try:
        with db_conn.cursor() as cursor:
            cursor.execute(query, tuple(drr_map.keys()))
            for drr_no, drx_no, lib_source, lib_selection, lib_strategy, instrument_model in cursor.fetchall():
                if drr_no in drr_map:
                    drr_acc = drr_map[drr_no]
                    drx_acc = f"DRX{str(drx_no).zfill(6)}" if drx_no is not None else "UNKNOWN"
                    
                    results[drr_acc] = {
                        "source": str(lib_source).strip() if lib_source else "",
                        "selection": str(lib_selection).strip() if lib_selection else "",
                        "strategy": str(lib_strategy).strip() if lib_strategy else "",
                        "instrument_model": str(instrument_model).strip() if instrument_model else "",
                        "drx": drx_acc
                    }
    except Exception as e:
        print(f"[WARN] Failed to fetch DRA library metadata: {e}")
                
    return results


def fetch_valid_journals(db_conn, journal_list):
    """
    指定されたジャーナル名のリストが entrez_journal テーブルに存在するか確認し、
    存在するジャーナル名を「データベースに登録されているそのままの表記」でセットとして返す。
    """
    if not journal_list:
        return set()

    # DB検索用に、検索キーワード自体をすべて小文字にしておく
    clean_journals = list({j.strip().lower() for j in journal_list if j.strip()})
    if not clean_journals:
        return set()

    placeholders = ', '.join(['%s'] * len(clean_journals))
    
    # jr_medabbrev だけでなく、jr_title や jr_isoabbrev も小文字化してマッチさせる
    query = f"""
        SELECT jr_title, jr_medabbrev, jr_isoabbrev 
        FROM public.entrez_journal 
        WHERE LOWER(jr_title) IN ({placeholders})
           OR LOWER(jr_medabbrev) IN ({placeholders})
           OR LOWER(jr_isoabbrev) IN ({placeholders})
    """
    
    valid_journals = set()
    try:
        with db_conn.cursor() as cursor:
            cursor.execute(query, tuple(clean_journals * 3))
            for row in cursor.fetchall():
                # 取得できた行のカラム（タイトルや略称）をすべて「生の文字列のまま」入れる
                for jr_name in row:
                    if jr_name:
                        valid_journals.add(str(jr_name).strip())
    except Exception as e:
        print(f"[WARN] Failed to fetch journal names from DB: {e}")
        
    return valid_journals
    
    
def fetch_drr_status(db_conn, drr_list):
    """
    DRRアクセッション番号から、DRAデータベースの submission status を取得する
    submission status 1000 cancelled 1100 permanently suppressed 1200 withdrawn の場合、Run も同じ status
    800 public の場合、is_delete true AND was_public true で Run status permanently suppressed 1100
    """
    if not drr_list: return {}
    
    drr_map = {}
    for drr in drr_list:
        if drr.upper().startswith("DRR"):
            try:
                num = int(drr[3:])
                drr_map[num] = drr
            except ValueError:
                pass
                
    if not drr_map: return {}
    
    placeholders = ', '.join(['%s'] * len(drr_map))
    
    # 修正: accession_entity (Run) 側から was_public, is_deleted を追加で取得する
    query = f"""
        SELECT 
            e.acc_no, 
            v.status,
            was_public,
            is_delete
        FROM mass.accession_entity e
        JOIN mass.current_dra_submission_group_view v
          ON v.submitter_id = substring(e.alias from '^([^-]+)-')
         AND v.serial = substring(e.alias from '-([0-9]+)_Run_')::int
        WHERE e.acc_type = 'DRR' 
          AND e.acc_no IN ({placeholders})
    """
    
    drr_status = {}
    try:
        with db_conn.cursor() as cursor:
            cursor.execute(query, tuple(drr_map.keys()))
            
            for acc_no, status, was_public, is_delete in cursor.fetchall():
                if acc_no in drr_map:
                    # ステータスが文字列で返ってくるケースを考慮し、判定用に int 化を試みる
                    try:
                        status_code = int(status)
                    except (ValueError, TypeError):
                        status_code = status
                        
                    # --- 判定ロジック ---
                    if status_code in (1000, 1100, 1200):
                        final_status = status_code
                    elif status_code == 800:
                        # 800 (public) の場合、特定のフラグ条件を満たせば 1100 (permanently suppressed) 扱いにする
                        if was_public and is_delete:
                            final_status = 1100
                        else:
                            final_status = status_code
                    else:
                        # その他のステータスはそのまま
                        final_status = status
                        
                    drr_status[drr_map[acc_no]] = final_status
                    
    except Exception as e:
        print(f"[WARN] Failed to fetch DRR status: {e}")
        
    return drr_status