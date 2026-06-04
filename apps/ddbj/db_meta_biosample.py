"""db_metadata から分割: biosample 関連の DB 取得関数。"""
import logging
from common.db_manager import execute_in_query

logger = logging.getLogger(__name__)


def fetch_biosample_data(db_conn, samd_list):
    if not samd_list: return {}
    query = """
        SELECT accession_id, attribute_name, attribute_value, status_id
        FROM mass.accession
        JOIN mass.attribute USING(smp_id) JOIN mass.sample USING(smp_id)
        WHERE accession_id IN ({placeholders})
        ORDER BY accession_id, attribute_name
    """
    bs_data = {}

    for acc_id, attr_name, attr_val, status_id in execute_in_query(db_conn, query, samd_list):
        if acc_id not in bs_data:
            bs_data[acc_id] = {}
            bs_data[acc_id]["status_id"] = status_id

        norm_attr = str(attr_name)
        bs_data[acc_id][norm_attr] = attr_val

    return bs_data


def fetch_biosample_submitters(db_conn, samd_list):
    if not samd_list: return {}
    query = """
        SELECT accession_id, email, first_name, last_name
        FROM mass.accession
        JOIN mass.sample USING(smp_id)
        JOIN mass.contact USING(submission_id)
        WHERE accession_id IN ({placeholders})
    """
    submitters = {}
    for acc_id, email, first, last in execute_in_query(db_conn, query, samd_list):
        if acc_id not in submitters: submitters[acc_id] = []
        submitters[acc_id].append({
            "email": str(email).strip() if email else "",
            "first": str(first).strip() if first else "",
            "last": str(last).strip() if last else ""
        })
    return submitters


def fetch_biosample_smp_ids(db_conn, samd_list):
    if not samd_list: return {}
    query = "SELECT accession_id, smp_id FROM mass.accession WHERE accession_id IN ({placeholders})"
    smp_ids = {}
    for acc_id, smp_id in execute_in_query(db_conn, query, samd_list):
        smp_ids[acc_id] = str(smp_id)
    return smp_ids


def fetch_samd_by_smp_id(db_conn, smp_list):
    if not smp_list: return {}
    query = """
        SELECT smp_id, accession_id, status_id
        FROM mass.accession JOIN mass.sample USING(smp_id)
        WHERE smp_id IN ({placeholders})
    """
    smp_to_samd = {}
    for smp_id, acc_id, status_id in execute_in_query(db_conn, query, smp_list):
        smp_to_samd[str(smp_id)] = {
            "accession": acc_id,
            "status_id": status_id
        }
    return smp_to_samd
