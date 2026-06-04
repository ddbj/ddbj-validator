import psycopg2
import re
import logging
from apps.ddbj.utils.features import get_features

# 分割した DB 取得関数を再エクスポート（外部 import 互換のため）
from apps.ddbj.db_meta_biosample import fetch_biosample_data, fetch_biosample_submitters, fetch_biosample_smp_ids, fetch_samd_by_smp_id
from apps.ddbj.db_meta_bioproject import fetch_bp_psubs, fetch_prjdb_by_psub
from apps.ddbj.db_meta_dra import fetch_dra_refs, fetch_dra_library_metadata, fetch_drr_status
from apps.ddbj.db_meta_journal import fetch_valid_journals

from common.db_manager import execute_in_query

logger = logging.getLogger(__name__)

# INSDC (DDBJ/ENA/GenBank) アクセッションを捕捉
_PRJ_PATTERN = re.compile(r'\tproject\t(PRJ[DE][AB]\d+|PRJN[A]\d+)')
_SAM_PATTERN = re.compile(r'\tbiosample\t(SAM[DN]\d+|SAME[AG]?\d+)')
_SRA_PATTERN = re.compile(r'\tsequence read archive\t([SDE]RR\d+)')

# 値にスペースが含まれる可能性がある項目は、行末または次のタブまでを取得
_ORG_PATTERN = re.compile(r'\torganism\t([^\t\r\n]+)', re.IGNORECASE)
_META_PATTERN = re.compile(r'\tmetagenome_source\t([^\t\r\n]+)')
_JRN_PATTERN = re.compile(r'\tjournal\t([^\t\r\n]+)', re.IGNORECASE)

def fast_extract_db_keys(ann_path, seq_path):
    """
    BioPythonのパースを待たずに、ANNファイルをテキストとして1行ずつ走査し、
    DB検索用のキーを高速に抽出する。
    """
    samds, projects, drrs, organisms, journals = set(), set(), set(), set(), set()
    
    try:
        with open(ann_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                # 処理の高速化のため、まずは対象Qualifierの文字列が含まれるかin句で足切り
                if '\tproject\t' in line:
                    if m := _PRJ_PATTERN.search(line):
                        projects.add(m.group(1).strip())
                        
                elif '\tbiosample\t' in line:
                    if m := _SAM_PATTERN.search(line):
                        samds.add(m.group(1).strip())
                        
                elif '\tsequence read archive\t' in line:
                    if m := _SRA_PATTERN.search(line):
                        drrs.add(m.group(1).strip())

                elif '\tjournal\t' in line:
                    if m := _JRN_PATTERN.search(line):
                        journals.add(m.group(1).strip())
                        
                elif '\torganism\t' in line:
                    if m := _ORG_PATTERN.search(line):
                        organisms.add(m.group(1).strip())
                elif '\tmetagenome_source\t' in line:
                    if m := _META_PATTERN.search(line):
                        organisms.add(m.group(1).strip())                                               
                        
    except Exception as e:
        logger.warning(f"Failed to fast-scan {ann_path}: {e}")

    # NCBI APIとDDBJローカルDBで問い合わせを振り分けるためのセットもここで作ってしまう
    from common.ncbi_api import filter_target_accessions
    ncbi_check_prjs = set(filter_target_accessions("bioproject", projects))
    ncbi_check_sams = set(filter_target_accessions("biosample", samds))
    ncbi_check_sras = set(filter_target_accessions("sra", drrs))

    return {
        "ann_path": ann_path,
        "seq_path": seq_path,
        "samds": samds, 
        "projects": projects, 
        "drrs": drrs, 
        "organisms": organisms, 
        "journals": journals,
        "ncbi_check_prjs": ncbi_check_prjs,
        "ncbi_check_sams": ncbi_check_sams,
        "ncbi_check_sras": ncbi_check_sras
    }


def get_organisms_from_records(records):
    """
    レコード内の source フィーチャーから organism と metagenome_source を抽出する。
    """
    organisms = set()
    for record in records.values():
        for feature in get_features(record, "source"):
            for org in feature.qualifiers.get("organism", []):
                organisms.add(org.strip())
            for org in feature.qualifiers.get("metagenome_source", []):
                organisms.add(org.strip())
    return list(organisms)

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



    














    
    
    
def get_expected_transl_table(record, tax_data):
    """
    学名とオルガネラから期待される transl_table を返す。
    見つからない場合や組み合わせが不適当な場合は 0 を返す。
    """
    
    for feature in get_features(record, "source"):
        org = feature.qualifiers.get("organism", [""])[0]
        organelle = feature.qualifiers.get("organelle", [""])[0].strip().lower()

        if org not in tax_data or tax_data[org]["status"] == "not_found":
            return 0

        if org in tax_data and tax_data[org]["status"] in ["valid", "fixable"]:
            t_data = tax_data[org]

            # オルガネラごとの条件分岐
            if organelle in ["mitochondrion", "mitochondrion:kinetoplast", "hydrogenosome"]:
                return t_data.get("mi_code", 0)
            elif organelle.startswith("plastid") or organelle == "chromatophore":
                return t_data.get("pl_code", 0)
            elif organelle == "nucleomorph" or not organelle:
                return t_data.get("gen_code", 0)
            else:
                # その他のオルガネラが来た場合は核のコードをデフォルトとするか、0とする
                return t_data.get("gen_code", 0)
                
    return 0
        