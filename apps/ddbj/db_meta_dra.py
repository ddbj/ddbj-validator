"""db_metadata から分割: dra 関連の DB 取得関数。"""
import logging
from common.db_manager import execute_in_query

logger = logging.getLogger(__name__)


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
        query = """
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
        for num, ref_name in execute_in_query(db_conn, query, drr_map.keys()):
            if num in drr_map:
                drr = drr_map[num]
                if drr not in dra_refs: dra_refs[drr] = set()
                dra_refs[drr].add(str(ref_name))

    return dra_refs


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

    query = """
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
        for drr_no, drx_no, lib_source, lib_selection, lib_strategy, instrument_model in execute_in_query(db_conn, query, drr_map.keys()):
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
        logger.warning(f"Failed to fetch DRA library metadata: {e}")
                
    return results


def fetch_drr_status(db_conn, drr_list):
    """
    DRRアクセッション番号から、DRAデータベースの submission status を取得する
    submission status 1000 cancelled 1100 permanently suppressed 1200 withdrawn の場合、Run も同じ status
    submission status 770 (temporarily suppressed) / 800 (public) の場合、
    個々の Run が is_delete true AND was_public true なら、その Run は permanently suppressed (1100) 扱いとする
    （submission 全体は生きているが、当該 Run だけが永久抑制されているケース）
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

    # accession_entity (Run) 側から was_public, is_deleted を追加で取得する
    query = """
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
        for acc_no, status, was_public, is_delete in execute_in_query(db_conn, query, drr_map.keys()):
            if acc_no in drr_map:
                # ステータスが文字列で返ってくるケースを考慮し、判定用に int 化を試みる
                try:
                    status_code = int(status)
                except (ValueError, TypeError):
                    status_code = status

                # --- 判定ロジック ---
                if status_code in (1000, 1100, 1200):
                    final_status = status_code
                elif status_code in (770, 800):
                    # 770 (temporarily suppressed) / 800 (public) の場合、
                    # 当該 Run が is_delete true AND was_public true なら 1100 (permanently suppressed) 扱いにする
                    if was_public and is_delete:
                        final_status = 1100
                    else:
                        final_status = status_code
                else:
                    # その他のステータスはそのまま
                    final_status = status

                drr_status[drr_map[acc_no]] = final_status

    except Exception as e:
        logger.warning(f"Failed to fetch DRR status: {e}")
        
    return drr_status
