import os
import re
import time
import requests

# 対象とするNCBI/EBIのプレフィックス定義
_TARGET_PATTERNS = {
    "bioproject": re.compile(r"^PRJ(NA|EA|EB)\d+"),   
    "biosample": re.compile(r"^SAM(N|E[AG])\d+"),
    "sra": re.compile(r"^[SE]RR\d+")
}

# データベースごとの正確なアクセッション検索タグ
_DB_FIELD_TAGS = {
    "bioproject": "[Project Accession]",
    "biosample": "[Accession]",
    "sra": "[Accession]"
}

def filter_target_accessions(db_name, accessions):
    """DDBJ(D)を除外し、NCBI(N)とEBI(E)のアクセッションのみを抽出する"""
    pattern = _TARGET_PATTERNS.get(db_name)
    if not pattern:
        return []
    return [acc for acc in accessions if pattern.match(acc.strip())]

def check_ncbi_public_status(db_name, accessions, chunk_size=100):
    """
    指定されたアクセッションリストからNCBI/EBI対象のものだけを抽出し、
    E-utilities で公開状況を一括チェックする。
    """
    results = {"public": [], "private": [], "skipped": []}
    
    target_accs = filter_target_accessions(db_name, accessions)
    results["skipped"] = [acc for acc in accessions if acc not in target_accs]
    
    if not target_accs:
        return results

    unique_accs = list(set(target_accs))
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    field_tag = _DB_FIELD_TAGS.get(db_name, "[Accession]")

    # 実行時に最新の環境変数を取得
    current_api_key = os.environ.get("NCBI_API_KEY")

    def check_chunk(chunk):
        # SRAのあいまい検索を防ぐため、正確なフィールドタグを付与
        term = " OR ".join(f"{acc}{field_tag}" for acc in chunk)
        payload = {
            "db": db_name,
            "term": term,
            "retmode": "json",
            "retmax": 0
        }
        if current_api_key:
            payload["api_key"] = current_api_key

        response = requests.post(base_url, data=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        esearchresult = data.get("esearchresult", {})
        
        count = int(esearchresult.get("count", "0"))
        
        # 1. 完全に存在しない場合
        if count == 0:
            return [], chunk
            
        # 2. すべてが綺麗に1件ずつヒットした場合
        if count == len(chunk):
            return chunk, []
            
        # 3. エラーリストから抽出
        errorlist = esearchresult.get("errorlist", {})
        warninglist = esearchresult.get("warninglist", {})
        
        not_found_phrases = []
        not_found_phrases.extend(errorlist.get("phrasenotfound", []))
        not_found_phrases.extend(warninglist.get("phrasenotfound", []))
        not_found_phrases.extend(warninglist.get("quotedphrasesnotfound", []))
        
        private_in_chunk = []
        for phrase in not_found_phrases:
            clean_acc = re.sub(r'\[.*?\]', '', phrase).replace('"', '').strip()
            if clean_acc in chunk:
                private_in_chunk.append(clean_acc)
                
        public_in_chunk = [acc for acc in chunk if acc not in private_in_chunk]
        
        # 4. ヒット数と抽出数が矛盾する場合のフォールバック
        if len(public_in_chunk) != count:
            if len(chunk) > 1:
                # チャンクを解体して1件ずつ再帰的に検証
                pub_fb, priv_fb = [], []
                for single_acc in chunk:
                    p_pub, p_priv = check_chunk([single_acc])
                    pub_fb.extend(p_pub)
                    priv_fb.extend(p_priv)
                    time.sleep(0.15 if current_api_key else 0.35)
                return pub_fb, priv_fb
            else:
                # あいまい検索で余計なものがヒットしている等は「無効」として扱う
                return [], chunk
                
        return public_in_chunk, private_in_chunk

    for i in range(0, len(unique_accs), chunk_size):
        chunk = unique_accs[i : i + chunk_size]
        try:
            pub, priv = check_chunk(chunk)
            results["public"].extend(pub)
            results["private"].extend(priv)
            time.sleep(0.15 if current_api_key else 0.35)
        except Exception as e:
            print(f"[Warning] NCBI API request failed for {db_name}: {e}")
            
    return results