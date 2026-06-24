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


def fetch_biosample_ssub(db_conn, samd_list):
    """入力 SAMD が属する SSUB(submission) を特定し、その SSUB 内の全サンプル＋属性を返す。

    -b/--biosample 機能用。SSUB 全サンプルを含む（入力 SAMD 以外も）ため、更新作業がしやすい。

    戻り値:
      ssub_map: {submission_id: {"samples": [
                   {"smp_id","sample_name","accession_id","status_id",
                    "package","package_group","env_package","attributes": {name: value}}, ...]}}
      found_samds: 入力 SAMD のうち DB で見つかったものの set
    """
    if not samd_list:
        return {}, set()

    # (A) 入力 SAMD の submission_id を特定し、その SSUB に属する全サンプルを列挙
    query_samples = """
        WITH target AS (
            SELECT DISTINCT s.submission_id
            FROM mass.accession a JOIN mass.sample s USING(smp_id)
            WHERE a.accession_id IN ({placeholders})
        )
        SELECT s.submission_id, s.smp_id, s.sample_name, s.package,
               s.package_group, s.env_package, a.accession_id, s.status_id
        FROM mass.sample s
        JOIN target t USING(submission_id)
        LEFT JOIN mass.accession a USING(smp_id)
        ORDER BY s.submission_id, s.smp_id
    """
    rows = execute_in_query(db_conn, query_samples, samd_list)

    ssub_map = {}
    sample_by_smp = {}
    found_samds = set()
    input_set = set(samd_list)
    for submission_id, smp_id, sample_name, package, package_group, env_package, accession_id, status_id in rows:
        sid = str(submission_id)
        smp = {
            "smp_id": str(smp_id),
            "sample_name": sample_name,
            "accession_id": accession_id,
            "status_id": status_id,
            "package": package,
            "package_group": package_group,
            "env_package": env_package,
            "attributes": {},
        }
        ssub_map.setdefault(sid, {"samples": []})["samples"].append(smp)
        sample_by_smp[str(smp_id)] = smp
        if accession_id in input_set:
            found_samds.add(accession_id)

    # (B) 属性を一括取得（seq_no 順）して各サンプルへ充填
    if sample_by_smp:
        query_attrs = """
            SELECT smp_id, attribute_name, attribute_value
            FROM mass.attribute
            WHERE smp_id IN ({placeholders})
            ORDER BY smp_id, seq_no
        """
        for smp_id, attr_name, attr_value in execute_in_query(db_conn, query_attrs, list(sample_by_smp.keys())):
            smp = sample_by_smp.get(str(smp_id))
            if smp is not None:
                smp["attributes"][str(attr_name)] = attr_value

    return ssub_map, found_samds
