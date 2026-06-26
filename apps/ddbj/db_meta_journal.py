"""db_metadata から分割: journal 関連の DB 取得関数。"""
import logging
from common.db_manager import execute_in_query

logger = logging.getLogger(__name__)


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

    # jr_medabbrev だけでなく、jr_title や jr_isoabbrev も小文字化してマッチさせる
    # IN 句が3つあり、いずれも同じ件数のプレースホルダ。パラメータは clean_journals を3回分渡す。
    query = """
        SELECT jr_title, jr_medabbrev, jr_isoabbrev
        FROM public.entrez_journal
        WHERE LOWER(jr_title) IN ({placeholders})
           OR LOWER(jr_medabbrev) IN ({placeholders})
           OR LOWER(jr_isoabbrev) IN ({placeholders})
    """

    valid_journals = set()
    try:
        for row in execute_in_query(db_conn, query, clean_journals, params=clean_journals * 3):
            # 取得できた行のカラム（タイトルや略称）をすべて「生の文字列のまま」入れる
            for jr_name in row:
                if jr_name:
                    valid_journals.add(str(jr_name).strip())
    except Exception as e:
        logger.warning(f"Failed to fetch journal names from DB: {e}")
        
    return valid_journals
