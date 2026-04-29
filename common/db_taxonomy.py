import os
import time
import requests
import xml.etree.ElementTree as ET
import psycopg2
from apps.ddbj.utils.features import get_features
from apps.ddbj.db_metadata import get_organisms_from_records, get_expected_transl_table


def get_tax_group(org_name, lineage):
    """organism名とlineageから tax_group を判定して返す"""
    org_clean = org_name.strip() if org_name else ""
    lineage_lower = lineage.lower() if lineage else ""
    org_lower = org_clean.lower()
    
    # "uncultured" や "environmental" が名前に含まれているか、系統に含まれているかで判定
    is_environmental = (
        "unclassified sequences" in lineage_lower or 
        "environmental samples" in lineage_lower or 
        "uncultured" in org_lower or
        "environmental" in org_lower
    )
    
    if is_environmental: return "environmental"
    if "Viruses" in lineage: return "virus"
    if "Eukaryota" in lineage: return "eukaryote"
    if "Bacteria" in lineage or "Archaea" in lineage: return "prokaryote"
    
    return "other"


TYPE_PRIORITY = {
    'scientific name': 1,
    'synonym': 2,
    'includes': 3,
    'unpublished name': 4,
    'equivalent name': 5,
    'misspelling': 6,
    'acronym': 7,
    'authority': 8,
    'blast name': 9,
    'common name': 10,
    'genbank common name': 11,
    'in-part': 12,
    'misnomer': 13
}

# 許可される rank の定義
ALLOWED_RANKS = {"species", "forma", "subspecies", "varietas"}

# 種以下には絶対に出現しない（＝DBを辿るまでもなくエラーとなる）rank の定義
DEFINITELY_NOT_SPECIES_RANKS = {
    "genus", "family", "subfamily", "tribe", "subgenus", "order", 
    "superfamily", "class", "section", "subtribe", "species group", 
    "suborder", "phylum", "subclass", "infraorder", "species subgroup", 
    "superorder", "subsection", "subphylum", "parvorder", "kingdom", 
    "infraclass", "series", "realm", "superclass", "cohort", "subcohort", 
    "domain", "subkingdom", "acellular root", "cellular root", "superphylum"
}

# NCBI TaxonomyのDivisionフルネームからDivision略号へのマッピング
NCBI_DIVISION_MAP = {
    "Bacteria": "BCT",
    "Invertebrates": "INV",
    "Mammals": "MAM",
    "Phages": "PHG",
    "Plants and Fungi": "PLN",
    "Primates": "PRI",
    "Rodents": "ROD",
    "Synthetic and Chimeric": "SYN",
    "Unassigned": "UNA",
    "Viruses": "VRL",
    "Vertebrates": "VRT",
    "Environmental samples": "ENV"
}


