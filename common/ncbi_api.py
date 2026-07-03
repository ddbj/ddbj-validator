import os
import re
import time
import logging
import requests

logger = logging.getLogger(__name__)

# NCBI E-utilities 推奨のアプリ名（tool）。本ツールで固定。
_NCBI_TOOL = "ddbj-validator"
# key/email なし利用の警告は 1 回だけ出す
_ncbi_no_id_warned = False


def ncbi_identity_params():
    """NCBI E-utilities 共通の識別パラメータ {tool, email?, api_key?} を環境変数から構築する。

    NCBI ガイドライン準拠:
    - NCBI_API_KEY があれば付与（レート緩和 10 req/s・アカウント紐付け）。最優先。
    - NCBI_API_EMAIL があれば付与（key 無し時の連絡先。過剰アクセス時に NCBI から事前連絡を受けられる）。
    - tool は "ddbj-validator" 固定。
    key も email も無い場合は .env への設定を 1 回だけ警告する（メールはハードコードしない方針）。
    """
    global _ncbi_no_id_warned
    params = {"tool": _NCBI_TOOL}
    api_key = os.environ.get("NCBI_API_KEY")
    email = os.environ.get("NCBI_API_EMAIL")
    if api_key:
        params["api_key"] = api_key
    if email:
        params["email"] = email
    if not api_key and not email and not _ncbi_no_id_warned:
        logger.warning(
            "Using NCBI API without a key or email."
            "Please set NCBI_API_EMAIL in your .env file."
            "Obtaining an NCBI_API_KEY is recommended for frequent use.")
        _ncbi_no_id_warned = True
    return params


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

    # 実行時に最新の環境変数から識別パラメータ（tool/email/api_key）を構築
    identity = ncbi_identity_params()
    current_api_key = identity.get("api_key")

    def check_chunk(chunk):
        # SRAのあいまい検索を防ぐため、正確なフィールドタグを付与
        term = " OR ".join(f"{acc}{field_tag}" for acc in chunk)
        payload = {
            "db": db_name,
            "term": term,
            "retmode": "json",
            "retmax": 0,
            **identity,  # tool（＋あれば email / api_key）
        }

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
            logger.warning(f"NCBI API request failed for {db_name}: {e}")
            
    return results