import psycopg2
from apps.ddbj.utils.features import get_features
from apps.ddbj.db_metadata import get_organisms_from_records, get_expected_transl_table

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
            
            base_data = {
                "scientific_name": sci_name, "rank": rank, "type": best_type, 
                "gen_code": gen_code, "mi_code": mi_code, "pl_code": pl_code, 
                "tax_id": tax_id, "lineage": lineage, "division": division,
                "is_species_or_below": False
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
                