def fetch_taxonomy_data(db_conn, organism_list):
    tax_data = {}
    if not organism_list:
        return tax_data
        
    lower_orgs = [org.lower() for org in organism_list]
    placeholders = ', '.join(['%s'] * len(lower_orgs))
    
    # taxonomy division
    query = f"""
        SELECT 
            trim(n.ut_name) AS input_name, 
            trim(n.ut_type) AS match_type, 
            trim(sci.ut_name) AS scientific_name,
            trim(nd.ut_rank) AS rank,
            nd.gen_code_id,
            nd.mi_gen_code_id,
            nd.plastid_gen_code_id,
            n.ut_id,
            trim(nd.lineage1) AS lineage,
            trim(d.division_cde) AS division
        FROM public.utax_names n
        LEFT JOIN public.utax_names sci ON n.ut_id = sci.ut_id AND trim(sci.ut_type) = 'scientific name'
        LEFT JOIN public.utax_nodes nd ON n.ut_id = nd.ut_id
        LEFT JOIN public.utax_div d ON nd.division_id = d.division_id
        WHERE lower(trim(n.ut_name)) IN ({placeholders})
    """
        
    temp_results = {}
    with db_conn.cursor() as cursor:
        cursor.execute(query, tuple(lower_orgs))
        for row in cursor.fetchall():
            input_org = row[0] if row[0] else ""
            ut_type = row[1].lower() if row[1] else ""
            sci_name = row[2] if row[2] else input_org
            rank = row[3].lower() if row[3] else "unknown"
            
            gen_code = row[4] if row[4] is not None else 0
            mi_code = row[5] if row[5] is not None else 0
            pl_code = row[6] if row[6] is not None else 0
            tax_id = row[7] if row[7] is not None else "unknown"
            lineage = row[8] if row[8] else ""
            division = row[9] if row[9] else ""
            
            priority = TYPE_PRIORITY.get(ut_type, 99)
            inp_lower = input_org.lower()
            if inp_lower not in temp_results:
                temp_results[inp_lower] = []
            
            temp_results[inp_lower].append((priority, ut_type, sci_name, rank, gen_code, mi_code, pl_code, tax_id, lineage, division))

    # 親階層をDBで再帰チェックする必要がある ut_id を保持する辞書
    pending_recursive_check = {}

    for org in organism_list:
        org_lower = org.lower()
        if org_lower in temp_results:
            best_match = sorted(temp_results[org_lower], key=lambda x: x[0])[0]
            
            priority, best_type, sci_name, rank, gen_code, mi_code, pl_code, tax_id, lineage, division = best_match
            
            tax_group = get_tax_group(org, lineage)
            
            base_data = {
                "scientific_name": sci_name, "rank": rank, "type": best_type, 
                "gen_code": gen_code, "mi_code": mi_code, "pl_code": pl_code, 
                "tax_id": tax_id, "lineage": lineage, "division": division,
                "is_species_or_below": False,
                "tax_group": tax_group
            }

            if rank in ALLOWED_RANKS:
                # 1 自身のランクが許可ランクの場合
                base_data["is_species_or_below"] = True
                if priority == 1:
                    if org == sci_name:
                        base_data["status"] = "valid"
                    else:
                        base_data["status"] = "fixable"
                        base_data["type"] = "case correction"
                else:
                    base_data["status"] = "fixable"
                    
            elif rank in DEFINITELY_NOT_SPECIES_RANKS:
                # 2 明らかに種より上のランクの場合（DBへの再帰問い合わせをスキップ）
                base_data["status"] = "invalid_rank"
                
            else:
                # 3 no rank 等、下位階層の可能性があるためDBで再帰チェックを保留
                base_data["status"] = "invalid_rank"
                if tax_id != "unknown":
                    pending_recursive_check[org] = tax_id
                    
            tax_data[org] = base_data
        else:
            tax_data[org] = {"status": "not_found", "is_species_or_below": False}

    # =========================================================
    # 未解決のノード（no rank等）に対して、DB側で一括再帰チェック
    # =========================================================
    if pending_recursive_check:
        ut_ids_to_check = tuple(set(pending_recursive_check.values()))
        
        recursive_query = """
            WITH RECURSIVE tax_path AS (
                SELECT ut_id AS original_ut_id, ut_id, p_ut_id, ut_rank, 0 AS steps
                FROM public.utax_nodes
                WHERE ut_id IN %s

                UNION ALL

                SELECT c.original_ut_id, p.ut_id, p.p_ut_id, p.ut_rank, c.steps + 1
                FROM public.utax_nodes p
                INNER JOIN tax_path c ON p.ut_id = c.p_ut_id
                WHERE c.steps < 10
            )
            SELECT DISTINCT original_ut_id
            FROM tax_path
            WHERE ut_rank IN ('species', 'forma', 'subspecies', 'varietas')
        """
        try:
            with db_conn.cursor() as cursor:
                cursor.execute(recursive_query, (ut_ids_to_check,))
                valid_ut_ids = {row[0] for row in cursor.fetchall()}
                
            for org, u_id in pending_recursive_check.items():
                if u_id in valid_ut_ids:
                    tax_data[org]["is_species_or_below"] = True
                    
                    best_match = sorted(temp_results[org.lower()], key=lambda x: x[0])[0]
                    priority, _, sci_name = best_match[0], best_match[1], best_match[2]
                    
                    if priority == 1:
                        if org == sci_name:
                            tax_data[org]["status"] = "valid"
                        else:
                            tax_data[org]["status"] = "fixable"
                            tax_data[org]["type"] = "case correction"
                    else:
                        tax_data[org]["status"] = "fixable"
                        
        except Exception as e:
            print(f"[WARN] Failed to check recursive taxonomy ranks: {e}")

    return tax_data

