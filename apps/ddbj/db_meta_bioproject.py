"""db_metadata から分割: bioproject 関連の DB 取得関数。"""
import logging
from common.db_manager import execute_in_query

logger = logging.getLogger(__name__)


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
        query = """
            SELECT project_id_counter, submission_id, project_type, project.status_id
            FROM mass.project
            JOIN mass.submission USING(submission_id)
            WHERE project_id_counter IN ({placeholders})
        """
        for num, sub_id, project_type, status_id in execute_in_query(db_conn, query, prj_map.keys()):
            if num in prj_map:
                bp_psubs[prj_map[num]] = {
                    "submission_id": str(sub_id),
                    "project_type": project_type,
                    "status_id": status_id
                }
    return bp_psubs


def fetch_prjdb_by_psub(db_conn, psub_list):
    if not psub_list: return {}
    query = """
        SELECT submission_id, project_id_counter, project.status_id
        FROM mass.submission
        JOIN mass.project USING(submission_id)
        WHERE submission_id IN ({placeholders})
    """
    psub_to_prj = {}
    for sub_id, num, status_id in execute_in_query(db_conn, query, psub_list):
        psub_to_prj[sub_id] = {
            "accession": f"PRJDB{num}",
            "status_id": status_id
        }
    return psub_to_prj