# ==============================================================================
# NCBI API を使用した代替Taxonomy情報取得（内部DBをスキップした場合に使用）
# ==============================================================================
def fetch_taxonomy_from_ncbi(organism_list):
    tax_data = {}
    if not organism_list:
        return tax_data
        
    unique_orgs = list(set(organism_list))
    api_key = os.environ.get("NCBI_API_KEY")
    
    for org in unique_orgs:
        # 1. Esearch で Taxonomy ID を取得
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        search_params = {
            "db": "taxonomy",
            "term": org,
            "retmode": "json",
            "retmax": 1
        }
        if api_key: search_params["api_key"] = api_key
        
        try:
            res = requests.get(search_url, params=search_params, timeout=10)
            res.raise_for_status()
            data = res.json()
            idlist = data.get("esearchresult", {}).get("idlist", [])
            
            if not idlist:
                tax_data[org] = {"status": "not_found", "is_species_or_below": False}
                time.sleep(0.15 if api_key else 0.35)
                continue
            
            tax_id = idlist[0]
            
            # 2. Efetch で XML フォーマットの詳細情報を取得
            fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            fetch_params = {
                "db": "taxonomy",
                "id": tax_id,
                "retmode": "xml"
            }
            if api_key: fetch_params["api_key"] = api_key
            
            f_res = requests.get(fetch_url, params=fetch_params, timeout=10)
            f_res.raise_for_status()
            
            root = ET.fromstring(f_res.content)
            taxon = root.find(".//Taxon")
            
            if taxon is not None:
                sci_name = taxon.findtext("ScientificName", "")
                rank = taxon.findtext("Rank", "unknown").lower()
                
                gen_code = int(taxon.findtext(".//GeneticCode/GCId", "1"))
                mi_code = int(taxon.findtext(".//MitoGeneticCode/MGCId", "1"))
                
                pl_code_elem = taxon.find(".//PlastidGeneticCode/PGCId")
                pl_code = int(pl_code_elem.text) if pl_code_elem is not None else 0
                
                lineage = taxon.findtext(".//Lineage", "")
                
                div_full = taxon.findtext(".//Division", "Unassigned")
                div_code = NCBI_DIVISION_MAP.get(div_full, "UNA")                
                
                # NCBI APIの LineageEx には親ノードの詳細配列が含まれるため、
                # そこに species レベルの親がいれば species_or_below だと判定（再帰クエリの代用）
                is_species_or_below = False
                if rank in ALLOWED_RANKS:
                    is_species_or_below = True
                elif rank not in DEFINITELY_NOT_SPECIES_RANKS:
                    for taxon_node in taxon.findall(".//LineageEx/Taxon"):
                        node_rank = taxon_node.findtext("Rank", "").lower()
                        if node_rank in ALLOWED_RANKS:
                            is_species_or_below = True
                            break
                
                if is_species_or_below:
                    if org.lower() == sci_name.lower():
                        status = "valid"
                        match_type = "scientific name"
                    else:
                        status = "fixable"
                        match_type = "synonym"
                else:
                    status = "invalid_rank"
                    match_type = "scientific name"

                tax_group = get_tax_group(org, lineage)

                tax_data[org] = {
                    "scientific_name": sci_name,
                    "rank": rank,
                    "type": match_type,
                    "gen_code": gen_code,
                    "mi_code": mi_code,
                    "pl_code": pl_code,
                    "tax_id": tax_id,
                    "lineage": lineage,
                    "division": div_code,
                    "status": status,
                    "is_species_or_below": is_species_or_below,
                    "tax_group": tax_group
                }
            else:
                tax_data[org] = {"status": "not_found", "is_species_or_below": False}

            # NCBI E-utilities の利用ガイドラインに基づきウェイトを入れる
            time.sleep(0.15 if api_key else 0.35)
            
        except Exception as e:
            print(f"[WARN] NCBI Taxonomy API failed for '{org}': {e}")
            tax_data[org] = {"status": "not_found", "is_species_or_below": False}
            
    return tax_data